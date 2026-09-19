from token_saver.output_processors import (
    ProcessorRegistry,
    explain_processor,
    process_output,
)


def test_pytest_failure_uses_failure_aware_processor_and_preserves_assertion():
    chatter = "\n".join(f"collecting {i}" for i in range(150))
    text = (
        chatter
        + "\n============================= FAILURES =============================\n"
        + "____________________________ test_refresh ____________________________\n"
        + "E   AssertionError: expected 200, got 401\n"
        + "=========================== short test summary info ===========================\n"
        + "FAILED tests/test_auth.py::test_refresh - AssertionError: expected 200, got 401\n"
        + "======================= 1 failed, 40 passed in 1.2s =======================\n"
    )
    result = process_output(text, "pytest -q", exit_code=1, min_reduction=0.0)
    assert result.processor == "pytest"
    assert result.failed is True
    assert result.compressed is True
    assert "AssertionError: expected 200, got 401" in result.text
    assert result.text.count("collecting") < 10


def test_failed_install_skips_success_only_processor():
    text = ("npm ERR! could not resolve dependency\n" * 80) + "fatal detail\n"
    result = process_output(
        text, "npm install", exit_code=1, min_reduction=0.0,
    )
    assert result.processor == "generic"
    assert result.text == text
    info = explain_processor("npm install", exit_code=1)
    assert info["processor"] == "generic"
    assert "package-install" in info["failure_skipped_processors"]


def test_critical_line_recovery_is_registry_wide():
    class Lossy:
        name = "lossy"
        priority = 1
        handles_failure = True

        def matches(self, command):
            return True

        def compress(self, command, text, *, failed, max_lines, keep_tail):
            return "short summary\n"

    class Generic:
        name = "generic"
        priority = 999
        handles_failure = True

        def matches(self, command):
            return True

        def compress(self, command, text, *, failed, max_lines, keep_tail):
            return text

    original = (
        "noise\n" * 200
        + "src/auth.py:42: AssertionError: refresh token expired\n"
        + "more noise\n" * 100
    )
    result = process_output(
        original,
        "custom check",
        exit_code=1,
        min_reduction=0.0,
        registry=ProcessorRegistry([Lossy(), Generic()]),
    )
    assert result.processor == "lossy"
    assert "src/auth.py:42: AssertionError: refresh token expired" in result.text
    assert result.recovered_lines


def test_ratio_gate_rejects_marginal_compression():
    class TinyTrim:
        name = "tiny"
        priority = 1
        handles_failure = True

        def matches(self, command):
            return True

        def compress(self, command, text, *, failed, max_lines, keep_tail):
            return text[:-1]

    class Generic(TinyTrim):
        name = "generic"
        priority = 999

    text = "x" * 1000
    result = process_output(
        text,
        "anything",
        min_reduction=0.02,
        registry=ProcessorRegistry([TinyTrim(), Generic()]),
    )
    assert result.text == text
    assert result.compressed is False
