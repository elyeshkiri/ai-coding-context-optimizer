"""Ranking snapshot and regression-diff utilities built on score traces."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .evaluate import _git_revision, _repository_specs, ground_truth_hash
from .repository_service import RepositoryContextService

SNAPSHOT_SCHEMA_VERSION = 1


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    """Load one JSON object or raise a focused validation error."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _normalized_files(values: object) -> list[str]:
    """Return deterministic repository-relative file paths from manifest values."""
    if not isinstance(values, list):
        return []
    return sorted(
        {
            value.replace("\\", "/")
            for value in values
            if isinstance(value, str) and value
        }
    )


def _resolve_repository(
    root: Path,
    specs: dict[str, tuple[Path, str | None]],
    alias: object,
) -> tuple[str, Path, str | None]:
    """Resolve one task repository alias with the same semantics as evaluation."""
    if alias is None:
        return "default", root, None
    if not isinstance(alias, str):
        raise ValueError("task repository must be a string alias")
    if alias not in specs:
        raise ValueError(f"task references unknown repository alias: {alias}")
    path, expected_revision = specs[alias]
    return alias, path, expected_revision


def _expected_observations(
    expected_files: list[str],
    results: list[dict],
) -> list[dict]:
    """Extract compact expected-file rank/score evidence from one explanation."""
    by_path = {item["path"]: item for item in results}
    observations: list[dict] = []
    for path in expected_files:
        item = by_path.get(path)
        observations.append(
            {
                "path": path,
                "rank": item["rank"] if item else None,
                "final_score": item["final_score"] if item else None,
                "stage_deltas": dict(item["stage_deltas"]) if item else {},
                "trace_complete": bool(item and item["trace_complete"]),
            }
        )
    return observations


def build_ranking_snapshot(
    root: Path,
    manifest: Path,
    *,
    max_files: int = 20,
    graph_hops: int = 1,
    closure_max_items: int = 20,
    embeddings: bool = False,
) -> dict:
    """Capture ranking traces for every task in an evaluation-style manifest."""
    if max_files <= 0:
        raise ValueError("max_files must be positive")
    if graph_hops < 0:
        raise ValueError("graph_hops must be nonnegative")
    if closure_max_items <= 0:
        raise ValueError("closure_max_items must be positive")

    root = root.resolve()
    manifest = manifest.resolve()
    payload = _load_json_object(manifest, label="manifest")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("manifest must contain a non-empty 'tasks' list")

    specs = _repository_specs(payload, manifest)
    services: dict[Path, RepositoryContextService] = {}
    revisions: dict[str, str | None] = {}
    results: list[dict] = []
    seen_ids: set[str] = set()

    for position, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            raise ValueError(f"task {position} must be an object")
        task_id = str(task.get("id", position))
        if task_id in seen_ids:
            raise ValueError(f"duplicate task id: {task_id}")
        seen_ids.add(task_id)

        repo_name, repo_root, expected_revision = _resolve_repository(
            root,
            specs,
            task.get("repository"),
        )
        if not repo_root.is_dir():
            raise ValueError(f"repository path does not exist: {repo_root}")
        actual_revision = revisions.get(repo_name)
        if repo_name not in revisions:
            actual_revision = _git_revision(repo_root)
            revisions[repo_name] = actual_revision
        if expected_revision and actual_revision != expected_revision:
            raise ValueError(
                f"repository {repo_name!r} revision mismatch: "
                f"expected {expected_revision}, "
                f"got {actual_revision or 'not-a-git-repository'}"
            )

        service = services.get(repo_root)
        if service is None:
            service = RepositoryContextService(repo_root)
            services[repo_root] = service

        query = str(task.get("query", ""))
        expected_files = _normalized_files(task.get("files", []))
        explanation = service.explain_ranking(
            query,
            max_files=max_files,
            changed_boost=False,
            feedback_boost=False,
            graph_hops=graph_hops,
            closure_max_items=closure_max_items,
            embeddings=embeddings,
            include_paths=set(expected_files),
        )
        results.append(
            {
                "id": task_id,
                "repository": repo_name,
                "query": query,
                "expected_files": expected_files,
                "candidate_count": explanation["candidate_count"],
                "ranking": explanation["results"],
                "expected": _expected_observations(
                    expected_files,
                    explanation["results"],
                ),
            }
        )

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "ground_truth_sha256": ground_truth_hash(payload),
        "manifest": manifest.name,
        "config": {
            "max_files": max_files,
            "changed_boost": False,
            "feedback_boost": False,
            "graph_hops": graph_hops,
            "closure_max_items": closure_max_items,
            "embeddings": embeddings,
            "trace_scores": True,
        },
        "repositories": {
            name: {"revision": revision}
            for name, revision in sorted(revisions.items())
        },
        "tasks": results,
    }


def _snapshot_tasks(snapshot: dict, *, label: str) -> dict[str, dict]:
    """Validate a snapshot and index task records by stable task id."""
    if snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError(
            f"{label} snapshot schema_version must be {SNAPSHOT_SCHEMA_VERSION}"
        )
    tasks = snapshot.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError(f"{label} snapshot must contain non-empty tasks")
    indexed: dict[str, dict] = {}
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str):
            raise ValueError(f"{label} snapshot contains an invalid task record")
        task_id = task["id"]
        if task_id in indexed:
            raise ValueError(f"{label} snapshot has duplicate task id: {task_id}")
        indexed[task_id] = task
    return indexed


def _expected_by_path(task: dict) -> dict[str, dict]:
    """Index one snapshot task's expected-file observations by path."""
    values = task.get("expected", [])
    if not isinstance(values, list):
        raise ValueError(f"task {task.get('id')!r} expected must be a list")
    return {
        item["path"]: item
        for item in values
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }


def _stage_changes(
    baseline: dict[str, float],
    candidate: dict[str, float],
) -> list[dict]:
    """Return per-stage contribution changes sorted by absolute impact."""
    changes = []
    for stage in sorted(set(baseline) | set(candidate)):
        before = float(baseline.get(stage, 0.0))
        after = float(candidate.get(stage, 0.0))
        delta = after - before
        changes.append(
            {
                "stage": stage,
                "baseline": before,
                "candidate": after,
                "delta": delta,
            }
        )
    return sorted(changes, key=lambda item: (-abs(item["delta"]), item["stage"]))


def _rank_delta(baseline: int | None, candidate: int | None) -> int | None:
    """Return positive values for regressions and negative values for improvements."""
    if baseline is None or candidate is None:
        return None
    return candidate - baseline


def _score_delta(baseline: float | None, candidate: float | None) -> float | None:
    """Return candidate-minus-baseline score when both observations exist."""
    if baseline is None or candidate is None:
        return None
    return candidate - baseline


def compare_ranking_snapshots(
    baseline: dict,
    candidate: dict,
) -> dict:
    """Compare expected-file rank movement and attribute score changes by stage."""
    baseline_hash = baseline.get("ground_truth_sha256")
    candidate_hash = candidate.get("ground_truth_sha256")
    if not isinstance(baseline_hash, str) or not isinstance(candidate_hash, str):
        raise ValueError("snapshots must contain ground_truth_sha256")
    if baseline_hash != candidate_hash:
        raise ValueError("snapshot ground truth hashes differ")

    baseline_tasks = _snapshot_tasks(baseline, label="baseline")
    candidate_tasks = _snapshot_tasks(candidate, label="candidate")
    if set(baseline_tasks) != set(candidate_tasks):
        raise ValueError("snapshot task ids differ")

    comparisons: list[dict] = []
    stage_totals: dict[str, float] = {}
    regression_tasks: set[str] = set()
    improvement_tasks: set[str] = set()

    for task_id in sorted(baseline_tasks):
        before_task = baseline_tasks[task_id]
        after_task = candidate_tasks[task_id]
        if before_task.get("repository") != after_task.get("repository"):
            raise ValueError(f"task {task_id} repository differs between snapshots")
        if before_task.get("query") != after_task.get("query"):
            raise ValueError(f"task {task_id} query differs between snapshots")

        before_expected = _expected_by_path(before_task)
        after_expected = _expected_by_path(after_task)
        if set(before_expected) != set(after_expected):
            raise ValueError(f"task {task_id} expected files differ between snapshots")

        files = []
        for path in sorted(before_expected):
            before = before_expected[path]
            after = after_expected[path]
            before_rank = before.get("rank")
            after_rank = after.get("rank")
            rank_delta = _rank_delta(before_rank, after_rank)
            score_delta = _score_delta(
                before.get("final_score"),
                after.get("final_score"),
            )
            stage_changes = _stage_changes(
                before.get("stage_deltas", {}),
                after.get("stage_deltas", {}),
            )
            for change in stage_changes:
                stage_totals[change["stage"]] = (
                    stage_totals.get(change["stage"], 0.0) + change["delta"]
                )

            regression = (
                before_rank is not None
                and (
                    after_rank is None
                    or (rank_delta is not None and rank_delta > 0)
                )
            )
            improvement = (
                after_rank is not None
                and (
                    before_rank is None
                    or (rank_delta is not None and rank_delta < 0)
                )
            )
            if regression:
                regression_tasks.add(task_id)
            if improvement:
                improvement_tasks.add(task_id)

            files.append(
                {
                    "path": path,
                    "baseline_rank": before_rank,
                    "candidate_rank": after_rank,
                    "rank_delta": rank_delta,
                    "baseline_score": before.get("final_score"),
                    "candidate_score": after.get("final_score"),
                    "score_delta": score_delta,
                    "regression": regression,
                    "improvement": improvement,
                    "stage_changes": stage_changes,
                }
            )

        comparisons.append(
            {
                "id": task_id,
                "repository": before_task.get("repository"),
                "query": before_task.get("query"),
                "files": files,
            }
        )

    all_files = [
        item
        for task in comparisons
        for item in task["files"]
    ]
    finite_drops = [
        item["rank_delta"]
        for item in all_files
        if isinstance(item["rank_delta"], int) and item["rank_delta"] > 0
    ]
    missing = sum(
        1
        for item in all_files
        if item["baseline_rank"] is not None and item["candidate_rank"] is None
    )
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "ground_truth_sha256": baseline_hash,
        "baseline_repositories": baseline.get("repositories", {}),
        "candidate_repositories": candidate.get("repositories", {}),
        "baseline_config": baseline.get("config", {}),
        "candidate_config": candidate.get("config", {}),
        "summary": {
            "task_count": len(comparisons),
            "expected_files_compared": len(all_files),
            "regressed_files": sum(bool(item["regression"]) for item in all_files),
            "improved_files": sum(bool(item["improvement"]) for item in all_files),
            "missing_in_candidate": missing,
            "regression_tasks": len(regression_tasks),
            "improvement_tasks": len(improvement_tasks),
            "max_rank_drop": max(finite_drops, default=0),
            "stage_delta_totals": {
                stage: delta
                for stage, delta in sorted(stage_totals.items())
                if not math.isclose(delta, 0.0, abs_tol=1e-12)
            },
        },
        "tasks": comparisons,
    }


def load_ranking_snapshot(path: Path) -> dict:
    """Load one ranking snapshot from disk."""
    return _load_json_object(path.resolve(), label="snapshot")


def regression_violations(
    report: dict,
    *,
    allowed_rank_drop: int = 0,
) -> list[dict]:
    """Return expected-file regressions exceeding a CI rank-drop allowance."""
    if allowed_rank_drop < 0:
        raise ValueError("allowed_rank_drop must be nonnegative")
    violations = []
    for task in report.get("tasks", []):
        for item in task.get("files", []):
            baseline_rank = item.get("baseline_rank")
            candidate_rank = item.get("candidate_rank")
            rank_delta = item.get("rank_delta")
            if baseline_rank is None:
                continue
            if candidate_rank is None or (
                isinstance(rank_delta, int) and rank_delta > allowed_rank_drop
            ):
                violations.append(
                    {
                        "id": task.get("id"),
                        "path": item.get("path"),
                        "baseline_rank": baseline_rank,
                        "candidate_rank": candidate_rank,
                        "rank_delta": rank_delta,
                    }
                )
    return violations


def _markdown_rank(value: int | None) -> str:
    """Render one optional rank for a Markdown table."""
    return "missing" if value is None else str(value)


def render_ranking_diff_markdown(report: dict, *, max_items: int = 20) -> str:
    """Render a compact GitHub-friendly ranking regression summary."""
    if max_items <= 0:
        raise ValueError("max_items must be positive")
    summary = report.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("ranking diff report is missing summary")

    lines = [
        "## ACCO ranking regression report",
        "",
        (
            f"Compared **{summary.get('task_count', 0)} tasks** / "
            f"**{summary.get('expected_files_compared', 0)} expected files**: "
            f"**{summary.get('regressed_files', 0)} regressed**, "
            f"**{summary.get('improved_files', 0)} improved**, "
            f"**{summary.get('missing_in_candidate', 0)} missing**."
        ),
        "",
    ]

    baseline_repos = report.get("baseline_repositories", {})
    candidate_repos = report.get("candidate_repositories", {})
    if baseline_repos or candidate_repos:
        lines.extend(
            [
                "<details>",
                "<summary>Snapshot provenance</summary>",
                "",
                "```json",
                json.dumps(
                    {
                        "baseline_repositories": baseline_repos,
                        "candidate_repositories": candidate_repos,
                        "baseline_config": report.get("baseline_config", {}),
                        "candidate_config": report.get("candidate_config", {}),
                    },
                    indent=2,
                    sort_keys=True,
                ),
                "```",
                "",
                "</details>",
                "",
            ]
        )

    movements = [
        (task, item)
        for task in report.get("tasks", [])
        if isinstance(task, dict)
        for item in task.get("files", [])
        if isinstance(item, dict)
        and (item.get("regression") or item.get("improvement"))
    ]
    movements.sort(
        key=lambda pair: (
            not bool(pair[1].get("regression")),
            -abs(pair[1].get("rank_delta") or 10**9),
            str(pair[0].get("id", "")),
            str(pair[1].get("path", "")),
        )
    )

    if not movements:
        lines.extend(["No expected-file rank movement was detected.", ""])
    else:
        lines.extend(
            [
                "| Task | File | Movement | Score Δ | Strongest stage changes |",
                "|---|---|---:|---:|---|",
            ]
        )
        for task, item in movements[:max_items]:
            before = _markdown_rank(item.get("baseline_rank"))
            after = _markdown_rank(item.get("candidate_rank"))
            direction = "↓" if item.get("regression") else "↑"
            rank_delta = item.get("rank_delta")
            movement = (
                f"{before} → {after} {direction}"
                if rank_delta is None
                else f"{before} → {after} ({rank_delta:+d})"
            )
            score_delta = item.get("score_delta")
            score_text = "n/a" if score_delta is None else f"{score_delta:+.3f}"
            stage_changes = [
                change
                for change in item.get("stage_changes", [])
                if abs(float(change.get("delta", 0.0))) > 1e-12
            ][:3]
            stage_text = "<br>".join(
                f"<code>{change['stage']}</code> {float(change['delta']):+.3f}"
                for change in stage_changes
            ) or "—"
            lines.append(
                f"| {task.get('id', '')} | <code>{item.get('path', '')}</code> | "
                f"{movement} | {score_text} | {stage_text} |"
            )
        lines.append("")

    stage_totals = summary.get("stage_delta_totals", {})
    if isinstance(stage_totals, dict) and stage_totals:
        strongest = sorted(
            stage_totals.items(),
            key=lambda pair: (-abs(float(pair[1])), pair[0]),
        )[:8]
        lines.extend(
            [
                "**Largest aggregate stage changes**",
                "",
                ", ".join(
                    f"<code>{stage}</code> {float(delta):+.3f}"
                    for stage, delta in strongest
                ),
                "",
            ]
        )

    if len(movements) > max_items:
        lines.append(
            f"_Showing {max_items} of {len(movements)} moved expected files; "
            "download the ranking-diff artifact for the complete report._"
        )
        lines.append("")

    return "\n".join(lines)