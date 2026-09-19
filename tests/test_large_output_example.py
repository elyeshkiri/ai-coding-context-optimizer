"""The large-output demo must genuinely trigger both Token Saver savings paths."""

import subprocess
import sys
from pathlib import Path

import pytest

from token_saver.estimate import estimate_tokens
from token_saver.hook import run

sys.path.insert(0, str(Path(__file__).parents[1] / "examples" / "large_output_demo"))
import make_project as demo  # noqa: E402


@pytest.fixture()
def project(tmp_path):
    return demo.make_project(tmp_path / "shop-project")


def _pytest(project):
    return subprocess.run(
        [sys.executable, "-m", "pytest"], cwd=project, text=True, capture_output=True,
    )


def test_project_has_exactly_the_one_boundary_bug(project):
    proc = _pytest(project)
    assert proc.returncode == 1
    assert "1 failed, 606 passed" in proc.stdout
    assert "FAILED tests/test_bulk.py::test_discount_at_threshold" in proc.stdout


def test_reference_fix_makes_the_suite_and_hidden_tests_pass(project):
    catalog = project / "shop" / "catalog.py"
    assert demo.BUGGY_LINE in catalog.read_text()
    catalog.write_text(catalog.read_text().replace(demo.BUGGY_LINE, demo.FIXED_LINE))
    (project / "tests" / "test_bulk_hidden.py").write_text(demo.HIDDEN_TEST)
    proc = _pytest(project)
    assert proc.returncode == 0, proc.stdout[-400:]


def test_test_run_output_is_filtered_but_keeps_the_failure(project):
    proc = _pytest(project)
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "python3 -m pytest"},
        "tool_response": {
            "stdout": proc.stdout, "stderr": "", "interrupted": False, "isImage": False,
        },
    }
    code, response = run(payload)
    assert code == 0 and response is not None, "hook did not filter the noisy test run"
    filtered = response["hookSpecificOutput"]["updatedToolOutput"]["stdout"]

    assert len(filtered.splitlines()) < len(proc.stdout.splitlines()) / 5
    assert estimate_tokens(filtered) < estimate_tokens(proc.stdout) / 4
    # the evidence the agent needs survives
    assert "test_discount_at_threshold" in filtered
    assert "assert 125.0 == 112.5" in filtered
    assert "1 failed, 606 passed" in filtered
    assert "token-saver output" in filtered  # recovery path for the omitted lines


def test_whole_file_read_of_the_large_module_is_redirected(project):
    catalog = project / "shop" / "catalog.py"
    assert len(catalog.read_text().splitlines()) > 500
    code, response = run({
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "cwd": str(project),
        "tool_input": {"file_path": str(catalog)},
    })
    assert code == 0 and response is not None, "large Read was not intercepted"
    decision = response["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "bulk_discount" in decision["permissionDecisionReason"]


def test_demo_rates_cover_the_supported_models():
    from token_saver.pricing import load_rates

    rates = load_rates(Path(demo.__file__).with_name("rates.json"))
    assert {"claude-haiku-4-5-20251001", "claude-sonnet-5"} <= set(rates)


def test_cat_of_the_large_module_through_bash_is_redirected_too(project):
    """The route that slipped past the guard in the Sonnet 5 demo run."""
    code, response = run({
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": str(project),
        "tool_input": {"command": "cat shop/catalog.py"},
    })
    assert code == 0 and response is not None, "cat of the large module was not intercepted"
    decision = response["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "bulk_discount" in decision["permissionDecisionReason"]
