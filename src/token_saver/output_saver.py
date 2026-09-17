"""Deterministic output-token controls for coding agents.

The output layer has two jobs:
1. Prevent unnecessary tokens from being generated via an explicit response policy.
2. Safely compact already-generated text without altering code/diff blocks.

This module intentionally does not summarize code with an LLM. Code is either
preserved exactly or the caller is told that the requested budget cannot be met.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re

from .estimate import estimate_tokens


_MODE_BUDGETS = {
    "terse": 300,
    "normal": 800,
    "detailed": 2000,
}
_FENCE_RE = re.compile(r"(^\s*```[^\n]*\n.*?^\s*```\s*$)", re.MULTILINE | re.DOTALL)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_FILLER = {
    "sure",
    "sure!",
    "absolutely",
    "absolutely!",
    "of course",
    "of course!",
    "certainly",
    "certainly!",
}
_FILLER_PREFIXES = (
    "here is the requested",
    "here's the requested",
    "here is the updated",
    "here's the updated",
    "i'll provide",
    "i will provide",
)


@dataclass(frozen=True)
class OutputPolicy:
    mode: str
    max_tokens: int
    instructions: str

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "max_tokens": self.max_tokens,
            "instructions": self.instructions,
        }


@dataclass(frozen=True)
class OutputSaveResult:
    text: str
    mode: str
    budget_tokens: int
    original_tokens: int
    output_tokens: int
    removed_units: int
    budget_exceeded: bool
    code_preserved: bool

    @property
    def token_reduction(self) -> float:
        if self.original_tokens <= 0:
            return 0.0
        return max(0.0, 1.0 - self.output_tokens / self.original_tokens)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "mode": self.mode,
            "budget_tokens": self.budget_tokens,
            "original_tokens": self.original_tokens,
            "output_tokens": self.output_tokens,
            "token_reduction": self.token_reduction,
            "removed_units": self.removed_units,
            "budget_exceeded": self.budget_exceeded,
            "code_preserved": self.code_preserved,
        }


def _resolve_budget(mode: str, max_tokens: int | None) -> tuple[str, int]:
    normalized = mode.strip().lower()
    if normalized not in _MODE_BUDGETS:
        raise ValueError(
            f"unknown output mode {mode!r}; expected one of: "
            + ", ".join(sorted(_MODE_BUDGETS))
        )
    budget = _MODE_BUDGETS[normalized] if max_tokens is None else int(max_tokens)
    if budget <= 0:
        raise ValueError("max_tokens must be positive")
    return normalized, budget


def build_output_policy(mode: str = "normal", max_tokens: int | None = None) -> OutputPolicy:
    """Return instructions meant to be injected before response generation."""
    normalized, budget = _resolve_budget(mode, max_tokens)
    detail = {
        "terse": "Prefer a compact status/result. Omit explanation unless it changes the decision.",
        "normal": "Include only the reasoning needed to understand the result and important tradeoffs.",
        "detailed": "Detailed explanation is allowed, but avoid repetition and unchanged code.",
    }[normalized]
    instructions = "\n".join([
        f"OUTPUT BUDGET: target <= {budget} tokens.",
        detail,
        "Do not restate the task or narrate tool calls.",
        "Do not repeat logs, test output, repository context, or facts already present in structured state.",
        "For code changes, prefer file/symbol references or a minimal patch over reproducing complete unchanged files.",
        "Summarize validation as compact facts (for example: tests: 42 passed, 0 failed).",
        "Use structured fields between agents instead of prose when the receiver is another machine.",
        "Stop once the acceptance criteria are satisfied; do not add offers, retrospectives, or next-step filler.",
        "Never omit an error, failed validation, safety issue, or material caveat merely to satisfy the token target.",
    ])
    return OutputPolicy(normalized, budget, instructions)


def _is_filler(paragraph: str) -> bool:
    normalized = " ".join(paragraph.strip().lower().split())
    if not normalized:
        return True
    if normalized in _FILLER:
        return True
    return len(normalized) <= 100 and any(normalized.startswith(p) for p in _FILLER_PREFIXES)


def _compact_prose(block: str, seen: set[str]) -> tuple[str, int]:
    removed = 0
    paragraphs = re.split(r"\n\s*\n", block)
    kept: list[str] = []
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph or _is_filler(paragraph):
            removed += 1
            continue

        # Collapse exact consecutive duplicate lines, a common tool/status echo.
        lines: list[str] = []
        previous: str | None = None
        for line in paragraph.splitlines():
            current = line.rstrip()
            if current.strip() and current.strip() == (previous or "").strip():
                removed += 1
                continue
            lines.append(current)
            previous = current
        paragraph = "\n".join(lines).strip()
        key = " ".join(paragraph.split())
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        kept.append(paragraph)
    return "\n\n".join(kept), removed


def _blocks(text: str) -> list[tuple[bool, str]]:
    """Split text into (is_code_fence, content) while preserving fence bytes."""
    out: list[tuple[bool, str]] = []
    pos = 0
    for match in _FENCE_RE.finditer(text):
        if match.start() > pos:
            out.append((False, text[pos:match.start()]))
        out.append((True, match.group(0)))
        pos = match.end()
    if pos < len(text):
        out.append((False, text[pos:]))
    return out


def _trim_prose(block: str, token_budget: int) -> tuple[str, bool]:
    """Line/sentence bounded prose trimming. Never called for code blocks."""
    if token_budget <= 0:
        return "", bool(block.strip())
    if estimate_tokens(block) <= token_budget:
        return block.strip(), False

    kept: list[str] = []
    truncated = False
    for paragraph in re.split(r"\n\s*\n", block):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        # Keep list/header lines atomically; prose paragraphs may be sentence-bounded.
        units = [paragraph]
        if "\n" not in paragraph and not paragraph.startswith(("#", "-", "*", ">")):
            units = [u.strip() for u in _SENTENCE_RE.split(paragraph) if u.strip()]
        for unit in units:
            candidate = ("\n\n".join(kept + [unit])).strip()
            if estimate_tokens(candidate) > token_budget:
                truncated = True
                break
            kept.append(unit)
        if truncated:
            break
    result = "\n\n".join(kept).strip()
    if truncated and result:
        ellipsis = "\n\n…"
        if estimate_tokens(result + ellipsis) <= token_budget:
            result += ellipsis
    return result, truncated


def compact_output(
    text: str,
    *,
    mode: str = "normal",
    max_tokens: int | None = None,
    enforce_budget: bool = False,
) -> OutputSaveResult:
    """Compact response prose while preserving fenced code/diffs byte-for-byte.

    Safe compaction (deduplication + filler removal) always runs. Token-budget
    trimming is opt-in because dropping prose is lossy. Even when enabled, code
    fences are never trimmed.
    """
    normalized, budget = _resolve_budget(mode, max_tokens)
    original_tokens = estimate_tokens(text)
    seen: set[str] = set()
    removed = 0
    compacted: list[tuple[bool, str]] = []

    for is_code, block in _blocks(text):
        if is_code:
            compacted.append((True, block.strip("\n")))
            continue
        prose, count = _compact_prose(block, seen)
        removed += count
        if prose:
            compacted.append((False, prose))

    if enforce_budget:
        code_tokens = sum(estimate_tokens(block) for is_code, block in compacted if is_code)
        prose_budget = max(0, budget - code_tokens)
        prose_blocks = [block for is_code, block in compacted if not is_code]
        weights = [max(1, estimate_tokens(block)) for block in prose_blocks]
        total_weight = sum(weights) or 1
        trimmed_blocks: list[tuple[bool, str]] = []
        prose_index = 0
        remaining_prose = prose_budget

        for is_code, block in compacted:
            if is_code:
                trimmed_blocks.append((True, block))
                continue
            weight = weights[prose_index]
            prose_index += 1
            later_weight = sum(weights[prose_index:])
            if later_weight:
                allocation = max(1, min(remaining_prose, prose_budget * weight // total_weight))
            else:
                allocation = remaining_prose
            trimmed, was_trimmed = _trim_prose(block, allocation)
            if was_trimmed:
                removed += 1
            if trimmed:
                trimmed_blocks.append((False, trimmed))
                remaining_prose = max(0, remaining_prose - estimate_tokens(trimmed))
        compacted = trimmed_blocks

    result_text = "\n\n".join(block for _, block in compacted if block).strip()
    output_tokens = estimate_tokens(result_text)
    code_preserved = all(
        block in result_text for is_code, block in _blocks(text) if is_code
    )
    return OutputSaveResult(
        text=result_text,
        mode=normalized,
        budget_tokens=budget,
        original_tokens=original_tokens,
        output_tokens=output_tokens,
        removed_units=removed,
        budget_exceeded=output_tokens > budget,
        code_preserved=code_preserved,
    )


def compact_structured_result(value: object) -> str:
    """Serialize agent-to-agent state without pretty-print whitespace."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
