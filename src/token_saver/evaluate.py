"""Ground-truth evaluation for context selection quality."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .pack import build_context_pack
from .repo_index import RepositoryIndex, build_index


def _recall(expected: set[str], actual: set[str]) -> float:
    return len(expected & actual) / len(expected) if expected else 1.0


def _git_revision(root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and value else None


def _repository_specs(payload: dict, manifest: Path) -> dict[str, tuple[Path, str | None]]:
    raw = payload.get("repositories", {})
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("'repositories' must be an object mapping names to paths/specs")
    specs: dict[str, tuple[Path, str | None]] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError("repository aliases must be non-empty strings")
        if isinstance(value, str):
            raw_path, revision = value, None
        elif isinstance(value, dict) and isinstance(value.get("path"), str):
            raw_path = value["path"]
            revision = value.get("revision")
            if revision is not None and not isinstance(revision, str):
                raise ValueError(f"repository {name!r} revision must be a string")
        else:
            raise ValueError(
                f"repository {name!r} must be a path string or {{path, revision}} object"
            )
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (manifest.parent / path).resolve()
        else:
            path = path.resolve()
        specs[name] = (path, revision)
    return specs


def _validate_holdout_protocol(payload: dict) -> None:
    protocol = payload.get("protocol")
    if not isinstance(protocol, dict):
        raise ValueError("holdout evaluation requires a 'protocol' object")
    required = ("ground_truth_frozen", "development_excluded")
    missing = [key for key in required if protocol.get(key) is not True]
    if missing:
        raise ValueError(
            "holdout protocol requires true flags: " + ", ".join(missing)
        )


def _summary(items: list[dict]) -> dict:
    return {
        "task_count": len(items),
        "mean_file_recall": sum(item["file_recall"] for item in items) / len(items),
        "mean_symbol_recall": sum(item["symbol_recall"] for item in items) / len(items),
        "mean_token_reduction": sum(item["token_reduction"] for item in items) / len(items),
    }


def evaluate_manifest(
    root: Path,
    manifest: Path,
    max_tokens: int = 6000,
    *,
    require_holdout: bool = False,
) -> dict:
    """Evaluate task-grounded context retrieval, optionally across repositories.

    Backward-compatible manifests use only ``tasks`` and the supplied ``root``.
    Multi-repository manifests may add a top-level ``repositories`` mapping and
    set each task's ``repository`` alias. Repository specs may pin a git
    ``revision``. ``require_holdout`` additionally requires protocol flags that
    attest ground truth was frozen and the repositories/tasks were excluded from
    Token Saver development/tuning.
    """
    root = root.resolve()
    manifest = manifest.resolve()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("manifest must contain a non-empty 'tasks' list")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if require_holdout:
        _validate_holdout_protocol(payload)

    specs = _repository_specs(payload, manifest)
    indexes: dict[Path, RepositoryIndex] = {}
    source_totals: dict[Path, int] = {}
    revisions: dict[Path, str | None] = {}

    def get_repo(alias: str | None) -> tuple[str, Path, str | None]:
        if alias is None:
            return "default", root, None
        if alias not in specs:
            raise ValueError(f"task references unknown repository alias: {alias}")
        path, expected_revision = specs[alias]
        return alias, path, expected_revision

    results = []
    by_repository: dict[str, list[dict]] = {}
    for position, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            raise ValueError(f"task {position} must be an object")
        alias_value = task.get("repository")
        if alias_value is not None and not isinstance(alias_value, str):
            raise ValueError(f"task {position} repository must be a string alias")
        repo_name, repo_root, expected_revision = get_repo(alias_value)
        if not repo_root.is_dir():
            raise ValueError(f"repository path does not exist: {repo_root}")

        if repo_root not in indexes:
            actual_revision = _git_revision(repo_root)
            revisions[repo_root] = actual_revision
            if expected_revision and actual_revision != expected_revision:
                raise ValueError(
                    f"repository {repo_name!r} revision mismatch: "
                    f"expected {expected_revision}, got {actual_revision or 'not-a-git-repository'}"
                )
            index = build_index(repo_root)
            indexes[repo_root] = index
            source_totals[repo_root] = max(
                1, sum(max(1, record.size // 4) for record in index.records.values())
            )
        index = indexes[repo_root]

        query = str(task.get("query", ""))
        expected_files = set(task.get("files", []))
        expected_symbols = set(task.get("symbols", []))
        pack = build_context_pack(
            repo_root, query, max_tokens=max_tokens, changed_boost=False,
            feedback_boost=False, index=index,
        )
        actual_symbols = {
            value.split(":", 1)[1].split("@", 1)[0]
            for value in pack.selected_symbols
        }
        item = {
            "id": task.get("id", position),
            "repository": repo_name,
            "revision": revisions[repo_root],
            "file_recall": _recall(expected_files, set(pack.selected_files)),
            "symbol_recall": _recall(expected_symbols, actual_symbols),
            "tokens": pack.estimated_tokens,
            "token_reduction": 1.0 - min(
                1.0, pack.estimated_tokens / source_totals[repo_root]
            ),
        }
        results.append(item)
        by_repository.setdefault(repo_name, []).append(item)

    return {
        "tasks": results,
        "repositories": {
            name: _summary(items) for name, items in sorted(by_repository.items())
        },
        "summary": _summary(results),
        "holdout_protocol_enforced": require_holdout,
    }
