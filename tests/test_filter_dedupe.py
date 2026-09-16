from token_saver.filter_output import filter_command_output, preprocess


def test_preprocess_collapses_consecutive_duplicate_success_lines():
    text = ("compiled module\n" * 100) + "done\n"
    out = preprocess(text)
    assert out.count("compiled module") == 1
    assert "repeated 99 more times" in out
    assert len(out) < len(text)


def test_json_compaction_happens_before_line_deduplication():
    text = '{\n  "items": [\n    1,\n    1,\n    1\n  ]\n}\n'
    out = preprocess(text)
    assert out.strip() == '{"items":[1,1,1]}'


def test_error_output_is_never_deduplicated_by_command_filter():
    text = ("ERROR connection refused\n" * 20) + "traceback detail\n"
    assert filter_command_output(text, command="python worker.py") == text
