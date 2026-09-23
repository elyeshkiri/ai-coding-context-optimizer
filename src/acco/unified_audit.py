"""One evidence-oriented audit across ACCO optimization layers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .audit import audit as context_audit
from .client_capabilities import capability_report
from .efficiency.advisor import advisor_report
from .estimate import Counter
from .fastpath import status as fastpath_status
from .mcp import probe_all
from .processor_mining import mine_transcripts
from .recovery import DEFAULT_CAPACITY_BYTES, RecoveryStore, recovery_path
from .semantic_retrieval import semantic_status
from .sessions import transcript_paths


def _recovery_status(root: Path) -> dict[str, Any]:
    """Report recovery capacity without creating a database merely for audit."""
    path = recovery_path(root)
    if not path.is_file():
        return {
            "path": str(path),
            "records": 0,
            "used_bytes": 0,
            "capacity_bytes": DEFAULT_CAPACITY_BYTES,
            "remaining_bytes": DEFAULT_CAPACITY_BYTES,
            "initialized": False,
        }
    result = RecoveryStore(root).stats()
    result["initialized"] = True
    return result


def _context_summary(
    root: Path,
    report,
    *,
    mcp_timeout: int,
    probe_mcp: bool,
) -> dict:
    """Convert the context audit into a stable JSON-safe summary."""
    mcp = []
    if probe_mcp:
        mcp = [
            {
                "name": item.name,
                "tools": item.tools,
                "tokens": item.tokens,
                "status": item.status,
            }
            for item in probe_all(root, timeout=mcp_timeout)
        ]
    return {
        "always_on_tokens": report.always_on,
        "on_demand_tokens": report.on_demand,
        "counter": report.counter_label,
        "window": report.window,
        "window_share": report.always_on / report.window if report.window else None,
        "mcp_servers_configured": list(report.mcp_servers),
        "mcp_probe": mcp,
        "largest_always_on": [
            {
                "path": item.path,
                "kind": item.kind,
                "tokens": item.tokens,
                "note": item.note,
            }
            for item in sorted(
                (entry for entry in report.items if entry.always_on),
                key=lambda item: (-item.tokens, item.path),
            )[:8]
        ],
    }


def _extra_recommendations(
    *,
    semantic: dict,
    fastpath: dict,
    processors: dict,
    client: dict | None,
) -> list[dict]:
    """Generate bounded actions tied directly to observed subsystem state."""
    items: list[dict] = []
    if int(semantic.get("chunks") or 0) == 0:
        items.append({
            "priority": "medium",
            "id": "build-semantic-index",
            "evidence": "semantic index contains no chunks",
            "action": "Run acco semantic-index before enabling semantic retrieval.",
        })
    if not fastpath.get("available"):
        items.append({
            "priority": "info",
            "id": "consider-rust-fastpath",
            "evidence": "Python fallback is active",
            "action": "Install/build the optional Rust extension when output/index hot-path latency matters.",
        })
    generic = int(processors.get("generic_output_tokens") or 0)
    total = int(processors.get("total_output_tokens") or 0)
    if total and generic:
        share = generic / total
        items.append({
            "priority": "high" if share >= 0.40 else "medium",
            "id": "expand-output-processors",
            "evidence": f"{share:.1%} of analyzed Bash output tokens used the generic processor",
            "action": "Use corpus-analyze unsupported families as the next processor-development queue.",
        })
    if client is not None:
        adaptive = client.get("features", {}).get("adaptive-mcp", {})
        if adaptive and not adaptive.get("guaranteed"):
            items.append({
                "priority": "info",
                "id": "adaptive-mcp-host-fallback",
                "evidence": "adaptive MCP dynamic refresh is not guaranteed for the selected client",
                "action": "Keep full MCP profile as the compatibility fallback for that host.",
            })
    order = {"high": 0, "medium": 1, "info": 2}
    return sorted(items, key=lambda item: (order[item["priority"]], item["id"]))


def unified_audit_report(
    root: Path,
    *,
    days: int = 7,
    window: int = 200_000,
    user_scope: bool = True,
    rates_path: str | Path | None = None,
    client: str | None = None,
    top: int = 10,
    min_processor_tokens: int = 100,
    probe_mcp: bool = False,
    mcp_timeout: int = 15,
    counter: Counter | None = None,
) -> dict:
    """Build one cross-layer audit without turning estimates into savings claims."""
    if days <= 0:
        raise ValueError("days must be positive")
    if window <= 0:
        raise ValueError("window must be positive")
    if top <= 0:
        raise ValueError("top must be positive")
    if mcp_timeout <= 0:
        raise ValueError("mcp timeout must be positive")
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")

    audited = context_audit(
        root,
        counter=counter,
        window=window,
        user_scope=user_scope,
    )
    advisor = advisor_report(
        root,
        days=days,
        rates_path=rates_path,
        user_scope=user_scope,
    )
    semantic = semantic_status(root)
    fastpath = fastpath_status()
    paths = transcript_paths(root)
    processors = mine_transcripts(
        paths,
        min_tokens=min_processor_tokens,
        top=top,
    )
    selected_client = capability_report(client) if client else None
    context = _context_summary(
        root,
        audited,
        mcp_timeout=mcp_timeout,
        probe_mcp=probe_mcp,
    )
    recommendations = [
        *advisor.get("recommendations", []),
        *_extra_recommendations(
            semantic=semantic,
            fastpath=fastpath,
            processors=processors,
            client=selected_client,
        ),
    ]

    return {
        "schema": 1,
        "root": str(root),
        "window_days": days,
        "context": context,
        "efficiency": {
            "score": advisor.get("score"),
            "usage": advisor.get("usage"),
            "cost": advisor.get("cost"),
            "savings": advisor.get("savings"),
            "behavior": advisor.get("behavior"),
            "continuity": advisor.get("continuity"),
            "model_routing": advisor.get("model_routing"),
        },
        "retrieval": {"semantic": semantic},
        "fastpath": fastpath,
        "processor_coverage": processors,
        "client_capabilities": selected_client,
        "recovery": _recovery_status(root),
        "recommendations": recommendations[:14],
        "evidence": {
            "measured": [
                "context size and configured files",
                "provider usage/cache counters when present",
                "transcript-observed Bash output size and processor routing",
                "semantic index state",
                "local fastpath availability",
            ],
            "estimated": [
                "tool-context reduction telemetry from ACCO transforms",
            ],
            "not_claimed": [
                "task success from audit data alone",
                "quality preservation from token counts alone",
                "end-to-end cost-per-success without paired evaluation",
            ],
        },
    }
