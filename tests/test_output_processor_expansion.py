"""Regression coverage for the expanded CLI-output processor inventory."""

import pytest

from acco.output import DEFAULT_REGISTRY
from acco.output_processors import explain_processor, process_output


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


def test_default_registry_contains_exactly_44_unique_processors():
    """The expanded built-in inventory should contain forty-four unique processors."""
    names = [processor.name for processor in DEFAULT_REGISTRY.processors]
    assert len(names) == 44
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



def test_git_log_compacts_short_verbose_history():
    """Short verbose logs should still lose author/date/stat boilerplate."""
    text = (
        "commit 67b2c0508fc99b2acf977cb077ca9fcd0b008de9 (HEAD -> master)\n"
        "Author: Corpus <corpus@example.com>\n"
        "Date:   Mon Sep 21 08:42:22 2026 +0000\n"
        "\n"
        "    initial capture fixture\n"
        "\n"
        " app.txt | 3 +++\n"
        " 1 file changed, 3 insertions(+)\n"
    )
    result = process_output(text, "git log --decorate --stat -3", min_reduction=0.0)
    assert result.processor == "git-log"
    assert result.compressed is True
    assert "67b2c050" in result.text
    assert "initial capture fixture" in result.text
    assert "[+3]" in result.text
    assert "Author:" not in result.text
    assert "Date:" not in result.text


def test_git_status_drops_hints_and_keeps_staging_semantics():
    """Status compression should retain branch and porcelain-like path state."""
    text = (
        "On branch feature/status\n"
        "Changes to be committed:\n"
        '  (use "git restore --staged <file>..." to unstage)\n'
        "        modified:   staged.py\n"
        "\n"
        "Changes not staged for commit:\n"
        '  (use "git add <file>..." to update what will be committed)\n'
        "        deleted:    removed.py\n"
        "\n"
        "Untracked files:\n"
        '  (use "git add <file>..." to include in what will be committed)\n'
        "        fresh.py\n"
    )
    result = process_output(text, "git status", min_reduction=0.0)
    assert result.processor == "git-status"
    assert result.compressed is True
    assert "On branch feature/status" in result.text
    assert "S modified: staged.py" in result.text
    assert "U deleted: removed.py" in result.text
    assert "? fresh.py" in result.text
    assert "(use " not in result.text


def test_git_diff_small_patch_avoids_wrapper_and_context_tax():
    """Small patches should retain exact edits without redundant headers/context."""
    text = (
        "diff --git a/app.txt b/app.txt\n"
        "index 85c3040..86ceddb 100644\n"
        "--- a/app.txt\n"
        "+++ b/app.txt\n"
        "@@ -1,3 +1,3 @@\n"
        " alpha\n"
        "-beta\n"
        "+beta changed\n"
        " gamma\n"
    )
    result = process_output(text, "git diff", min_reduction=0.0)
    assert result.processor == "git-diff"
    assert result.compressed is True
    assert "diff --git a/app.txt b/app.txt" in result.text
    assert "@@ -1,3 +1,3 @@" in result.text
    assert "-beta" in result.text
    assert "+beta changed" in result.text
    assert "index 85c3040" not in result.text
    assert " alpha" not in result.text
    assert "[filtered" not in result.text


def test_go_build_small_failure_drops_single_package_header():
    """A single-package Go build error should reduce to the exact diagnostic."""
    text = (
        "# example.com/corpus\n"
        "./main.go:2:22: undefined: missingSymbol\n"
    )
    result = process_output(text, "go build ./...", exit_code=1, min_reduction=0.0)
    assert result.processor == "go-build"
    assert result.compressed is True
    assert result.text == "./main.go:2:22: undefined: missingSymbol\n"


def test_go_test_compile_failure_keeps_location_and_package_failure():
    """Go test compile failures should drop redundant package/bare FAIL lines."""
    text = (
        "# example.com/corpus [example.com/corpus.test]\n"
        "./main.go:2:22: undefined: missingSymbol\n"
        "FAIL\texample.com/corpus [build failed]\n"
        "FAIL\n"
    )
    result = process_output(text, "go test ./...", exit_code=1, min_reduction=0.0)
    assert result.processor == "go-test"
    assert result.compressed is True
    assert "./main.go:2:22: undefined: missingSymbol" in result.text
    assert "FAIL\texample.com/corpus [build failed]" in result.text
    assert "# example.com/corpus" not in result.text
    assert result.text.splitlines()[-1] != "FAIL"


def test_go_test_runtime_failure_preserves_test_and_location():
    """Runtime Go test failures should preserve failing test identity and message."""
    text = (
        "=== RUN   TestRefresh\n"
        "--- FAIL: TestRefresh (0.00s)\n"
        "    sample_test.go:8: expected 200, got 401\n"
        "FAIL\n"
        "FAIL\texample.com/corpus/auth\t0.003s\n"
    )
    result = process_output(text, "go test ./...", exit_code=1, min_reduction=0.0)
    assert result.processor == "go-test"
    assert result.compressed is True
    assert "--- FAIL: TestRefresh (0.00s)" in result.text
    assert "sample_test.go:8: expected 200, got 401" in result.text
    assert "FAIL\texample.com/corpus/auth\t0.003s" in result.text



def test_git_log_stat_compacts_each_commit_without_dropping_counts():
    """Verbose stat logs should keep subjects and compact per-commit change totals."""
    text = (
        "commit aaaaaaaa11111111111111111111111111111111 (HEAD -> feature/v3, main)\n"
        "Author: Example <example@example.com>\n"
        "Date:   Mon Sep 7 10:00:00 2026 +0000\n\n"
        "    tune parser\n\n"
        " src/a.py | 3 ++-\n"
        " 1 file changed, 2 insertions(+), 1 deletion(-)\n\n"
        "commit bbbbbbbb22222222222222222222222222222222\n"
        "Author: Example <example@example.com>\n"
        "Date:   Sun Sep 6 10:00:00 2026 +0000\n\n"
        "    add fixtures\n\n"
        " tests/a.py | 4 ++++\n"
        " tests/b.py | 2 ++\n"
        " 2 files changed, 6 insertions(+)\n"
    )
    result = process_output(
        text,
        "git log --decorate --stat -2",
        min_reduction=0.0,
    )
    assert result.processor == "git-log"
    assert result.compressed is True
    assert "aaaaaaaa [HEAD>feature/v3,main] tune parser [+2 -1]" in result.text
    assert "bbbbbbbb add fixtures [2f +6]" in result.text
    assert "Author:" not in result.text
    assert "src/a.py |" not in result.text


def test_git_log_without_stat_does_not_invent_change_totals():
    """Log compression should only emit compact stats when the command requested them."""
    text = (
        "commit cccccccc33333333333333333333333333333333\n"
        "Author: Example <example@example.com>\n"
        "Date:   Tue Sep 8 10:00:00 2026 +0000\n\n"
        "    plain subject\n\n"
        " src/a.py | 1 +\n"
        " 1 file changed, 1 insertion(+)\n"
    )
    result = process_output(text, "git log -1", min_reduction=0.0)
    assert result.processor == "git-log"
    assert result.compressed is True
    assert result.text == "cccccccc plain subject\n"


def test_git_status_short_branch_routes_to_status_not_branch():
    """The --branch option on git status must not be mistaken for git branch."""
    text = (
        "## feature/v3...origin/feature/v3 [ahead 2]\n"
        " M src/app.py\n"
        "A  src/new.py\n"
        "?? notes/\n"
    )
    info = explain_processor("git status --short --branch", exit_code=0)
    assert info["processor"] == "git-status"
    result = process_output(
        text,
        "git status --short --branch",
        exit_code=0,
        min_reduction=0.0,
    )
    assert result.processor == "git-status"
    assert "## feature/v3...origin/feature/v3 [ahead 2]" in result.text
    assert " M src/app.py" in result.text
    assert "A  src/new.py" in result.text
    assert "?? notes/" in result.text


def test_git_status_long_uses_compact_state_prefixes():
    """Long status keeps exact state wording with one-character stage prefixes."""
    text = (
        "On branch feature/v3\n"
        "Changes to be committed:\n"
        "        renamed:    src/old.py -> src/new.py\n"
        "        modified:   src/staged.py\n"
        "Changes not staged for commit:\n"
        "        deleted:    docs/old.md\n"
        "        modified:   src/live.py\n"
        "Untracked files:\n"
        "        notes/todo.txt\n"
    )
    result = process_output(text, "git status", min_reduction=0.0)
    assert result.processor == "git-status"
    assert result.compressed is True
    assert "S renamed: src/old.py -> src/new.py" in result.text
    assert "S modified: src/staged.py" in result.text
    assert "U deleted: docs/old.md" in result.text
    assert "U modified: src/live.py" in result.text
    assert "? notes/todo.txt" in result.text
