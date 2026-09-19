"""0.6 regressions: host contracts, recovery, attribution and concurrent state.

Hook fixtures follow the documented API; these are NOT live Claude Code tests.
"""
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from token_saver.hook import run, main as hook_main
from token_saver.guard import decide_read
from token_saver.output_store import retrieve, store_output
from token_saver.sessions import Report, Turn, ToolCall, analyze
from token_saver.snippet import extract_symbol
from token_saver.state import load, record_read, seen_read
from token_saver.install import install, merge_hooks
from token_saver.pricing import cost


def bash(stdout, stderr='', **extra):
    return {'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
            'tool_input': {'command': 'npm test'}, 'session_id': 's',
            'tool_response': dict(stdout=stdout, stderr=stderr, interrupted=False, isImage=False, **extra)}


def noisy():
    return ''.join(f'progress line {i} ' + 'x' * 80 + '\n' for i in range(500))


def test_hook_emits_documented_structured_replacement_and_recovers_original():
    original = bash(noisy(), 'diagnostic on stderr\n', exitCode=3)
    _, result = run(original)
    output = result['hookSpecificOutput']['updatedToolOutput']
    assert 'updatedOutput' not in result['hookSpecificOutput']
    assert output['stderr'] == original['tool_response']['stderr']
    assert output['exitCode'] == 3
    assert output['interrupted'] is False and output['isImage'] is False
    output_id = re.search(r'token-saver output ([a-f0-9]{32})', output['stdout'])[1]
    assert retrieve(output_id, limit=1000) == original['tool_response']['stdout']
    assert retrieve(output_id, 'stderr') == original['tool_response']['stderr']
    assert retrieve(output_id, offset=250, limit=2) == ''.join(noisy().splitlines(True)[249:251])
    assert 'Re-run' not in output['stdout']
    assert len(output['stdout'].encode()) < len(noisy().encode())


@pytest.mark.parametrize('patch', [{'isImage': True}, {'interrupted': True}, {'stdout': ['structured']}, {'stderr': None}])
def test_unsupported_or_interrupted_bash_results_pass_through(patch):
    payload = bash(noisy()); payload['tool_response'].update(patch)
    assert run(payload) == (0, None)


def test_archive_failure_fails_open(monkeypatch, capsys):
    import io
    monkeypatch.setattr('token_saver.output_store.store_output', lambda _: (_ for _ in ()).throw(OSError('disk full')))
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(bash(noisy()))))
    assert hook_main() == 0
    assert capsys.readouterr().out == ''


def test_failure_name_stack_and_multiline_diff_survive():
    text = noisy() + '\nFAIL src/a.test.ts\n  ● missing user\nExpected: true\nReceived: false\n  at Object.<anonymous> (src/a.test.ts:42:17)\n - deleted value\n + actual value\n'
    assert run(bash(text)) == (0, None)


def test_saved_output_private_and_id_validated():
    output_id = store_output({'stdout': 'secret\n', 'stderr': ''})
    path = Path(os.environ['TOKEN_SAVER_STATE_DIR']) / 'outputs' / (output_id + '.json')
    if os.name != 'nt': assert path.stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError): retrieve('../../etc/passwd')
    with pytest.raises(ValueError): retrieve(output_id, offset=0)
    with pytest.raises(ValueError): retrieve(output_id, limit=3000)


def test_first_cache_write_is_not_churn():
    report = Report(turns=[Turn('s', created=30000)])
    assert report.cache_churn()[:2] == (0, 0)
    assert report.turns[0].cache_kind == 'initial_observation'


def test_large_prefix_growth_is_not_churn():
    report = Report(turns=[Turn('s', created=30000), Turn('s', created=50000, read=30000)])
    assert report.cache_churn()[0] == 0
    assert report.turns[1].cache_kind == 'prefix_growth'


def test_recreation_only_counts_overlap_not_new_content():
    report = Report(turns=[Turn('s', created=30000), Turn('s', created=60000)])
    assert report.cache_churn()[:2] == (30000, 1)


def test_reads_in_different_sessions_or_epochs_are_not_duplicates():
    report = Report(calls=[ToolCall('Read', 100, session, path='/a.py', digest='same', epoch=epoch)
                           for session, epoch in [('a', 0), ('a', 1), ('b', 0)]])
    assert report.duplicate_reads() == []


def transcript(tmp_path, records, name='s.jsonl'):
    path = tmp_path / name
    path.write_text('\n'.join(json.dumps(r) for r in records))
    return path


def assistant(mid, output=5, created=30000, read=0):
    return {'type': 'assistant', 'message': {'id': mid, 'model': 'test-model', 'content': [], 'usage': {
        'input_tokens': 10, 'output_tokens': output, 'cache_creation_input_tokens': created, 'cache_read_input_tokens': read,
        'cache_creation': {'ephemeral_5m_input_tokens': created}}}}


def test_streamed_usage_keeps_final_totals_without_double_count(tmp_path):
    report = analyze([transcript(tmp_path, [assistant('a', 0), assistant('a', 100), assistant('a', 50)])])
    assert report.usage['output_tokens'] == 100
    assert report.usage['cache_creation_input_tokens'] == 30000
    assert len(report.turns) == 1


def test_compaction_resets_cache_and_duplicate_attribution(tmp_path):
    result = {'type': 'user', 'toolUseResult': {'file': {'filePath': '/a.py', 'content': 'x=1\n'}}}
    records = [assistant('a'), result, {'type': 'system', 'subtype': 'compact_boundary'}, assistant('b'), result]
    report = analyze([transcript(tmp_path, records)])
    assert report.cache_churn()[0] == 0
    assert report.duplicate_reads() == []


@pytest.mark.parametrize('input_', [{'offset': 1}, {'limit': 99999}, {'limit': 0}, {'limit': -1}])
def test_guard_rejects_unbounded_or_oversized_windows(tmp_path, input_):
    path = tmp_path/'large.py'; path.write_text('x = 1\n'*300)
    assert decide_read(dict(file_path=str(path), **input_), tmp_path) is not None


def test_session_reset_does_not_erase_other_session(tmp_path):
    path = tmp_path/'a.py'; path.write_text('x=1\n')
    record_read(tmp_path, path, 'a', 'first')
    record_read(tmp_path, path, 'b', 'second')
    run({'hook_event_name': 'SessionStart', 'source': 'compact', 'session_id': 'first', 'cwd': str(tmp_path)})
    assert not seen_read(tmp_path, path, 'a', 'first')
    assert seen_read(tmp_path, path, 'b', 'second')


def _record_parallel(args):
    root, n = args
    record_read(Path(root), Path(root)/f'{n}.py', str(n), 'parallel')


def test_parallel_updates_do_not_lose_reads(tmp_path):
    with ProcessPoolExecutor(max_workers=4) as pool:
        list(pool.map(_record_parallel, [(str(tmp_path), i) for i in range(40)]))
    assert len(load(tmp_path, 'parallel')['reads']) == 40


def test_truncated_read_is_not_recorded_as_whole_file(tmp_path):
    path = tmp_path/'a.py'; path.write_text('x=1\n'*300)
    run({'hook_event_name':'PostToolUse','tool_name':'Read','cwd':str(tmp_path),'session_id':'s',
         'tool_input':{'file_path':str(path)},'tool_response':{'file':{'content':'x=1\n'}}})
    assert load(tmp_path,'s')['reads'] == {}


def test_install_preserves_shared_matchers_and_registers_compaction():
    existing = {'hooks': {'PostToolUse':[{'matcher':'Grep','hooks':[{'command':'token-saver hook'}, {'command':'other'}]}]}}
    before = json.dumps(existing)
    updated = merge_hooks(existing)
    assert json.dumps(existing) == before
    assert updated['hooks']['PostToolUse'][0]['matcher'] == 'Grep'
    assert 'compact' in updated['hooks']['SessionStart'][0]['matcher']
    assert merge_hooks(updated) == updated


def test_install_does_not_overwrite_bad_settings(tmp_path):
    path=tmp_path/'.claude'/'settings.json';path.parent.mkdir();path.write_text('{broken')
    with pytest.raises(ValueError): install(tmp_path)
    assert path.read_text() == '{broken'


@pytest.mark.parametrize('suffix,source,name,expected', [
    ('.ts', 'export const fetchUser = async (id: string) => { return id; };', 'fetchUser','return id'),
    ('.js', 'class API { fetchUser(id) { return id; } }', 'API.fetchUser','return id'),
    ('.ts', 'class API { fetchUser = (id: string) => id; }', 'API.fetchUser','=> id'),
    ('.tsx', 'export const Card = () => <div title="}">hello</div>;', 'Card','<div'),
    ('.js', 'const api = { run: () => ({value: "}"}) };', 'api.run','value'),
    ('.js', 'const api = { run() { return /}/.test("}"); } };', 'api.run','/}/'),
])
def test_syntax_aware_symbols(suffix,source,name,expected):
    hit=extract_symbol(source,suffix,name)
    assert hit and expected in hit[0]


def test_long_symbol_not_silently_truncated():
    src='function longOne() {\n'+'  step();\n'*200+'  return "last";\n}\nfunction unrelated() {}'
    hit=extract_symbol(src,'.js','longOne')
    assert 'last' in hit[0] and 'unrelated' not in hit[0]
    assert hit[2] > 120


def test_same_line_sibling_not_in_snippet():
    hit=extract_symbol('const first=()=>1, second=()=>2;', '.js','first')
    assert 'second' not in hit[0]


def test_ambiguous_methods_require_qualification():
    src='class A { run() {} } class B { run() {} }'
    with pytest.raises(ValueError,match='Ambiguous'): extract_symbol(src,'.js','run')
    assert extract_symbol(src,'.js','B.run')


def test_invalid_js_not_given_guessed_boundaries():
    with pytest.raises(ValueError,match='syntax'): extract_symbol('function x( {','.js','x')


def test_python_qualified_methods():
    src='class A:\n def run(self): pass\nclass B:\n def run(self): pass\n'
    with pytest.raises(ValueError): extract_symbol(src,'.py','run')
    assert extract_symbol(src,'.py','B.run')[1] == 4


def test_pricing_uses_model_and_ttl():
    report=Report(turns=[Turn('s',created=300,read=100,input_tokens=10,output_tokens=20,cache_5m=100,cache_1h=200,model='x')])
    rates={'x':{'input':1,'output':5,'cache_write_5m':1.25,'cache_write_1h':2,'cache_read':.1}}
    assert cost(report,rates)['usd'] == pytest.approx((10+100+125+400+10)/1e6)
    assert cost(report,{})['usd'] is None
    report.turns[0].cache_5m=0
    assert cost(report,rates)['usd'] is None


def test_subprocess_hook_contract(tmp_path):
    proc=subprocess.run([sys.executable,'-m','token_saver.hook'],input=json.dumps(bash(noisy())),text=True,capture_output=True)
    assert proc.returncode == 0
    response=json.loads(proc.stdout)['hookSpecificOutput']
    assert response['hookEventName'] == 'PostToolUse'
    assert isinstance(response['updatedToolOutput']['stdout'],str)


def test_benchmark_compares_actual_usage_and_quality(tmp_path):
    from token_saver.benchmark import evaluate
    rate={'test-model':{'input':1,'output':5,'cache_write_5m':1.25,'cache_write_1h':2,'cache_read':.1}}
    rates=tmp_path/'rates.json';rates.write_text(json.dumps(rate))
    transcript(tmp_path,[assistant('a',created=40000)],'before.jsonl')
    transcript(tmp_path,[assistant('b',created=20000)],'after.jsonl')
    runs=[dict(task='fix',trial=1,revision='abc',model='test-model',prompt_sha256='0'*64,validation='independent tests passed',
               condition=arm,success=True,seconds=2,transcripts=[file]) for arm,file in [('baseline','before.jsonl'),('enabled','after.jsonl')]]
    manifest=tmp_path/'runs.json';manifest.write_text(json.dumps({'runs':runs}))
    result=evaluate(manifest,rates)
    assert result['paired_trials'] == 1
    assert 49 < result['cost_per_success_reduction_percent'] < 50
    runs[1]['success']=False;manifest.write_text(json.dumps({'runs':runs}))
    assert evaluate(manifest,rates)['cost_per_success_reduction_percent'] is None
    runs[1]['revision']='different';manifest.write_text(json.dumps({'runs':runs}))
    with pytest.raises(ValueError,match='paired'): evaluate(manifest,rates)
