"""Capture provenance-backed CLI outputs from disposable local fixtures.

The script intentionally records raw stdout/stderr before any ACCO
processing. Captures are suitable for freezing as an untouched evaluation
corpus; missing optional tools are recorded as skips rather than synthesized.
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
    """Run one controlled shell command and capture combined textual output."""
    return subprocess.run(
        ["bash", "-lc", command],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
        env={**os.environ, "NO_COLOR": "1", "TERM": "dumb"},
    )


def _tool_version(tool: str, cwd: Path) -> str | None:
    """Return a bounded version string for an installed executable."""
    if shutil.which(tool) is None:
        return None
    candidates = {
        "git": "git --version",
        "python": "python --version",
        "pytest": "pytest --version",
        "ruff": "ruff --version",
        "mypy": "mypy --version",
        "pylint": "pylint --version",
        "node": "node --version",
        "npm": "npm --version",
        "tsc": "tsc --version",
        "eslint": "eslint --version",
        "cargo": "cargo --version",
        "go": "go version",
        "dotnet": "dotnet --version",
        "mvn": "mvn --version",
        "gradle": "gradle --version",
        "docker": "docker --version",
        "jq": "jq --version",
        "terraform": "terraform version",
        "helm": "helm version --short",
        "kubectl": "kubectl version --client=true",
        "pulumi": "pulumi version",
    }
    result = _run(candidates.get(tool, f"{tool} --version"), cwd, timeout=30)
    first = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return first[0][:240] if first else None


def _write(path: Path, text: str) -> None:
    """Write UTF-8 fixture content, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _prepare_workspace(root: Path) -> dict[str, Path]:
    """Create disposable fixture repositories and projects."""
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    git_repo = root / "git-repo"
    git_repo.mkdir()
    _run("git init -q && git config user.email corpus@example.com && git config user.name Corpus", git_repo)
    _write(git_repo / "app.txt", "alpha\nbeta\ngamma\n")
    _run("git add app.txt && git commit -qm 'initial capture fixture'", git_repo)
    _write(git_repo / "app.txt", "alpha\nbeta changed\ngamma\n")
    _write(git_repo / "untracked.txt", "new\n")

    py = root / "python"
    py.mkdir()
    _write(
        py / "test_sample.py",
        "def test_refresh():\n    assert 401 == 200, 'expected 200, got 401'\n",
    )
    _write(py / "lint_sample.py", "def f():\n    return missing_name\n")
    _write(
        py / "type_sample.py",
        "def value() -> int:\n    return 'wrong'\n",
    )

    js = root / "javascript"
    js.mkdir()
    _write(
        js / "package.json",
        json.dumps(
            {
                "name": "cli-corpus-fixture",
                "version": "1.0.0",
                "scripts": {"build": "node -e \"throw new Error('build fixture failure')\""},
            },
            indent=2,
        )
        + "\n",
    )
    _write(js / "type.ts", "const count: number = 'wrong';\n")
    _write(js / "lint.js", "const unused = 1;\nconsole.log(missingName);\n")
    _write(
        js / "eslint.config.mjs",
        "export default [{ rules: { 'no-undef': 'error', 'no-unused-vars': 'warn' } }];\n",
    )

    rust = root / "rust"
    (rust / "src").mkdir(parents=True)
    _write(
        rust / "Cargo.toml",
        "[package]\nname='cli_corpus_fixture'\nversion='0.1.0'\nedition='2021'\n",
    )
    _write(
        rust / "src" / "lib.rs",
        "pub fn broken() -> i32 { let s = String::from(\"x\"); drop(s); s.len() as i32 }\n"
        "#[cfg(test)] mod tests { #[test] fn refresh() { assert_eq!(401, 200); } }\n",
    )

    rust_test = root / "rust-test"
    (rust_test / "src").mkdir(parents=True)
    _write(
        rust_test / "Cargo.toml",
        "[package]\nname='cli_corpus_test_fixture'\nversion='0.1.0'\nedition='2021'\n",
    )
    _write(
        rust_test / "src" / "lib.rs",
        "pub fn answer() -> i32 { 42 }\n"
        "#[cfg(test)] mod tests { #[test] fn refresh() { assert_eq!(401, 200); } }\n",
    )

    go = root / "go"
    go.mkdir()
    _write(go / "go.mod", "module example.com/corpus\n\ngo 1.22\n")
    _write(go / "main.go", "package main\nfunc main(){ println(missingSymbol) }\n")
    _write(
        go / "sample_test.go",
        "package main\nimport \"testing\"\nfunc TestRefresh(t *testing.T){ t.Fatalf(\"expected 200, got 401\") }\n",
    )

    docker = root / "docker"
    docker.mkdir()
    _write(
        docker / "Dockerfile",
        "FROM alpine:3.20\nRUN echo build-step\nRUN false\n",
    )
    _write(
        docker / "compose.yaml",
        "services:\n  hello:\n    image: alpine:3.20\n    command: [\"sh\", \"-c\", \"echo compose-ready\"]\n",
    )

    tf = root / "terraform"
    tf.mkdir()
    _write(
        tf / "main.tf",
        'terraform { required_version = ">= 1.0" }\n'
        'resource "terraform_data" "example" { input = "captured" }\n',
    )

    helm = root / "helm"
    (helm / "templates").mkdir(parents=True)
    _write(helm / "Chart.yaml", "apiVersion: v2\nname: capture\nversion: 0.1.0\n")
    _write(
        helm / "templates" / "configmap.yaml",
        "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: capture\ndata:\n  value: real-output\n",
    )

    return {
        "root": root,
        "git": git_repo,
        "python": py,
        "javascript": js,
        "rust": rust,
        "rust_test": rust_test,
        "go": go,
        "docker": docker,
        "terraform": tf,
        "helm": helm,
    }


def capture(out_dir: Path, workspace: Path) -> dict:
    """Execute available real CLIs and return provenance metadata."""
    paths = _prepare_workspace(workspace)
    out_dir.mkdir(parents=True, exist_ok=True)
    captures_dir = out_dir / "captures"
    captures_dir.mkdir()

    specs = [
        ("git-status", "git", "git status --untracked-files=all", "git"),
        ("git-diff", "git", "git diff", "git"),
        ("git-log", "git", "git log --decorate --stat -3", "git"),
        ("git-show", "git", "git show --stat --oneline HEAD", "git"),
        ("git-branch", "git", "git branch -avv", "git"),
        ("git-remote-failure", "git", "git push origin main", "git"),
        ("pytest-failure", "pytest", "pytest -q", "python"),
        ("ruff-failure", "ruff", "ruff check lint_sample.py", "python"),
        ("mypy-failure", "mypy", "mypy type_sample.py", "python"),
        ("pylint-failure", "pylint", "pylint lint_sample.py --score=no", "python"),
        ("npm-install", "npm", "npm install --ignore-scripts --no-audit --no-fund", "javascript"),
        ("npm-build-failure", "npm", "npm run build", "javascript"),
        ("tsc-failure", "tsc", "tsc --noEmit --pretty false type.ts", "javascript"),
        ("eslint-failure", "eslint", "eslint lint.js", "javascript"),
        ("cargo-build-failure", "cargo", "cargo build", "rust"),
        ("cargo-clippy-failure", "cargo", "cargo clippy", "rust"),
        ("cargo-test-failure", "cargo", "cargo test", "rust_test"),
        ("go-build-failure", "go", "go build ./...", "go"),
        ("go-test-failure", "go", "go test ./...", "go"),
        ("dotnet-test", "dotnet", "dotnet test --nologo", "root"),
        ("maven-version", "mvn", "mvn --version", "root"),
        ("gradle-version", "gradle", "gradle --version", "root"),
        ("docker-ps", "docker", "docker ps -a", "docker"),
        ("docker-build-failure", "docker", "docker build --progress=plain .", "docker"),
        ("docker-compose-config", "docker", "docker compose config", "docker"),
        ("docker-inspect-failure", "docker", "docker inspect acco-missing-container", "docker"),
        ("jq-query", "jq", "printf '%s\\n' '{\"items\":[1,2,3]}' | jq '.items[]'", "root"),
        ("terraform-plan", "terraform", "terraform init -backend=false -input=false >/dev/null && terraform plan -no-color -input=false", "terraform"),
        ("helm-template", "helm", "helm template capture .", "helm"),
        ("kubectl-client", "kubectl", "kubectl version --client=true", "root"),
        ("pulumi-version", "pulumi", "pulumi version", "root"),
    ]

    versions: dict[str, str | None] = {}
    records: list[dict] = []
    skipped: list[dict] = []
    for case_id, tool, command, cwd_key in specs:
        tool_path = shutil.which(tool)
        if tool_path is None:
            skipped.append({"id": case_id, "tool": tool, "reason": "executable-not-found"})
            continue
        if tool not in versions:
            versions[tool] = _tool_version(tool, paths["root"])
        cwd = paths[cwd_key]
        try:
            result = _run(command, cwd)
            output = result.stdout
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + "\n[ACCO_CAPTURE_TIMEOUT]\n"
            result = subprocess.CompletedProcess(command, 124, output)
        capture_path = captures_dir / f"{case_id}.txt"
        capture_path.write_text(output, encoding="utf-8")
        records.append(
            {
                "id": case_id,
                "tool": tool,
                "tool_path": tool_path,
                "tool_version": versions[tool],
                "command": command,
                "cwd_fixture": cwd_key,
                "exit_code": result.returncode,
                "output_path": str(capture_path.relative_to(out_dir)),
                "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
                "output_bytes": len(output.encode()),
                "output_lines": len(output.splitlines()),
            }
        )

    canonical = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    manifest = {
        "protocol": {
            "kind": "provenance-backed-cli-output-corpus",
            "captured": True,
            "untuned_before_capture": True,
            "capture_definition_sha256": hashlib.sha256(canonical).hexdigest(),
        },
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "github_sha": os.getenv("GITHUB_SHA"),
            "github_run_id": os.getenv("GITHUB_RUN_ID"),
            "github_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
            "runner_os": os.getenv("RUNNER_OS"),
            "runner_arch": os.getenv("RUNNER_ARCH"),
            "runner_name": os.getenv("RUNNER_NAME"),
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
    """Capture the corpus and print a content-free summary for CI logs."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="cli-corpus-capture")
    parser.add_argument("--workspace", default=".tmp-cli-corpus-workspace")
    parser.add_argument("--min-captures", type=int, default=20)
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
