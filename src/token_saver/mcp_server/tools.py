"""Application-level MCP tool registry and tool implementations."""

from __future__ import annotations

from collections.abc import Iterable

from ..output_saver import build_output_policy, compact_output
from ..patch_context import build_diff_context, review_patch
from .contracts import McpToolContext, McpToolSpec


class McpToolRegistry:
    """Resolve MCP tool calls without coupling handlers to JSON-RPC transport."""

    def __init__(self, specs: Iterable[McpToolSpec]):
        """Build a registry and reject ambiguous duplicate tool names."""
        by_name: dict[str, McpToolSpec] = {}
        for spec in specs:
            if spec.name in by_name:
                raise ValueError(f"duplicate MCP tool registration: {spec.name}")
            by_name[spec.name] = spec
        self._specs = by_name

    def schemas(self) -> list[dict]:
        """Return tools/list schemas in deterministic registration order."""
        return [spec.to_schema() for spec in self._specs.values()]

    def names(self) -> tuple[str, ...]:
        """Return registered tool names in deterministic order."""
        return tuple(self._specs)

    def call(self, name: str, context: McpToolContext, arguments: dict) -> object:
        """Call a registered application handler or reject an unknown tool."""
        spec = self._specs.get(name)
        if spec is None:
            raise ValueError(f"unknown tool: {name}")
        return spec.handler(context, arguments)


def _build_context(context: McpToolContext, arguments: dict) -> dict:
    """Build a task-aware source context pack."""
    pack = context.repository.build_context(
        str(arguments.get("query", "")),
        max_tokens=int(arguments.get("max_tokens", 6000)),
        target_symbol=arguments.get("target_symbol"),
    )
    return {
        "text": pack.text,
        "estimated_tokens": pack.estimated_tokens,
        "selected_files": pack.selected_files,
        "selected_symbols": pack.selected_symbols,
        "redactions": pack.redactions,
        "closure_files": pack.closure_files,
    }


def _browse_context(context: McpToolContext, arguments: dict) -> dict:
    """Return ranked repository source candidates for a query."""
    return context.repository.browse(
        str(arguments.get("query", "")),
        max_files=int(arguments.get("max_files", 8)),
        preview_tokens=int(arguments.get("preview_tokens", 350)),
    )


def _explain_ranking(context: McpToolContext, arguments: dict) -> dict:
    """Explain stage-by-stage file-ranking score contributions."""
    return context.repository.explain_ranking(
        str(arguments.get("query", "")),
        max_files=int(arguments.get("max_files", 8)),
        changed_boost=bool(arguments.get("changed_boost", True)),
        embeddings=bool(arguments.get("embeddings", False)),
    )


def _find_symbol(context: McpToolContext, arguments: dict) -> list[dict]:
    """Find symbol definitions and source ranges."""
    return context.repository.find_symbols(str(arguments.get("name", "")))


def _analyze_change_impact(context: McpToolContext, arguments: dict) -> dict:
    """Return callers, dependents, tests, and graph evidence for a target."""
    return context.repository.impact(
        str(arguments.get("target", ""))
    ).to_dict()


def _report_context_feedback(context: McpToolContext, arguments: dict) -> dict:
    """Record whether one included file was useful for future local ranking."""
    scores = context.repository.feedback(
        str(arguments.get("path", "")),
        useful=bool(arguments.get("useful")),
    )
    return {"scores": scores}


def _index_status(context: McpToolContext, arguments: dict) -> dict:
    """Return persistent repository-index lifecycle metadata."""
    del arguments
    return context.repository.status()


def _refresh_index(context: McpToolContext, arguments: dict) -> dict:
    """Refresh the repository index and return its resulting status."""
    del arguments
    context.repository.refresh()
    return context.repository.status()


def _remember_finding(context: McpToolContext, arguments: dict) -> dict:
    """Persist one explicit evidence-backed project finding."""
    anchors = arguments.get("anchors")
    invalidators = arguments.get("invalidators")
    supersedes = arguments.get("supersedes")
    return context.repository.remember_finding(
        claim=str(arguments.get("claim", "")),
        anchors=[str(value) for value in anchors] if isinstance(anchors, list) else [],
        evidence=str(arguments.get("evidence", "")),
        applicability=str(arguments.get("applicability", "")),
        confidence=str(arguments.get("confidence", "verified")),
        invalidators=(
            [str(value) for value in invalidators]
            if isinstance(invalidators, list)
            else None
        ),
        supersedes=(
            [str(value) for value in supersedes]
            if isinstance(supersedes, list)
            else None
        ),
        source="mcp",
    )


def _recall_findings(context: McpToolContext, arguments: dict) -> list[dict]:
    """Recall current evidence-backed findings relevant to one query."""
    return context.repository.recall_findings(
        str(arguments.get("query", "")),
        limit=int(arguments.get("limit", 5)),
        include_stale=bool(arguments.get("include_stale", False)),
    )


def _knowledge_status(context: McpToolContext, arguments: dict) -> dict:
    """Return knowledge counts without exposing finding contents."""
    del arguments
    return context.repository.knowledge_status()


def _build_diff_context(context: McpToolContext, arguments: dict) -> dict:
    """Build context around the current Git patch and its impact closure."""
    return build_diff_context(
        context.root,
        base=str(arguments.get("base", "HEAD")),
        staged=bool(arguments.get("staged", False)),
        max_tokens=int(arguments.get("max_tokens", 6000)),
    )


def _review_diff(context: McpToolContext, arguments: dict) -> dict:
    """Report changed symbols, impact, API changes, and test coverage signals."""
    return review_patch(
        context.root,
        base=str(arguments.get("base", "HEAD")),
        staged=bool(arguments.get("staged", False)),
    )


def _output_policy(context: McpToolContext, arguments: dict) -> dict:
    """Return generation-time response policy metadata."""
    del context
    policy = build_output_policy(
        str(arguments.get("mode", "normal")),
        int(arguments["max_tokens"]) if "max_tokens" in arguments else None,
        str(arguments.get("task", "general")),
    )
    return policy.to_dict()


def _compact_output(context: McpToolContext, arguments: dict) -> dict:
    """Compact generated prose while preserving fenced code and diffs."""
    del context
    result = compact_output(
        str(arguments.get("text", "")),
        mode=str(arguments.get("mode", "normal")),
        max_tokens=int(arguments["max_tokens"]) if "max_tokens" in arguments else None,
        enforce_budget=bool(arguments.get("enforce_budget", False)),
    )
    return result.to_dict()


DEFAULT_TOOL_REGISTRY = McpToolRegistry(
    [
        McpToolSpec(
            "build_context",
            "Build a task-aware source context pack under a hard token budget.",
            {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "max_tokens": {"type": "integer", "minimum": 1},
                    "target_symbol": {"type": "string"},
                },
            },
            _build_context,
        ),
        McpToolSpec(
            "find_symbol",
            "Find exact or partial symbol definitions with source ranges.",
            {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            },
            _find_symbol,
        ),
        McpToolSpec(
            "browse_context",
            "Inspect ranked files, selected symbols, fuzzy corrections, and source previews.",
            {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "max_files": {"type": "integer", "minimum": 1},
                    "preview_tokens": {"type": "integer", "minimum": 1},
                },
            },
            _browse_context,
        ),
        McpToolSpec(
            "explain_ranking",
            "Explain stage-by-stage score contributions for ranked repository files.",
            {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "max_files": {"type": "integer", "minimum": 1},
                    "changed_boost": {"type": "boolean"},
                    "embeddings": {"type": "boolean"},
                },
            },
            _explain_ranking,
        ),
        McpToolSpec(
            "analyze_change_impact",
            "Find callers, dependents, and related tests for a file or symbol.",
            {
                "type": "object",
                "required": ["target"],
                "properties": {"target": {"type": "string"}},
            },
            _analyze_change_impact,
        ),
        McpToolSpec(
            "report_context_feedback",
            "Record whether an included file was useful for future local ranking.",
            {
                "type": "object",
                "required": ["path", "useful"],
                "properties": {
                    "path": {"type": "string"},
                    "useful": {"type": "boolean"},
                },
            },
            _report_context_feedback,
        ),
        McpToolSpec(
            "index_status",
            "Report persistent repository index size, reuse, and refresh time.",
            {"type": "object", "properties": {}},
            _index_status,
        ),
        McpToolSpec(
            "refresh_index",
            "Incrementally refresh the persistent repository index.",
            {"type": "object", "properties": {}},
            _refresh_index,
        ),
        McpToolSpec(
            "remember_finding",
            "Persist a durable evidence-backed project finding anchored to current source files.",
            {
                "type": "object",
                "required": ["claim", "anchors", "evidence", "applicability"],
                "properties": {
                    "claim": {"type": "string"},
                    "anchors": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "items": {"type": "string"},
                    },
                    "evidence": {"type": "string"},
                    "applicability": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["speculative", "probable", "verified"],
                    },
                    "invalidators": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "supersedes": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
            _remember_finding,
        ),
        McpToolSpec(
            "recall_findings",
            "Recall durable project findings; changed source anchors are excluded as stale by default.",
            {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    "include_stale": {"type": "boolean"},
                },
            },
            _recall_findings,
        ),
        McpToolSpec(
            "knowledge_status",
            "Report active, stale, and superseded project-knowledge counts.",
            {"type": "object", "properties": {}},
            _knowledge_status,
        ),
        McpToolSpec(
            "build_diff_context",
            "Build context around the current Git patch and its impact closure.",
            {
                "type": "object",
                "properties": {
                    "base": {"type": "string"},
                    "staged": {"type": "boolean"},
                    "max_tokens": {"type": "integer", "minimum": 1},
                },
            },
            _build_diff_context,
        ),
        McpToolSpec(
            "review_diff",
            "Report changed symbols, impact, API changes, and test coverage signals.",
            {
                "type": "object",
                "properties": {
                    "base": {"type": "string"},
                    "staged": {"type": "boolean"},
                },
            },
            _review_diff,
        ),
        McpToolSpec(
            "output_policy",
            "Return a generation-time response policy for reducing output tokens.",
            {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["terse", "normal", "detailed"],
                    },
                    "max_tokens": {"type": "integer", "minimum": 1},
                    "task": {
                        "type": "string",
                        "enum": [
                            "general",
                            "coding",
                            "debugging",
                            "review",
                            "explanation",
                            "planning",
                        ],
                    },
                },
            },
            _output_policy,
        ),
        McpToolSpec(
            "compact_output",
            "Safely compact generated prose while preserving fenced code/diffs exactly.",
            {
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text": {"type": "string"},
                    "mode": {
                        "type": "string",
                        "enum": ["terse", "normal", "detailed"],
                    },
                    "max_tokens": {"type": "integer", "minimum": 1},
                    "enforce_budget": {"type": "boolean"},
                },
            },
            _compact_output,
        ),
    ]
)
