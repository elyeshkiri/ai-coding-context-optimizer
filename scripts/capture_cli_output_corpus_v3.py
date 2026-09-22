"""Capture untouched real CLI outputs for fresh corpus v3.

Corpus v3 is a post-v2 proof set for Git log/status tuning. It uses a new Git
history/worktree and different command variants, and intentionally performs no
ACCO or peer evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROCESSOR_LOCK_SHA = "18ebda5d623fc01ef2ea5cdf79054ecee7ba76e6"


def _run(command: str, cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    """Execute one controlled command with stable textual terminal settings."""
    return subprocess.run(
        ["bash", "-lc", command],
        cwd=cwd,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
        env={
            **os.environ,
            "NO_COLOR": "1",
            "TERM": "dumb",
            "TZ": "UTC",
            "LC_ALL": "C.UTF-8",
        },
    )


def _write(path: Path, text: str) -> None:
    """Write UTF-8 fixture content and create parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _version(tool: str, root: Path) -> str | None:
    """Return one bounded version line for an installed command."""
    if shutil.which(tool) is None:
        return None
    commands = {
        "git": "git --version",
        "pytest": "pytest --version",
        "ruff": "ruff --version",
        "mypy": "mypy --version",
        "npm": "npm --version",
        "tsc": "tsc --version",
        "eslint": "eslint --version",
        "cargo": "cargo --version",
        "go": "go version",
        "docker": "docker --version",
        "jq": "jq --version",
        "helm": "helm version --short",
        "kubectl": "kubectl version --client=true",
    }
    result = _run(commands.get(tool, f"{tool} --version"), root, timeout=30)
    lines = [line.strip() for line in (result.stdout + result.stderr).splitlines()]
    lines = [line for line in lines if line]
    return lines[0][:240] if lines else None


def _git_commit(repo: Path, message: str, timestamp: str) -> None:
    """Create one deterministic commit in the v3 Git fixture."""
    command = (
        "git add -A && "
        f"GIT_AUTHOR_DATE='{timestamp}' GIT_COMMITTER_DATE='{timestamp}' "
        f"git commit -qm {json.dumps(message)}"
    )
    result = _run(command, repo)
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)


def _prepare_git(root: Path) -> Path:
    """Create a fresh multi-commit repository and mixed worktree state."""
    repo = root / "git-v3"
    repo.mkdir()
    init = _run(
        "git init -q -b trunk && "
        "git config user.email corpus-v3@example.com && "
        "git config user.name 'Corpus V3'",
        repo,
    )
    if init.returncode != 0:
        raise RuntimeError(init.stdout + init.stderr)

    fixtures = [
        (
            "bootstrap service",
            {
                "src/api.txt": "route=/v1\nstatus=200\n",
                "src/cache.txt": "ttl=30\n",
                "docs/readme.md": "v3 fixture\n",
            },
        ),
        ("add worker queue", {"src/worker.txt": "queue=events\nretries=3\n"}),
        ("increase cache ttl", {"src/cache.txt": "ttl=45\n"}),
        ("document retries", {"docs/retries.md": "retries=3\nbackoff=linear\n"}),
        ("add metrics", {"src/metrics.txt": "requests=0\nerrors=0\n"}),
        (
            "revise api status",
            {"src/api.txt": "route=/v1\nstatus=201\nheader=x-v3\n"},
        ),
        ("add scheduler", {"src/scheduler.txt": "interval=15\n"}),
        (
            "expand worker policy",
            {"src/worker.txt": "queue=events\nretries=5\ntimeout=20\n"},
        ),
        ("add operations guide", {"docs/ops.md": "deploy\nobserve\nrollback\n"}),
    ]
    for index, (message, files) in enumerate(fixtures, start=1):
        for relative, content in files.items():
            _write(repo / relative, content)
        _git_commit(repo, message, f"2026-09-{index:02d}T11:00:00Z")

    switch = _run("git switch -qc feature/git-v3", repo)
    if switch.returncode != 0:
        raise RuntimeError(switch.stdout + switch.stderr)

    # Staged rename + staged new file.
    renamed = _run("git mv src/metrics.txt src/telemetry.txt", repo)
    if renamed.returncode != 0:
        raise RuntimeError(renamed.stdout + renamed.stderr)
    _write(repo / "src" / "feature_flag.txt", "git_v3=true\n")
    staged = _run("git add src/telemetry.txt src/feature_flag.txt", repo)
    if staged.returncode != 0:
        raise RuntimeError(staged.stdout + staged.stderr)

    # Unstaged edit + deletion + two untracked paths.
    _write(
        repo / "src" / "api.txt",
        "route=/v2\nstatus=202\nheader=x-v3\nmode=preview\n",
    )
    (repo / "docs" / "retries.md").unlink()
    _write(repo / "notes" / "review.txt", "review git log compaction\n")
    _write(repo / "notes" / "nested" / "todo.txt", "fresh proof only\n")
    return repo


def _prepare_go(root: Path) -> dict[str, Path]:
    """Create fresh Go build and runtime-test failures for control coverage."""
    build = root / "go-build-v3"
    (build / "cmd" / "app").mkdir(parents=True)
    _write(build / "go.mod", "module example.com/v3build\n\ngo 1.22\n")
    _write(
        build / "cmd" / "app" / "main.go",
        "package main\n"
        "func add(a int, b int) int { return a + b }\n"
        "func main() { _ = add(1) }\n",
    )

    tests = root / "go-test-v3"
    (tests / "session").mkdir(parents=True)
    _write(tests / "go.mod", "module example.com/v3tests\n\ngo 1.22\n")
    _write(
        tests / "session" / "session.go",
        "package session\nfunc Token() string { return \"expired\" }\n",
    )
    _write(
        tests / "session" / "session_test.go",
        "package session\n"
        'import "testing"\n'
        "func TestToken(t *testing.T) {\n"
        ' if got := Token(); got != "active" { t.Fatalf("token=%s want=active", got) }\n'
        "}\n",
    )
    return {"go_build": build, "go_test": tests}


def _prepare_controls(root: Path) -> dict[str, Path]:
    """Create unrelated fresh fixtures to detect broad regressions."""
    py = root / "python-v3"
    py.mkdir()
    _write(
        py / "test_state.py",
        "def test_state():\n"
        "    actual = {'status': 409, 'retry': 2}\n"
        "    assert actual == {'status': 200, 'retry': 1}\n",
    )
    _write(
        py / "lint_state.py",
        "def value():\n"
        "    return missing_state + missing_retry\n",
    )
    _write(py / "types_state.py", "def code() -> int:\n    return '409'\n")

    js = root / "javascript-v3"
    js.mkdir()
    _write(
        js / "package.json",
        json.dumps(
            {
                "name": "cli-corpus-v3",
                "version": "1.0.0",
                "scripts": {
                    "build": "node -e \"console.error('v3 compile stop'); process.exit(3)\""
                },
            },
            indent=2,
        )
        + "\n",
    )
    _write(
        js / "types.ts",
        "const retries: number = 'five';\nconst mode: 'safe' = 'fast';\n",
    )
    _write(js / "lint.js", "console.log(v3Missing);\n")
    _write(
        js / "eslint.config.mjs",
        "export default [{ languageOptions: { globals: {} }, "
        "rules: { 'no-undef': 'error' } }];\n",
    )

    rust = root / "rust-v3"
    (rust / "src").mkdir(parents=True)
    _write(
        rust / "Cargo.toml",
        "[package]\nname='cli_corpus_v3'\nversion='0.1.0'\nedition='2021'\n",
    )
    _write(
        rust / "src" / "lib.rs",
        "pub fn enabled() -> bool { let value: bool = 7; value }\n",
    )

    docker = root / "docker-v3"
    docker.mkdir()
    _write(
        docker / "Dockerfile",
        "FROM alpine:3.20\n"
        "RUN printf 'v3-build\\n'\n"
        "RUN test -d /missing-directory-v3\n",
    )

    helm = root / "helm-v3"
    (helm / "templates").mkdir(parents=True)
    _write(helm / "Chart.yaml", "apiVersion: v2\nname: capture-v3\nversion: 0.3.0\n")
    _write(
        helm / "templates" / "configmap.yaml",
        "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: capture-v3\n"
        "data:\n  mode: proof\n",
    )
    return {
        "python": py,
        "javascript": js,
        "rust": rust,
        "docker": docker,
        "helm": helm,
    }


def capture(out_dir: Path, workspace: Path) -> dict:
    """Execute fresh commands and persist untouched stdout/stderr plus provenance."""
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    git = _prepare_git(workspace)
    go = _prepare_go(workspace)
    controls = _prepare_controls(workspace)
    paths = {"root": workspace, "git": git, **go, **controls}

    specs = [
        ("git-status-long-v3", "git", "git status --untracked-files=all", "git"),
        (
            "git-status-short-v3",
            "git",
            "git status --short --branch --untracked-files=all",
            "git",
        ),
        (
            "git-status-porcelain-v1-v3",
            "git",
            "git status --porcelain=v1 --branch --untracked-files=all",
            "git",
        ),
        (
            "git-status-porcelain-v2-v3",
            "git",
            "git status --porcelain=v2 --branch --untracked-files=all",
            "git",
        ),
        ("git-log-stat-v3", "git", "git log --decorate --stat -8", "git"),
        (
            "git-log-stat-no-merges-v3",
            "git",
            "git log --decorate --stat --no-merges -6",
            "git",
        ),
        (
            "git-log-fuller-stat-v3",
            "git",
            "git log --format=fuller --stat -5",
            "git",
        ),
        (
            "git-log-reverse-stat-v3",
            "git",
            "git log --reverse --stat -6",
            "git",
        ),
        (
            "git-log-oneline-v3",
            "git",
            "git log --oneline --decorate -9",
            "git",
        ),
        (
            "git-log-graph-v3",
            "git",
            "git log --graph --oneline --decorate -9",
            "git",
        ),
        ("git-diff-worktree-v3", "git", "git diff -- src docs", "git"),
        ("git-diff-cached-v3", "git", "git diff --cached --find-renames", "git"),
        ("git-show-v3", "git", "git show --stat --oneline HEAD~3", "git"),
        ("git-branch-v3", "git", "git branch -avv", "git"),
        ("go-build-v3", "go", "go build ./...", "go_build"),
        ("go-test-v3", "go", "go test -v ./...", "go_test"),
        ("pytest-v3", "pytest", "pytest -q", "python"),
        ("ruff-v3", "ruff", "ruff check lint_state.py", "python"),
        ("mypy-v3", "mypy", "mypy types_state.py", "python"),
        (
            "npm-install-v3",
            "npm",
            "npm install --ignore-scripts --no-audit --no-fund",
            "javascript",
        ),
        ("npm-build-v3", "npm", "npm run build", "javascript"),
        ("tsc-v3", "tsc", "tsc --noEmit --pretty false types.ts", "javascript"),
        ("eslint-v3", "eslint", "eslint lint.js", "javascript"),
        ("cargo-check-v3", "cargo", "cargo check", "rust"),
        ("docker-build-v3", "docker", "docker build --progress=plain .", "docker"),
        ("docker-ps-v3", "docker", "docker ps -a", "docker"),
        (
            "jq-v3",
            "jq",
            "printf '%s\\n' '{\"states\":[409,202,200]}' | jq '.states[]'",
            "root",
        ),
        ("helm-template-v3", "helm", "helm template capture-v3 .", "helm"),
        ("kubectl-client-v3", "kubectl", "kubectl version --client=true", "root"),
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    captures_dir = out_dir / "captures"
    captures_dir.mkdir()
    versions: dict[str, str | None] = {}
    records: list[dict] = []
    skipped: list[dict] = []

    for case_id, tool, command, cwd_key in specs:
        executable = shutil.which(tool)
        if executable is None:
            skipped.append(
                {"id": case_id, "tool": tool, "reason": "executable-not-found"}
            )
            continue
        if tool not in versions:
            versions[tool] = _version(tool, workspace)
        try:
            result = _run(command, paths[cwd_key])
            output = result.stdout + result.stderr
            exit_code = result.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            output = stdout + stderr + "\n[ACCO_CAPTURE_TIMEOUT]\n"
            exit_code = 124

        capture_path = captures_dir / f"{case_id}.txt"
        capture_path.write_text(output, encoding="utf-8")
        encoded = output.encode()
        records.append(
            {
                "id": case_id,
                "tool": tool,
                "tool_path": executable,
                "tool_version": versions[tool],
                "command": command,
                "cwd_fixture": cwd_key,
                "exit_code": exit_code,
                "output_path": str(capture_path.relative_to(out_dir)),
                "output_sha256": hashlib.sha256(encoded).hexdigest(),
                "output_bytes": len(encoded),
                "output_lines": len(output.splitlines()),
            }
        )

    manifest = {
        "protocol": {
            "kind": "provenance-backed-cli-output-corpus-v3-capture",
            "captured": True,
            "untuned_before_capture": True,
            "processor_lock_sha": PROCESSOR_LOCK_SHA,
            "focus": "git-log-status",
        },
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "github_sha": os.getenv("GITHUB_SHA"),
            "github_run_id": os.getenv("GITHUB_RUN_ID"),
            "github_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
            "runner_os": os.getenv("RUNNER_OS"),
            "runner_arch": os.getenv("RUNNER_ARCH"),
            "image_os": os.getenv("ImageOS"),
            "image_version": os.getenv("ImageVersion"),
        },
        "summary": {
            "attempted": len(specs),
            "captured": len(records),
            "skipped": len(skipped),
            "raw_bytes": sum(item["output_bytes"] for item in records),
        },
        "captures": records,
        "skipped": skipped,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    """Capture fresh v3 evidence without evaluating either compressor."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="cli-corpus-v3-capture")
    parser.add_argument("--workspace", default=".tmp-cli-corpus-v3")
    parser.add_argument("--min-captures", type=int, default=25)
    args = parser.parse_args()
    manifest = capture(Path(args.out).resolve(), Path(args.workspace).resolve())
    print(
        json.dumps(
            {"summary": manifest["summary"], "environment": manifest["environment"]},
            indent=2,
        )
    )
    if manifest["summary"]["captured"] < args.min_captures:
        print(
            f"captured only {manifest['summary']['captured']} cases; "
            f"minimum is {args.min_captures}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
