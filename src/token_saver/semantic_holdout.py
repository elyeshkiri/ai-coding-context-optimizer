"""Frozen no-identifier-leakage evaluation for hybrid semantic retrieval.

This evaluator compares three retrieval arms on the same immutable natural-
language tasks:

* Token Saver's validated lexical/structural pipeline;
* the same pipeline with persistent chunk-level semantic retrieval enabled;
* a deliberately weak distinct-term-overlap baseline.

The query freeze is a separate committed artifact and is validated byte-
independently through a canonical SHA-256 before any ground-truth result is
accepted. Once a suite has been evaluated, it is burned for tuning.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .evaluate import _git_revision, _recall, _repository_specs
from .lexical import terms
from .pack import build_context_pack
from .repo_index import RepositoryIndex, build_index


def _canonical_sha256(value: object) -> str:
    """Return a stable SHA-256 over JSON-compatible evidence."""
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _query_freeze_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize the pre-ground-truth query evidence only."""
    repositories: dict[str, dict[str, str]] = {}
    raw_repositories = payload.get("repositories", {})
    if isinstance(raw_repositories, dict):
        for alias, spec in sorted(raw_repositories.items()):
            if not isinstance(alias, str) or not isinstance(spec, dict):
                continue
            revision = spec.get("revision")
            repository = spec.get("repository")
            if isinstance(revision, str) and isinstance(repository, str):
                repositories[alias] = {
                    "repository": repository,
                    "revision": revision,
                }

    tasks: list[dict[str, Any]] = []
    raw_tasks = payload.get("tasks", [])
    if isinstance(raw_tasks, list):
        for task in raw_tasks:
            if not isinstance(task, dict):
                continue
            source = task.get("source_issue")
            normalized_source = {}
            if isinstance(source, dict):
                normalized_source = {
                    "number": source.get("number"),
                    "url": source.get("url"),
                }
            tasks.append(
                {
                    "id": task.get("id"),
                    "repository": task.get("repository"),
                    "source_issue": normalized_source,
                    "query": str(task.get("query", "")),
                }
            )
    return {
        "suite_version": int(payload.get("suite_version", 1)),
        "repositories": repositories,
        "tasks": tasks,
    }


def query_freeze_hash(payload: dict[str, Any]) -> str:
    """Return the canonical hash of repository revisions and frozen queries."""
    return _canonical_sha256(_query_freeze_payload(payload))


def _ground_truth_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize semantic holdout evidence for its final immutable hash."""
    repositories: dict[str, dict[str, str | None]] = {}
    raw_repositories = payload.get("repositories", {})
    if isinstance(raw_repositories, dict):
        for alias, spec in sorted(raw_repositories.items()):
            if not isinstance(alias, str) or not isinstance(spec, dict):
                continue
            revision = spec.get("revision")
            repositories[alias] = {
                "revision": revision if isinstance(revision, str) else None,
            }

    tasks: list[dict[str, Any]] = []
    for task in payload.get("tasks", []):
        if not isinstance(task, dict):
            continue
        tasks.append(
            {
                "id": task.get("id"),
                "repository": task.get("repository"),
                "source_issue": task.get("source_issue"),
                "query": str(task.get("query", "")),
                "files": sorted(
                    str(value).replace("\\", "/")
                    for value in task.get("files", [])
                    if isinstance(value, str)
                ),
                "forbidden_identifiers": sorted(
                    str(value)
                    for value in task.get("forbidden_identifiers", [])
                    if isinstance(value, str)
                ),
                "eligible": bool(task.get("eligible", True)),
                "exclusion_reason": task.get("exclusion_reason"),
                "max_tokens": int(task.get("max_tokens", payload.get("max_tokens", 6000))),
                "max_files": int(task.get("max_files", payload.get("max_files", 12))),
            }
        )
    protocol = payload.get("protocol", {})
    return {
        "suite_version": int(payload.get("suite_version", 1)),
        "repositories": repositories,
        "tasks": tasks,
        "query_freeze_commit": protocol.get("query_freeze_commit"),
        "query_freeze_sha256": protocol.get("query_freeze_sha256"),
        "baseline": protocol.get("baseline"),
        "embedding_model": protocol.get("embedding_model"),
        "embedding_model_revision": protocol.get("embedding_model_revision"),
    }


def semantic_ground_truth_hash(payload: dict[str, Any]) -> str:
    """Return a stable SHA-256 for the final semantic holdout definition."""
    return _canonical_sha256(_ground_truth_payload(payload))


def _validate_query_freeze(
    manifest_payload: dict[str, Any],
    manifest_path: Path,
) -> str:
    """Prove final queries exactly match the earlier query-only freeze."""
    protocol = manifest_payload.get("protocol")
    if not isinstance(protocol, dict):
        raise ValueError("semantic holdout requires a protocol object")
    freeze_name = protocol.get("query_freeze_file")
    if not isinstance(freeze_name, str) or not freeze_name:
        raise ValueError("semantic holdout requires protocol.query_freeze_file")
    freeze_path = (manifest_path.parent / freeze_name).resolve()
    try:
        frozen = json.loads(freeze_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"unable to read query freeze: {freeze_path}") from exc

    actual_hash = query_freeze_hash(frozen)
    declared_hash = protocol.get("query_freeze_sha256")
    if declared_hash != actual_hash:
        raise ValueError(
            "query freeze hash mismatch; set protocol.query_freeze_sha256 to "
            f"{actual_hash}"
        )

    final_query_payload = _query_freeze_payload(manifest_payload)
    frozen_query_payload = _query_freeze_payload(frozen)
    if final_query_payload != frozen_query_payload:
        raise ValueError(
            "final semantic holdout queries/revisions differ from the "
            "pre-ground-truth query freeze"
        )
    commit = protocol.get("query_freeze_commit")
    if not isinstance(commit, str) or len(commit) != 40:
        raise ValueError("semantic holdout requires the 40-character query freeze commit")
    return actual_hash


def _validate_leakage(task: dict[str, Any]) -> list[str]:
    """Return declared answer identities leaked literally by one frozen query."""
    query = str(task.get("query", "")).casefold()
    leaked: list[str] = []
    for raw in task.get("forbidden_identifiers", []):
        if not isinstance(raw, str):
            continue
        value = raw.strip().casefold()
        if value and value in query:
            leaked.append(raw)
    return leaked


def validate_semantic_holdout(
    payload: dict[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    """Validate query sequence, leakage metadata, exclusions, and freeze hashes."""
    protocol = payload.get("protocol")
    if not isinstance(protocol, dict):
        raise ValueError("semantic holdout requires a protocol object")
    for flag in (
        "ground_truth_frozen",
        "development_excluded",
        "semantic_natural_language",
        "query_frozen_before_ground_truth",
        "no_identifier_leakage",
    ):
        if protocol.get(flag) is not True:
            raise ValueError(f"semantic holdout requires protocol.{flag}=true")
    frozen_at = protocol.get("frozen_at")
    if not isinstance(frozen_at, str) or not frozen_at.strip():
        raise ValueError("semantic holdout requires protocol.frozen_at")

    query_hash = _validate_query_freeze(payload, manifest_path)
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("semantic holdout requires a non-empty tasks list")

    eligible = 0
    excluded = 0
    for position, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            raise ValueError(f"semantic task {position} must be an object")
        files = task.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError(f"semantic task {task.get('id', position)!r} needs files")
        identifiers = task.get("forbidden_identifiers")
        if not isinstance(identifiers, list) or not identifiers:
            raise ValueError(
                f"semantic task {task.get('id', position)!r} needs forbidden_identifiers"
            )
        leaked = _validate_leakage(task)
        is_eligible = bool(task.get("eligible", True))
        if leaked and is_eligible:
            raise ValueError(
                f"semantic task {task.get('id', position)!r} leaks answer "
                f"identifiers: {', '.join(leaked)}"
            )
        if is_eligible:
            eligible += 1
        else:
            excluded += 1
            reason = task.get("exclusion_reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(
                    f"excluded semantic task {task.get('id', position)!r} "
                    "requires exclusion_reason"
                )

    expected_hash = semantic_ground_truth_hash(payload)
    if protocol.get("ground_truth_sha256") != expected_hash:
        raise ValueError(
            "semantic ground truth is not frozen or changed; set "
            f"protocol.ground_truth_sha256 to {expected_hash}"
        )
    return {
        "query_freeze_sha256": query_hash,
        "ground_truth_sha256": expected_hash,
        "task_count": len(tasks),
        "eligible_tasks": eligible,
        "excluded_tasks": excluded,
    }


def _trivial_lexical_files(
    index: RepositoryIndex,
    query: str,
    *,
    max_files: int,
) -> list[str]:
    """Rank files by distinct normalized query-term presence only."""
    q_terms = set(terms(query))
    scored: list[tuple[int, str]] = []
    for rel, record in index.records.items():
        document_terms = set((record.term_counts or {}).keys())
        score = len(q_terms & document_terms)
        if score:
            scored.append((score, rel))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [rel for _, rel in scored[:max_files]]


def _arm_result(
    expected_files: set[str],
    selected_files: list[str],
    *,
    tokens: int | None = None,
    source_tokens: int | None = None,
) -> dict[str, Any]:
    """Return comparable per-arm file evidence."""
    result: dict[str, Any] = {
        "selected_files": selected_files,
        "file_recall": _recall(expected_files, set(selected_files)),
    }
    if tokens is not None:
        result["tokens"] = tokens
        if source_tokens is not None:
            result["token_reduction"] = 1.0 - min(1.0, tokens / max(1, source_tokens))
    return result


def _summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate three-arm file recall and semantic delta evidence."""
    if not items:
        return {
            "task_count": 0,
            "lexical_file_recall": 0.0,
            "semantic_file_recall": 0.0,
            "trivial_lexical_file_recall": 0.0,
            "semantic_recovered_tasks": 0,
            "semantic_regressed_tasks": 0,
        }
    return {
        "task_count": len(items),
        "lexical_file_recall": sum(
            item["lexical"]["file_recall"] for item in items
        ) / len(items),
        "semantic_file_recall": sum(
            item["semantic"]["file_recall"] for item in items
        ) / len(items),
        "trivial_lexical_file_recall": sum(
            item["trivial_lexical"]["file_recall"] for item in items
        ) / len(items),
        "lexical_mean_token_reduction": sum(
            item["lexical"]["token_reduction"] for item in items
        ) / len(items),
        "semantic_mean_token_reduction": sum(
            item["semantic"]["token_reduction"] for item in items
        ) / len(items),
        "semantic_recovered_tasks": sum(bool(item["semantic_recovered"]) for item in items),
        "semantic_regressed_tasks": sum(bool(item["semantic_regressed"]) for item in items),
        "semantic_file_recall_delta": sum(
            item["semantic"]["file_recall"] - item["lexical"]["file_recall"]
            for item in items
        ) / len(items),
    }


def evaluate_semantic_holdout(
    root: Path,
    manifest: Path,
) -> dict[str, Any]:
    """Evaluate frozen lexical, hybrid-semantic, and trivial-baseline arms."""
    root = root.resolve()
    manifest = manifest.resolve()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    validation = validate_semantic_holdout(payload, manifest)
    specs = _repository_specs(payload, manifest)

    indexes: dict[Path, RepositoryIndex] = {}
    source_tokens: dict[Path, int] = {}
    revisions: dict[Path, str | None] = {}
    results: list[dict[str, Any]] = []
    by_repository: dict[str, list[dict[str, Any]]] = {}

    for position, task in enumerate(payload["tasks"], start=1):
        if not bool(task.get("eligible", True)):
            continue
        alias = task.get("repository")
        if not isinstance(alias, str) or alias not in specs:
            raise ValueError(f"task {position} references unknown repository {alias!r}")
        repo_root, expected_revision = specs[alias]
        if not repo_root.is_dir():
            raise ValueError(f"repository path does not exist: {repo_root}")
        if repo_root not in indexes:
            revision = _git_revision(repo_root)
            revisions[repo_root] = revision
            if expected_revision and revision != expected_revision:
                raise ValueError(
                    f"repository {alias!r} revision mismatch: expected "
                    f"{expected_revision}, got {revision or 'not-a-git-repository'}"
                )
            index = build_index(repo_root)
            indexes[repo_root] = index
            source_tokens[repo_root] = max(
                1,
                sum(max(1, record.size // 4) for record in index.records.values()),
            )
        index = indexes[repo_root]

        query = str(task["query"])
        expected_files = {
            str(value).replace("\\", "/") for value in task.get("files", [])
        }
        max_tokens = int(task.get("max_tokens", payload.get("max_tokens", 6000)))
        max_files = int(task.get("max_files", payload.get("max_files", 12)))

        lexical_pack = build_context_pack(
            repo_root,
            query,
            max_tokens=max_tokens,
            max_files=max_files,
            changed_boost=False,
            feedback_boost=False,
            index=index,
            embeddings=False,
            cache_enabled=False,
        )
        semantic_pack = build_context_pack(
            repo_root,
            query,
            max_tokens=max_tokens,
            max_files=max_files,
            changed_boost=False,
            feedback_boost=False,
            index=index,
            embeddings=True,
            cache_enabled=False,
        )
        trivial_files = _trivial_lexical_files(
            index,
            query,
            max_files=max_files,
        )

        lexical = _arm_result(
            expected_files,
            lexical_pack.selected_files,
            tokens=lexical_pack.estimated_tokens,
            source_tokens=source_tokens[repo_root],
        )
        semantic = _arm_result(
            expected_files,
            semantic_pack.selected_files,
            tokens=semantic_pack.estimated_tokens,
            source_tokens=source_tokens[repo_root],
        )
        trivial = _arm_result(expected_files, trivial_files)
        item = {
            "id": task.get("id", position),
            "repository": alias,
            "revision": revisions[repo_root],
            "source_issue": task.get("source_issue"),
            "expected_files": sorted(expected_files),
            "lexical": lexical,
            "semantic": semantic,
            "trivial_lexical": trivial,
            "semantic_recovered": (
                lexical["file_recall"] < 1.0 and semantic["file_recall"] == 1.0
            ),
            "semantic_regressed": (
                lexical["file_recall"] == 1.0 and semantic["file_recall"] < 1.0
            ),
        }
        results.append(item)
        by_repository.setdefault(alias, []).append(item)

    return {
        "suite": "semantic-holdout-13",
        "tasks": results,
        "excluded_tasks": [
            {
                "id": task.get("id"),
                "reason": task.get("exclusion_reason"),
            }
            for task in payload["tasks"]
            if not bool(task.get("eligible", True))
        ],
        "repositories": {
            alias: _summarize(items)
            for alias, items in sorted(by_repository.items())
        },
        "summary": _summarize(results),
        "protocol": validation,
        "claim_boundary": (
            "This first evaluation burns the suite for tuning. Results measure "
            "file retrieval on this frozen no-identifier-leakage cohort; they "
            "are not an API-cost or task-success claim."
        ),
    }
