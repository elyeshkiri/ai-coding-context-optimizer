"""Measure where tokens actually went, from Claude Code's own session transcripts.

Everything else in this package acts on a theory of where tokens go. This module
reads the record. Claude Code writes one JSONL file per session under
``~/.claude/projects/<slug>/``; each assistant turn carries a ``usage`` block and
each tool result carries its payload, so the real cost of a session is on disk.

Nothing here talks to the network and nothing is mutated — transcripts are only
ever read.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .estimate import estimate_tokens
from .images import cost_from_base64
from .skeleton import skeletonize

# Outlining only makes sense where signatures preserve the point of the file.
# Skeletonising prose or data deletes the content rather than compressing it,
# so those reads are never counted as an outline saving.
OUTLINE_SUFFIXES = {
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs",
    ".java", ".kt", ".swift", ".rb", ".php", ".cs", ".c", ".h", ".cpp", ".hpp",
}

USAGE_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)

# Minimum cache write size considered by the heuristic classifier.
REPRIME_MIN_TOKENS = 20_000


def projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def project_slug(path: Path) -> str:
    """Claude Code's directory name for a project: its absolute path, / -> -."""
    return str(Path(path).resolve()).replace("/", "-")


def transcript_paths(root: Path | None = None, all_projects: bool = False) -> list[Path]:
    base = projects_dir()
    if not base.is_dir():
        return []
    if all_projects or root is None:
        return sorted(base.rglob("*.jsonl"))
    scoped = base / project_slug(root)
    return sorted(scoped.rglob("*.jsonl")) if scoped.is_dir() else []


@dataclass
class ToolCall:
    name: str
    tokens: int
    session: str
    path: str | None = None
    content: str | None = None
    digest: str | None = None
    epoch: int = 0
    estimated: bool = True
    unknown_size: bool = False
    kind: str = "text"      # text | image | other

    @property
    def outlinable(self) -> bool:
        return (
            self.kind == "text"
            and bool(self.path)
            and bool(self.content)
            and Path(self.path).suffix.lower() in OUTLINE_SUFFIXES
        )

    @property
    def label(self) -> str:
        if self.path:
            return self.path
        return f"({self.name} {self.kind} result)"


@dataclass
class Turn:
    """One assistant API response, counted once however many blocks it spans."""

    session: str
    created: int = 0     # cache_creation_input_tokens
    read: int = 0        # cache_read_input_tokens
    timestamp: str | None = None
    epoch: int = 0
    model: str = "unknown"
    input_tokens: int = 0
    output_tokens: int = 0
    cache_5m: int = 0
    cache_1h: int = 0
    cache_kind: str = "unknown"
    suspected_recreated: int = 0

    @property
    def cold_reprime(self) -> bool:
        """Compatibility flag set by Report.cache_churn; never proves waste."""
        return self.cache_kind == "suspected_recreation"


@dataclass
class Report:
    sessions: int = 0
    usage: Counter = field(default_factory=Counter)
    calls: list[ToolCall] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)

    @property
    def fresh_input(self) -> int:
        return self.usage["input_tokens"] + self.usage["cache_creation_input_tokens"]

    @property
    def cache_hit_rate(self) -> float:
        cached = self.usage["cache_read_input_tokens"]
        total = cached + self.fresh_input
        return cached / total if total else 0.0

    def by_tool(self) -> list[tuple[str, int, int]]:
        """(tool, total tokens, call count), biggest first."""
        totals: Counter = Counter()
        counts: Counter = Counter()
        for call in self.calls:
            totals[call.name] += call.tokens
            counts[call.name] += 1
        return [(n, t, counts[n]) for n, t in totals.most_common()]

    def biggest(self, limit: int = 10) -> list[ToolCall]:
        return sorted(self.calls, key=lambda c: -c.tokens)[:limit]

    def image_cost(self) -> tuple[int, int]:
        """Approximate visual size and image count; unknown images contribute zero."""
        images = [c for c in self.calls if c.kind == "image"]
        return sum(c.tokens for c in images), len(images)

    def duplicate_reads(self) -> list[tuple[str, int, int]]:
        """Same-session/context repeats; their necessity cannot be inferred."""
        groups: dict[tuple[str, int, str, str], list[ToolCall]] = defaultdict(list)
        for call in self.calls:
            if call.name == "Read" and call.path and call.digest:
                groups[(call.session, call.epoch, call.path, call.digest)].append(call)
        out = [
            (path, len(calls), calls[0].tokens * (len(calls) - 1))
            for (_session, _epoch, path, _digest), calls in groups.items()
            if len(calls) > 1
        ]
        return sorted(out, key=lambda row: -row[2])

    def cache_churn(self) -> tuple[int, int, list[Turn]]:
        """Suspected recreated overlap, count, and candidates (not avoidable waste).

        Usage cannot distinguish expiry from changed prefixes. Initial observations
        and context resets are excluded; ordinary append-only growth is separate.
        """
        previous = {}
        cold = []
        for turn in self.turns:
            key = (turn.session, turn.epoch)
            prior = previous.get(key)
            turn.suspected_recreated = 0
            prefix = turn.created + turn.read
            if prior is None:
                turn.cache_kind = "initial_observation"
            elif turn.created == 0:
                turn.cache_kind = "cache_hit" if turn.read else "uncached"
            elif turn.read >= prior:
                turn.cache_kind = "prefix_growth"
            elif (turn.created >= REPRIME_MIN_TOKENS and prior >= REPRIME_MIN_TOKENS
                  and prefix >= prior * 0.8):
                turn.cache_kind = "suspected_recreation"
                turn.suspected_recreated = min(turn.created, max(0, prior - turn.read))
                cold.append(turn)
            else:
                turn.cache_kind = "unclassified_write"
            previous[key] = prefix
        cold.sort(key=lambda t: -t.suspected_recreated)
        return sum(t.suspected_recreated for t in cold), len(cold), cold

    def outline_savings(self) -> tuple[int, int, list[tuple[str, int, int]]]:
        """What skeletonising every recoverable file read would have cost instead.

        Returns (tokens read, tokens if outlined, per-file rows).
        """
        rows: list[tuple[str, int, int]] = []
        before = after = 0
        for call in self.calls:
            if not call.outlinable:
                continue
            suffix = Path(call.path).suffix
            outlined = estimate_tokens(skeletonize(call.content, suffix), suffix)
            before += call.tokens
            after += outlined
            rows.append((call.path, call.tokens, outlined))
        rows.sort(key=lambda row: -(row[1] - row[2]))
        return before, after, rows


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def analyze(paths: list[Path], keep_content: bool = True) -> Report:
    report = Report()
    for path in paths:
        names: dict[str, str] = {}
        # Claude Code writes one transcript line per *content block*, and every
        # line repeats the same message.usage. Counting per line bills a single
        # API response once per block it happened to emit, which on a turn with
        # thinking + text + three tool_use blocks overstates it fivefold.
        counted: dict[str, dict] = {}
        turn_by_id: dict[str, Turn] = {}
        epoch = 0
        session = str(path.resolve())
        try:
            handle = path.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        report.sessions += 1
        with handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("subtype") == "compact_boundary" or record.get("type") == "compact_boundary":
                    epoch += 1
                message = record.get("message") or {}
                if not isinstance(message, dict):
                    continue

                if record.get("type") == "assistant":
                    usage = message.get("usage") or {}
                    message_id = message.get("id")
                    # no id: cannot dedupe, so count it and hope it is unique
                    key_id = message_id or f"__line__{len(counted)}"
                    if isinstance(usage, dict) and usage:
                        prior = counted.setdefault(key_id, {})
                        for key in USAGE_FIELDS:
                            value = usage.get(key) or 0
                            if not isinstance(value, int) or value < 0: continue
                            value = max(value, prior.get(key, 0))
                            report.usage[key] += value - prior.get(key, 0)
                            prior[key] = value
                        if key_id not in turn_by_id:
                            turn = Turn(session=session, epoch=epoch, timestamp=record.get("timestamp"))
                            turn_by_id[key_id] = turn
                            report.turns.append(turn)
                        turn = turn_by_id[key_id]
                        turn.created = prior.get("cache_creation_input_tokens", 0)
                        turn.read = prior.get("cache_read_input_tokens", 0)
                        turn.input_tokens = prior.get("input_tokens", 0)
                        turn.output_tokens = prior.get("output_tokens", 0)
                        turn.model = message.get("model") or turn.model
                        breakdown = usage.get("cache_creation") or {}
                        if isinstance(breakdown, dict):
                            for field, attr in (("ephemeral_5m_input_tokens", "cache_5m"), ("ephemeral_1h_input_tokens", "cache_1h")):
                                value = breakdown.get(field, 0)
                                if isinstance(value, int) and value >= 0:
                                    setattr(turn, attr, max(getattr(turn, attr), value))
                    for block in message.get("content") or []:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            uid = block.get("id")
                            if uid:
                                names[uid] = block.get("name") or "unknown"

                result = record.get("toolUseResult")
                if result is None:
                    continue
                name = "unknown"
                for block in message.get("content") or []:
                    if not isinstance(block, dict):
                        continue
                    uid = block.get("tool_use_id") or block.get("toolUseId")
                    if uid in names:
                        name = names[uid]
                        break
                if name == "unknown":
                    uid = record.get("toolUseID") or record.get("tool_use_id")
                    if uid in names:
                        name = names[uid]
                if name == "unknown" and isinstance(result, dict) and isinstance(result.get("file"), dict):
                    name = "Read"
                payload = result if isinstance(result, str) else json.dumps(result)
                call = ToolCall(
                    name=name,
                    tokens=estimate_tokens(payload),
                    session=session,
                    epoch=epoch,
                )
                info = result.get("file") if isinstance(result, dict) else None
                if isinstance(info, dict):
                    if info.get("base64") or result.get("type") == "image":
                        call.kind = "image"
                        # bill images as visual tokens, never as base64 length
                        measured = cost_from_base64(info.get("base64") or "")
                        if not measured:
                            call.tokens = 0
                            call.unknown_size = True
                        if measured:
                            call.tokens = measured.tokens
                            call.path = f"{measured.width}x{measured.height} {measured.fmt}"
                    elif info.get("filePath"):
                        body = info.get("content") or ""
                        call.path = info["filePath"]
                        call.tokens = (
                            estimate_tokens(body, Path(call.path).suffix) or call.tokens
                        )
                        call.digest = _digest(body)
                        if keep_content:
                            call.content = body
                report.calls.append(call)
    return report
