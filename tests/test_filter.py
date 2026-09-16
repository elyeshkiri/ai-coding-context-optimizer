"""Regressions for the output filter."""

from token_saver.filter_output import filter_command_output, filter_text, preprocess


def _lines(text: str) -> list[str]:
    return text.splitlines()


def test_short_input_passes_through():
    text = "a\nb\nc\n"
    assert filter_text(text, max_lines=80) == text


def test_missing_trailing_newline_is_added():
    assert filter_text("a\nb") == "a\nb\n"


def test_empty_input():
    assert filter_text("") == ""


def test_head_and_tail_never_overlap():
    """Regression: max_lines smaller than the 10-line head floor duplicated input."""
    text = "\n".join(str(i) for i in range(1, 7)) + "\n"
    out = filter_text(text, max_lines=5, keep_tail=20)
    assert out == text, "filter must not duplicate a 6-line input"


def test_never_grows_the_input():
    """A filter that emits more bytes than it consumed is worse than no filter."""
    text = "\n".join(f"fail {i}" for i in range(100)) + "\n"
    out = filter_text(text)
    assert len(out) <= len(text)


def test_never_grows_on_pathological_sizes():
    for n in range(1, 60):
        for max_lines in (1, 2, 5, 11, 30, 80):
            text = "\n".join(f"error {i}" for i in range(n)) + "\n"
            out = filter_text(text, max_lines=max_lines)
            assert len(out) <= len(text), (n, max_lines)
            # same input without a trailing newline: only the newline may be added
            bare = text.rstrip("\n")
            out = filter_text(bare, max_lines=max_lines)
            assert len(out) <= len(bare) + 1, (n, max_lines)


def test_omitted_count_is_accurate():
    """Regression: the count was computed before error lines were added back."""
    text = "\n".join(
        f"line {i}" + (" ERROR boom" if i % 4 == 0 else "") for i in range(200)
    )
    out = filter_text(text, max_lines=80, keep_tail=20)
    header = _lines(out)[0]
    claimed = int(header.split(";")[1].strip().split()[0])

    shown = [
        ln
        for ln in _lines(out)[1:]
        if ln not in ("--- matching errors ---", "--- tail ---")
    ]
    assert claimed == 200 - len(shown)


def test_keeps_errors_from_the_middle():
    lines = ["noise"] * 200
    lines[100] = "AssertionError: needle"
    out = filter_text("\n".join(lines))
    assert "AssertionError: needle" in out


def test_deduplicates_repeated_error_lines():
    lines = ["noise"] * 40 + ["ERROR same"] * 60 + ["noise"] * 40
    out = filter_text("\n".join(lines))
    assert out.count("ERROR same") < 60


def test_compresses_a_long_quiet_log():
    text = "\n".join(f"line {i}" for i in range(5000))
    out = filter_text(text)
    assert len(_lines(out)) < 120
    assert "line 0" in out
    assert "line 4999" in out


def test_preprocess_strips_ansi_and_minifies_json():
    colored = "\x1b[31merror\x1b[0m\n"
    assert "error" in preprocess(colored)
    assert "\x1b" not in preprocess(colored)
    fat = '{\n  "a": 1,\n  "b": 2\n}\n'
    slim = preprocess(fat)
    assert slim.count("\n") <= 1
    assert '"a":1' in slim.replace(" ", "")


def test_pytest_keeps_failures_not_collection():
    chatter = "\n".join(f"collecting {i}" for i in range(200))
    text = (
        chatter
        + "\n============================= FAILURES =============================\n"
        + "E   AssertionError: needle\n"
        + "=========================== short test summary info ===========================\n"
        + "FAILED tests/test_x.py::test_y\n"
        + "======================= 1 failed, 40 passed in 1.2s =======================\n"
    )
    out = filter_command_output(text, command="pytest -q")
    assert "AssertionError: needle" in out
    assert out.count("collecting") < 10
    assert len(out) < len(text)
