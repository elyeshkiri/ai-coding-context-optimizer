"""Capture untouched real CLI outputs for fresh corpus v2.

Corpus v2 deliberately uses different Git history/worktree shapes and Go
failure modes from v1. It performs no Token Saver evaluation.
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
    """Return a bounded version line for an installed command."""
    if shutil.which(tool) is None:
        return None
    commands = {
        "git": "git --version",
        "python": "python --version",
        "pytest": "pytest --version",
        "ruff": "ruff --version",
        "mypy": "mypy --version",
        "node": "node --version",
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
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[0][:240] if lines else None


def _git_commit(repo: Path, message: str, timestamp: str) -> None:
    """Create a deterministic Git fixture commit."""
    command = (
        "git add -A && "
        f"GIT_AUTHOR_DATE='{timestamp}' GIT_COMMITTER_DATE='{timestamp}' "
        f"git commit -qm {json.dumps(message)}"
    )
    result = _run(command, repo)
    if result.returncode != 0:
        raise RuntimeError(result.stdout)


def _prepare_git(root: Path) -> Path:
    """Create a multi-commit repository with staged, unstaged, and untracked state."""
    repo = root / "git-v2"
    repo.mkdir()
    init = _run(
        "git init -q -b main && "
        "git config user.email corpus-v2@example.com && "
        "git config user.name 'Corpus V2'",
        repo,
    )
    if init.returncode != 0:
        raise RuntimeError(init.stdout)

    _write(repo / "src" / "alpha.txt", "alpha-1\nalpha-2\nalpha-3\n")
    _write(repo / "src" / "beta.txt", "beta-1\nbeta-2\n")
    _write(repo / "docs" / "old.md", "legacy docs\n")
    _git_commit(repo, "seed project", "2026-09-01T10:00:00Z")

    _write(repo / "src" / "alpha.txt", "alpha-1\nalpha-two\nalpha-3\n")
    _git_commit(repo, "adjust alpha behavior", "2026-09-02T10:00:00Z")

    _write(repo / "src" / "gamma.txt", "gamma\n")
    _git_commit(repo, "add gamma module", "2026-09-03T10:00:00Z")

    _write(repo / "docs" / "guide.md", "guide v1\n")
    _git_commit(repo, "document workflow", "2026-09-04T10:00:00Z")

    _write(repo / "src" / "beta.txt", "beta-1\nbeta-2\nbeta-3\n")
    _git_commit(repo, "extend beta", "2026-09-05T10:00:00Z")

    _write(repo / "src" / "delta.txt", "delta\n")
    _git_commit(repo, "add delta", "2026-09-06T10:00:00Z")

    branch = _run("git switch -qc feature/v2", repo)
    if branch.returncode != 0:
        raise RuntimeError(branch.stdout)

    # Staged rename + staged edit.
    renamed = _run("git mv src/beta.txt src/beta-renamed.txt", repo)
    if renamed.returncode != 0:
        raise RuntimeError(renamed.stdout)
    _write(repo / "src" / "gamma.txt", "gamma\ngamma staged\n")
    staged = _run("git add src/gamma.txt src/beta-renamed.txt", repo)
    if staged.returncode != 0:
        raise RuntimeError(staged.stdout)

    # Unstaged multi-hunk edit + deletion.
    _write(
        repo / "src" / "alpha.txt",
        "alpha-1 changed\nalpha-two\nalpha-3\nalpha-4 added\n",
    )
    (repo / "docs" / "old.md").unlink()
    _write(repo / "notes" / "todo.txt", "fresh v2 note\n")
    return repo


def _prepare_go(root: Path) -> dict[str, Path]:
    """Create independent Go build and test fixtures with fresh failure modes."""
    build = root / "go-build-v2"
    (build / "cmd" / "broken").mkdir(parents=True)
    _write(build / "go.mod", "module example.com/v2build\n\ngo 1.22\n")
    _write(
        build / "cmd" / "broken" / "main.go",
        "package main\n"
        "func wantsInt(v int) {}\n"
        "func main() { wantsInt(\"wrong\") }\n",
    )

    tests = root / "go-test-v2"
    (tests / "auth").mkdir(parents=True)
    (tests / "healthy").mkdir(parents=True)
    _write(tests / "go.mod", "module example.com/v2tests\n\ngo 1.22\n")
    _write(tests / "auth" / "auth.go", "package auth\nfunc Status() int { return 401 }\n")
    _write(
        tests / "auth" / "auth_test.go",
        "package auth\n"
        'import "testing"\n'
        "func TestRefresh(t *testing.T) {\n"
        ' t.Run("expired", func(t *testing.T) {\n'
        '  if got := Status(); got != 200 { t.Fatalf("status=%d want=200", got) }\n'
        " })\n"
        "}\n",
    )
    _write(tests / "healthy" / "healthy.go", "package healthy\nfunc Value() int { return 7 }\n")
    _write(
        tests / "healthy" / "healthy_test.go",
        'package healthy\nimport "testing"\n'
        "func TestValue(t *testing.T) { if Value() != 7 { t.Fatal(\"bad\") } }\n",
    )
    return {"go_build": build, "go_test": tests}


def _prepare_controls(root: Path) -> dict[str, Path]:
    """Create unrelated control fixtures for regression detection."""
    py = root / "python-v2"
    py.mkdir()
    _write(
        py / "test_multi.py",
        "def test_alpha():\n    assert 3 == 4, 'alpha mismatch'\n\n"
        "def test_beta():\n    assert 'left' == 'right'\n",
    )
    _write(
        py / "lint_multi.py",
        "def first():\n    return unknown_one\n\n"
        "def second():\n    return unknown_two\n",
    )
    _write(py / "types.py", "def total() -> int:\n    return None\n")

    js = root / "javascript-v2"
    js.mkdir()
    _write(
        js / "package.json",
        json.dumps(
            {
                "name": "cli-corpus-v2",
                "version": "1.0.0",
                "scripts": {
                    "build": "node -e \"console.error('v2 build failure'); process.exit(2)\""
                },
            },
            indent=2,
        )
        + "\n",
    )
    _write(
        js / "types.ts",
        "const count: number = 'bad';\nconst enabled: boolean = 3;\n",
    )
    _write(js / "lint.js", "console.log(firstMissing);\nconsole.log(secondMissing);\n")
    _write(
        js / "eslint.config.mjs",
        "export default [{ languageOptions: { globals: {} }, "
        "rules: { 'no-undef': 'error' } }];\n",
    )

    rust = root / "rust-v2"
    (rust / "src").mkdir(parents=True)
    _write(
        rust / "Cargo.toml",
        "[package]\nname='cli_corpus_v2'\nversion='0.1.0'\nedition='2021'\n",
    )
    _write(
        rust / "src" / "lib.rs",
        "pub fn number() -> i32 { let value: i32 = \"wrong\"; value }\n"
        "#[cfg(test)] mod tests { #[test] fn value() { assert_eq!(2, 3); } }\n",
    )

    docker = root / "docker-v2"
    docker.mkdir()
    _write(
        docker / "Dockerfile",
        "FROM alpine:3.20\nRUN printf 'v2-layer\\n'\nRUN test -f /definitely-missing-v2\n",
    )

    helm = root / "helm-v2"
    (helm / "templates").mkdir(parents=True)
    _write(helm / "Chart.yaml", "apiVersion: v2\nname: capture-v2\nversion: 0.2.0\n")
    _write(
        helm / "templates" / "service.yaml",
        "apiVersion: v1\nkind: Service\nmetadata:\n  name: capture-v2\n"
        "spec:\n  selector:\n    app: capture-v2\n  ports:\n    - port: 8080\n",
    )
    return {
        "python": py,
        "javascript": js,
        "rust": rust,
        "docker": docker,
        "helm": helm,
    }


def capture(out_dir: Path, workspace: Path) -> dict:
    """Execute v2 commands and persist untouched stdout/stderr plus provenance."""
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    git = _prepare_git(workspace)
    go = _prepare_go(workspace)
    controls = _prepare_controls(workspace)
    paths = {"root": workspace, "git": git, **go, **controls}

    specs = [
        ("git-status-long-v2", "git", "git status --untracked-files=all", "git"),
        ("git-status-short-v2", "git", "git status --short --branch", "git"),
        ("git-diff-worktree-v2", "git", "git diff -- src docs", "git"),
        ("git-diff-cached-v2", "git", "git diff --cached --find-renames", "git"),
        ("git-log-stat-v2", "git", "git log --decorate --stat -6", "git"),
        ("git-log-oneline-v2", "git", "git log --oneline --decorate -8", "git"),
        ("git-show-v2", "git", "git show --stat --oneline HEAD~2", "git"),
        ("git-diff-stat-v2", "git", "git diff --stat HEAD~3..HEAD", "git"),
        ("go-build-type-v2", "go", "go build ./cmd/broken", "go_build"),
        ("go-build-all-v2", "go", "go build ./...", "go_build"),
        ("go-test-verbose-v2", "go", "go test -v ./auth", "go_test"),
        ("go-test-all-v2", "go", "go test ./...", "go_test"),
        ("go-test-success-v2", "go", "go test ./healthy", "go_test"),
        ("pytest-multi-v2", "pytest", "pytest -q", "python"),
        ("ruff-multi-v2", "ruff", "ruff check lint_multi.py", "python"),
        ("mypy-v2", "mypy", "mypy types.py", "python"),
        ("npm-install-v2", "npm", "npm install --ignore-scripts --no-audit --no-fund", "javascript"),
        ("npm-build-v2", "npm", "npm run build", "javascript"),
        ("tsc-multi-v2", "tsc", "tsc --noEmit --pretty false types.ts", "javascript"),
        ("eslint-multi-v2", "eslint", "eslint lint.js", "javascript"),
        ("cargo-check-v2", "cargo", "cargo check", "rust"),
        ("cargo-test-v2", "cargo", "cargo test", "rust"),
        ("docker-build-v2", "docker", "docker build --progress=plain .", "docker"),
        ("docker-ps-v2", "docker", "docker ps -a", "docker"),
        ("jq-v2", "jq", "printf '%s\\n' '{\"users\":[{\"id\":7},{\"id\":9}]}' | jq '.users[].id'", "root"),
        ("helm-template-v2", "helm", "helm template capture-v2 .", "helm"),
        ("kubectl-client-v2", "kubectl", "kubectl version --client=true", "root"),
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
            skipped.append({"id": case_id, "tool": tool, "reason": "executable-not-found"})
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
            output = stdout + stderr + "\n[TOKEN_SAVER_CAPTURE_TIMEOUT]\n"
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
            "kind": "provenance-backed-cli-output-corpus-v2-capture",
            "captured": True,
            "untuned_before_capture": True,
            "processor_lock_sha": "43ec1693e208b9d12502fac7a43bc70009c59740",
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
    """Capture fresh v2 evidence without evaluating either compressor."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="cli-corpus-v2-capture")
    parser.add_argument("--workspace", default=".tmp-cli-corpus-v2")
    parser.add_argument("--min-captures", type=int, default=22)
    args = parser.parse_args()
    manifest = capture(Path(args.out).resolve(), Path(args.workspace).resolve())
    print(json.dumps({"summary": manifest["summary"], "environment": manifest["environment"]}, indent=2))
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
