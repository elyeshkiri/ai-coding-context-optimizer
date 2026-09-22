"""Focused browser-context compression for captured HTML or AX-like text."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import re

from .estimate import estimate_tokens
from .recovery import RecoveryCapacityError, RecoveryStore

_INTERACTIVE = {
    "a", "button", "input", "select", "option", "textarea",
    "form", "label", "summary",
}
_NOISE = {"script", "style", "noscript", "svg", "path", "meta", "link"}
_WORD = re.compile(r"[A-Za-z0-9_./:@-]{2,}")


@dataclass(frozen=True)
class BrowserContextResult:
    """Describe one focused browser-payload transform."""

    text: str
    changed: bool
    original_tokens: int
    output_tokens: int
    recovery_handle: str | None
    matched_terms: tuple[str, ...]

    def to_dict(self) -> dict:
        """Return a JSON-safe result."""
        return {
            "text": self.text,
            "changed": self.changed,
            "original_tokens": self.original_tokens,
            "output_tokens": self.output_tokens,
            "recovery_handle": self.recovery_handle,
            "matched_terms": list(self.matched_terms),
        }


class _FocusedHTML(HTMLParser):
    """Extract compact human-visible and interactive lines from HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._stack: list[str] = []
        self._skip = 0
        self.lines: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        """Record interactive controls and enter noise suppression."""
        lowered = tag.lower()
        self._stack.append(lowered)
        if lowered in _NOISE:
            self._skip += 1
            return
        if lowered not in _INTERACTIVE:
            return
        useful = []
        for key, value in attrs:
            if key in {"id", "name", "type", "role", "href", "value", "placeholder", "aria-label"}:
                rendered = key if value is None else f"{key}={value!r}"
                useful.append(rendered)
        suffix = (" " + " ".join(useful)) if useful else ""
        self.lines.append(f"<{lowered}{suffix}>")

    def handle_endtag(self, tag: str) -> None:
        """Leave noise suppression and keep the parser stack bounded."""
        lowered = tag.lower()
        if lowered in _NOISE and self._skip:
            self._skip -= 1
        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        """Keep normalized visible text outside script/style noise."""
        if self._skip:
            return
        text = " ".join(data.split())
        if text:
            self.lines.append(text)


def _terms(query: str) -> set[str]:
    """Return normalized focus terms."""
    return {match.group(0).lower() for match in _WORD.finditer(query)}


def _focused_lines(lines: list[str], query: str, max_lines: int) -> tuple[list[str], tuple[str, ...]]:
    """Select matching lines plus local context and interactive anchors."""
    if max_lines <= 0:
        raise ValueError("browser max_lines must be positive")
    query_terms = _terms(query)
    if not query_terms:
        return lines[:max_lines], ()

    selected: set[int] = set()
    matched: set[str] = set()
    for index, line in enumerate(lines):
        lowered = line.lower()
        hits = {term for term in query_terms if term in lowered}
        if not hits:
            continue
        matched.update(hits)
        for candidate in range(max(0, index - 1), min(len(lines), index + 2)):
            selected.add(candidate)

    # Preserve a small interactive skeleton so focused text still has actionable context.
    for index, line in enumerate(lines):
        if line.startswith("<") and any(line.startswith(f"<{tag}") for tag in _INTERACTIVE):
            selected.add(index)
            if len(selected) >= max_lines:
                break

    ordered = [lines[index] for index in sorted(selected)]
    if not ordered:
        ordered = lines[:max_lines]
    return ordered[:max_lines], tuple(sorted(matched))


def compress_browser_payload(
    text: str,
    *,
    query: str = "",
    max_lines: int = 120,
    recovery: RecoveryStore | None = None,
) -> BrowserContextResult:
    """Compress captured browser context without performing network access."""
    original_tokens = estimate_tokens(text)
    looks_html = bool(re.search(r"<(?:html|body|div|table|form|button|a)\b", text, re.I))
    if looks_html:
        parser = _FocusedHTML()
        try:
            parser.feed(text)
            lines = parser.lines
        except Exception:
            lines = text.splitlines()
    else:
        lines = [line.strip() for line in text.splitlines() if line.strip()]

    selected, matched = _focused_lines(lines, query, max_lines)
    body = "\n".join(selected).strip()
    if len(lines) > len(selected):
        body += f"\n[... {len(lines) - len(selected)} browser lines omitted]"
    output_tokens = estimate_tokens(body)
    changed = bool(body) and len(body.encode()) < len(text.encode()) and output_tokens < original_tokens
    if not changed:
        return BrowserContextResult(
            text=text,
            changed=False,
            original_tokens=original_tokens,
            output_tokens=original_tokens,
            recovery_handle=None,
            matched_terms=matched,
        )

    handle = None
    if recovery is not None:
        try:
            handle = recovery.put(
                text,
                content_type="text/html" if looks_html else "text/plain",
                metadata={
                    "transform": "browser-context",
                    "query_terms": list(matched),
                },
            )
        except RecoveryCapacityError:
            return BrowserContextResult(
                text=text,
                changed=False,
                original_tokens=original_tokens,
                output_tokens=original_tokens,
                recovery_handle=None,
                matched_terms=matched,
            )
        body += f"\n[token-saver recovery: {handle}]"
        output_tokens = estimate_tokens(body)
        if output_tokens >= original_tokens:
            return BrowserContextResult(
                text=text,
                changed=False,
                original_tokens=original_tokens,
                output_tokens=original_tokens,
                recovery_handle=None,
                matched_terms=matched,
            )
    return BrowserContextResult(
        text=body,
        changed=True,
        original_tokens=original_tokens,
        output_tokens=output_tokens,
        recovery_handle=handle,
        matched_terms=matched,
    )
