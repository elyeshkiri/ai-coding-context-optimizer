import json
import textwrap

from token_saver.serve import call_tool


def _payload(result):
    return json.loads(result['content'][0]['text'])


def test_mcp_context_browser_returns_ranked_source_candidates(tmp_path):
    (tmp_path / 'views.py').write_text(textwrap.dedent('''
        def renderTemplate(template):
            return template
    '''))

    result = call_tool(
        tmp_path,
        'browse_context',
        {'query': 'rendr template', 'max_files': 3, 'preview_tokens': 200},
    )
    payload = _payload(result)

    assert payload['candidate_count'] >= 1
    assert payload['files'][0]['path'] == 'views.py'
    assert any('renderTemplate@' in label for label in payload['files'][0]['symbols'])
