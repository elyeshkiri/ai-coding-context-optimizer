import json
import sys

import pytest

from acco.benchmark import task_definition_hash
from acco.experiment import _git as experiment_git
from acco.experiment import prompt_sha256, run_experiment, validate_suite
from acco.swebench_docker import (
    grade_swebench,
    parse_test_statuses,
    passed_tests,
    strip_test_file_changes,
)

TEST_PATCH = """diff --git a/tests/test_x.py b/tests/test_x.py
--- a/tests/test_x.py
+++ b/tests/test_x.py
@@ -1 +1,2 @@
 def test_old(): pass
+def test_target(): assert True
"""

AGENT_PATCH = """diff --git a/src/mod.py b/src/mod.py
--- a/src/mod.py
+++ b/src/mod.py
@@ -1 +1 @@
-x = 1
+x = 2
diff --git a/tests/test_x.py b/tests/test_x.py
--- a/tests/test_x.py
+++ b/tests/test_x.py
@@ -1 +1,2 @@
 def test_old(): pass
+def test_mine(): assert True
"""


def test_strip_test_file_changes_keeps_only_source_hunks():
    stripped = strip_test_file_changes(AGENT_PATCH, TEST_PATCH)
    assert "src/mod.py" in stripped
    assert "tests/test_x.py" not in stripped
    assert stripped.endswith("+x = 2\n")


def test_strip_test_file_changes_can_leave_nothing():
    only_tests = AGENT_PATCH[AGENT_PATCH.index("diff --git a/tests"):]
    assert strip_test_file_changes(only_tests, TEST_PATCH) == ""


def test_parse_test_statuses_reads_pytest_short_summary():
    out = "\n".join([
        "PASSED tests/a.py::test_ok[True]",
        "FAILED tests/a.py::test_bad - AssertionError: assert 1 == 2",
        "ERROR tests/b.py::test_env - recursive dependency",
        "collected 3 items",
    ])
    assert parse_test_statuses(out) == {
        "tests/a.py::test_ok[True]": "PASSED",
        "tests/a.py::test_bad": "FAILED",
        "tests/b.py::test_env": "ERROR",
    }
    assert passed_tests(out) == {"tests/a.py::test_ok[True]"}


def test_parse_test_statuses_ignores_forced_color_output():
    # astropy's official image runs pytest with --color=yes.
    out = "\n".join([
        "\x1b[32mPASSED\x1b[0m t.py::\x1b[1mtest_ok[a]\x1b[0m",
        "\x1b[31mFAILED\x1b[0m t.py::\x1b[1mtest_bad\x1b[0m - IndexError: boom",
    ])
    assert parse_test_statuses(out) == {
        "t.py::test_ok[a]": "PASSED",
        "t.py::test_bad": "FAILED",
    }


def test_grade_ignores_preexisting_errors_but_catches_regressions():
    reference = {"t::keep", "t::other"}
    ok = grade_swebench(["t::target"], reference, {"t::target", "t::keep", "t::other"})
    assert ok["resolved"] and ok["regression_count"] == 0

    regressed = grade_swebench(["t::target"], reference, {"t::target", "t::keep"})
    assert not regressed["resolved"] and regressed["regressions"] == ["t::other"]

    unfixed = grade_swebench(["t::target"], reference, {"t::keep", "t::other"})
    assert not unfixed["resolved"] and unfixed["fail_to_pass_passed"] == 0

    assert not grade_swebench(["t::target"], reference, set())["resolved"]


def test_git_helper_can_preserve_trailing_newline(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "f").write_text("x\n")
    assert experiment_git(tmp_path, "ls-files", "--others").endswith("f")
    assert experiment_git(tmp_path, "ls-files", "--others", strip=False).endswith("\n")


def _swebench_suite(tmp_path):
    import subprocess

    repo = tmp_path / "source"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "mod.py").write_text("x = 1\n")
    (repo / "tests" / "test_x.py").write_text("def test_old(): pass\n")
    for cmd in (
        ["init", "-q"],
        ["config", "user.email", "b@example.test"],
        ["config", "user.name", "B"],
        ["add", "."],
        ["commit", "-qm", "fixture"],
    ):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True)
    revision = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True, capture_output=True, check=True,
    ).stdout.strip()

    runner = tmp_path / "runner.py"
    runner.write_text(
        """
import json, pathlib, sys
pathlib.Path("src/mod.py").write_text("x = 2\\n")
with open("tests/test_x.py", "a") as f:
    f.write("def test_mine(): assert True\\n")
t = pathlib.Path(sys.argv[1]); t.parent.mkdir(parents=True, exist_ok=True)
t.write_text(json.dumps({"type": "assistant", "message": {
    "id": "m", "model": "synthetic-test-model", "content": [],
    "usage": {"input_tokens": 1, "cache_creation_input_tokens": 0,
              "cache_read_input_tokens": 0, "output_tokens": 1}}}) + "\\n")
""".lstrip()
    )
    prompt = "Fix x."
    suite = {
        "suite_version": 1,
        "protocol": {
            "task_definitions_frozen": True,
            "condition_order_randomized": True,
            "independent_verification": True,
            "history_isolated": True,
            "hidden_tests_after_agent": True,
            "frozen_at": "2026-09-19T00:00:00Z",
            "task_definition_sha256": "",
        },
        "design": {"trials_per_task": 1, "condition_order_seed": 1},
        "repositories": {"fixture": {"path": "source", "revision": revision}},
        "runner": {
            "command": [sys.executable, str(runner), "{transcript}"],
            "model": "synthetic-test-model",
            "transcript_mode": "path",
            "timeout_seconds": 30,
        },
        "tasks": [{
            "id": "swe-task",
            "repository": "fixture",
            "revision": revision,
            "prompt": prompt,
            "prompt_sha256": prompt_sha256(prompt),
            "test_patch": TEST_PATCH,
            "swebench": {"image": "img", "test_command": "pytest -rA", "env_activate": "true"},
            "source": {"fail_to_pass": ["tests/test_x.py::test_target"]},
        }],
    }
    suite["protocol"]["task_definition_sha256"] = task_definition_hash(suite)
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(suite))
    return path


def test_swebench_run_survives_all_three_harness_failure_modes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "acco.experiment.user_acco_hook_configured", lambda: False
    )
    calls = []

    def fake_verify(*, agent_patch, test_patch, stdout_path, stderr_path, **_):
        text = agent_patch.read_text()
        calls.append(text)
        if text:
            # (1) the patch must be intact and (2) must not touch the hidden test file
            assert text.endswith("\n"), "agent patch lost its trailing newline"
            assert "tests/test_x.py" not in text
            lines = ["PASSED tests/test_x.py::test_target", "PASSED tests/test_x.py::test_old"]
        else:
            lines = ["FAILED tests/test_x.py::test_target - assert", "PASSED tests/test_x.py::test_old"]
        # (3) pre-existing image errors make the whole command exit nonzero
        lines.append("ERROR tests/test_env.py::test_broken_fixture - recursive dependency")
        stdout_path.write_text("\n".join(lines) + "\n")
        stderr_path.write_text("")
        return 1, 0.1

    monkeypatch.setattr("acco.swebench_docker.verify_swebench", fake_verify)
    result = run_experiment(
        _swebench_suite(tmp_path), tmp_path / "runs.json", allow_development=True
    )

    assert len(result["runs"]) == 2 and all(run["success"] for run in result["runs"])
    step = result["runs"][0]["verification"][0]
    assert step["exit_code"] == 1 and step["grade"]["resolved"]
    assert (tmp_path / "runs.artifacts" / "_reference" / "swe-task" / "swebench.stdout").is_file()
    # reference computed once (empty patch) and reused for both arms
    assert sum(1 for c in calls if c == "") == 1
    recorded = tmp_path / "runs.artifacts" / "swe-task" / "trial-1"
    for arm in ("baseline", "enabled"):
        full = (recorded / arm / "agent.patch").read_text()
        assert full.endswith("\n") and "tests/test_x.py" in full  # record stays complete


def test_swebench_regression_against_reference_fails_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "acco.experiment.user_acco_hook_configured", lambda: False
    )

    def fake_verify(*, agent_patch, stdout_path, stderr_path, **_):
        fixed = bool(agent_patch.read_text())
        lines = ["PASSED tests/test_x.py::test_target"] if fixed else [
            "FAILED tests/test_x.py::test_target - assert",
            "PASSED tests/test_x.py::test_old",
        ]
        stdout_path.write_text("\n".join(lines) + "\n")
        stderr_path.write_text("")
        return 0, 0.1

    monkeypatch.setattr("acco.swebench_docker.verify_swebench", fake_verify)
    result = run_experiment(
        _swebench_suite(tmp_path), tmp_path / "runs.json", allow_development=True
    )
    step = result["runs"][0]["verification"][0]
    assert not any(run["success"] for run in result["runs"])
    assert step["grade"]["regressions"] == ["tests/test_x.py::test_old"]


def test_swebench_task_requires_fail_to_pass(tmp_path):
    path = _swebench_suite(tmp_path)
    suite = json.loads(path.read_text())
    del suite["tasks"][0]["source"]
    path.write_text(json.dumps(suite))
    with pytest.raises(ValueError, match="fail_to_pass"):
        validate_suite(path, require_frozen=False, require_broad=False)
