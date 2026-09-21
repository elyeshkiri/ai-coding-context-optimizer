"""Regression coverage for the expanded CLI-output processor inventory."""

import pytest

from token_saver.output import DEFAULT_REGISTRY
from token_saver.output_processors import explain_processor, process_output


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("git diff --cached", "git-diff"),
        ("git show HEAD", "git-show"),
        ("git branch -a", "git-branch"),
        ("git push origin main", "git-remote"),
        ("docker build .", "docker-build"),
        ("docker ps -a", "docker-ps"),
        ("docker compose up", "docker-compose"),
        ("docker inspect app", "docker-inspect"),
        ("kubectl get pods", "kubectl-get"),
        ("kubectl describe pod api", "kubectl-describe"),
        ("kubectl get events", "kubectl-events"),
        ("terraform plan", "terraform-plan"),
        ("terraform apply -auto-approve", "terraform-apply"),
        ("helm upgrade api chart/", "helm"),
        ("pulumi up", "pulumi"),
        ("cargo build", "cargo-build"),
        ("cargo clippy", "cargo-clippy"),
        ("cargo test", "cargo-test"),
        ("go build ./...", "go-build"),
        ("go test ./...", "go-test"),
        ("./mvnw test", "maven"),
        ("./gradlew test", "gradle"),
        ("ruff check .", "ruff"),
        ("npx eslint src", "eslint"),
        ("python -m pylint src", "pylint"),
        ("npx tsc --noEmit", "tsc"),
        ("python -m mypy src", "mypy"),
        ("jq '.items[]' data.json", "jq-yq"),
    ],
)
def test_specialized_processor_routing(command, expected):
    """Every added CLI family should route before the broad fallback processors."""
    info = explain_processor(command, exit_code=0)
    assert info["processor"] == expected


def test_default_registry_contains_exactly_40_unique_processors():
    """The expanded built-in inventory should contain forty unique processors."""
    names = [processor.name for processor in DEFAULT_REGISTRY.processors]
    assert len(names) == 40
    assert len(set(names)) == 40
    assert names[-1] == "generic"


def test_git_diff_preserves_every_changed_line_while_dropping_context():
    """Diff compression must retain edits instead of blindly truncating the patch."""
    context = "\n".join(f" unchanged context {index}" for index in range(180))
    text = (
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,3 +1,3 @@\n"
        f"{context}\n"
        "-old_value = 1\n"
        "+new_value = 2\n"
    )
    result = process_output(text, "git diff", exit_code=0, min_reduction=0.0)
    assert result.processor == "git-diff"
    assert result.compressed is True
    assert "-old_value = 1" in result.text
    assert "+new_value = 2" in result.text
    assert "unchanged context 100" not in result.text


@pytest.mark.parametrize(
    ("command", "expected", "diagnostic"),
    [
        ("docker build .", "docker-build", "ERROR: failed to solve build graph"),
        ("terraform plan", "terraform-plan", "Error: invalid resource reference"),
        ("cargo build", "cargo-build", "error[E0382]: borrow of moved value"),
        ("go build ./...", "go-build", "main.go:18:9: undefined: session"),
        ("./mvnw test", "maven", "[ERROR] Failed to execute goal"),
        ("./gradlew test", "gradle", "FAILURE: Build failed with an exception."),
        ("ruff check .", "ruff", "src/app.py:42:5: F821 Undefined name 'user'"),
        ("npx tsc --noEmit", "tsc", "src/app.ts(10,4): error TS2322: bad type"),
    ],
)
def test_specialized_failure_processors_preserve_diagnostics(
    command,
    expected,
    diagnostic,
):
    """Failure-aware specializations must retain the actionable diagnostic."""
    text = ("progress line\n" * 220) + diagnostic + "\n"
    result = process_output(text, command, exit_code=1, min_reduction=0.0)
    assert result.processor == expected
    assert diagnostic in result.text



def test_git_status_preserves_untracked_filename():
    """Human-readable git status must retain files listed under Untracked files."""
    text = (
        "On branch feature\n"
        "Untracked files:\n"
        "  new_file.py\n"
        + ("hint line\n" * 120)
    )
    result = process_output(text, "git status", exit_code=0, min_reduction=0.0)
    assert result.processor == "git-status"
    assert "new_file.py" in result.text


def test_docker_build_drops_progress_but_preserves_failure():
    """BuildKit progress chatter should not crowd out the actionable failure."""
    text = (
        "\n".join(f"#12 0.1 compiling layer {index}" for index in range(120))
        + "\n#13 ERROR: process failed\n"
        + "ERROR: failed to solve build graph\n"
    )
    result = process_output(text, "docker build .", exit_code=1, min_reduction=0.0)
    assert result.processor == "docker-build"
    assert "failed to solve build graph" in result.text
    assert result.text.count("compiling layer") < 5


def test_cargo_test_drops_passing_tests_but_preserves_failure():
    """Cargo test compression should summarize passes and keep failing evidence."""
    text = (
        "\n".join(f"test passing_{index} ... ok" for index in range(120))
        + "\ntest auth::refresh ... FAILED\n"
        + "failures:\n    auth::refresh\n"
        + "test result: FAILED. 120 passed; 1 failed\n"
    )
    result = process_output(text, "cargo test", exit_code=101, min_reduction=0.0)
    assert result.processor == "cargo-test"
    assert "auth::refresh ... FAILED" in result.text
    assert "test result: FAILED" in result.text
    assert result.text.count("... ok") < 5
