#!/usr/bin/env python3
"""Clone/fetch repositories required by a frozen Token Saver experiment suite."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def _run(command: list[str], *, cwd: Path | None = None) -> None:
    proc = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode:
        raise SystemExit(
            f"command failed ({proc.returncode}): {' '.join(command)}\n"
            + proc.stderr[-4000:]
        )


def _has_commit(repo: Path, revision: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{revision}^{{commit}}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite")
    parser.add_argument(
        "--task", action="append", dest="tasks",
        help="prepare only this task id; repeat for multiple tasks",
    )
    args = parser.parse_args()

    suite_path = Path(args.suite).resolve()
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    repositories = suite["repositories"]
    tasks = suite["tasks"]
    if args.tasks:
        wanted = set(args.tasks)
        known = {str(task["id"]) for task in tasks}
        unknown = sorted(wanted - known)
        if unknown:
            raise SystemExit("unknown task(s): " + ", ".join(unknown))
        tasks = [task for task in tasks if str(task["id"]) in wanted]
    base = suite_path.parent

    selected_repo_ids = {str(task["repository"]) for task in tasks}
    revisions: dict[str, set[str]] = {repo_id: set() for repo_id in selected_repo_ids}
    for task in tasks:
        revisions[task["repository"]].add(task["revision"])

    for repo_id in sorted(selected_repo_ids):
        definition = repositories[repo_id]
        path = (base / definition["path"]).resolve()
        url = definition.get("url")
        if not isinstance(url, str) or not url:
            raise SystemExit(f"{repo_id}: repository url is required")

        if not (path / ".git").is_dir():
            path.parent.mkdir(parents=True, exist_ok=True)
            print(f"clone {repo_id}: {url} -> {path}")
            _run([
                "git", "clone", "--filter=blob:none", "--no-checkout",
                url, str(path),
            ])
        else:
            print(f"reuse {repo_id}: {path}")

        for revision in sorted(revisions[repo_id]):
            if _has_commit(path, revision):
                continue
            print(f"fetch {repo_id}@{revision[:12]}")
            _run([
                "git", "-C", str(path), "fetch", "--filter=blob:none",
                "origin", revision,
            ])
            if not _has_commit(path, revision):
                raise SystemExit(f"{repo_id}: revision unavailable after fetch: {revision}")

    print(
        f"ready: {len(repositories)} repositories, "
        f"{sum(len(v) for v in revisions.values())} pinned revisions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
