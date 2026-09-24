"""Focused, recoverable optimization for caller-supplied browser payloads."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import json
import re
from typing import Any

from .estimate import estimate_tokens
from .recovery import RecoveryCapacityError, RecoveryStore

_INTERACTIVE_TAGS = {
    "a",
    "button",
    "input",
    "select",
    "option",
    "textarea",
    "form",
    "label",
    "summary",
}
_STRUCTURAL_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "main",
    "nav",
    "dialog",
    "table",
}
_NOISE_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "path",
    "meta",
    "link",
    "template",
}
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_INTERACTIVE_ROLES = {
    "button",
    "link",
    "textbox",
    "searchbox",
    "checkbox",
    "radio",
    "combobox",
    "menuitem",
    "option",
    "tab",
    "treeitem",
    "slider",
    "spinbutton",
}
_STRUCTURAL_ROLES = {
    "heading",
    "alert",
    "dialog",
    "navigation",
    "main",
    "form",
    "table",
    "row",
    "cell",
    "list",
    "listitem",
    "tabpanel",
}
_BROWSER_HINT_KEYS = {
    "accessibility",
    "accessibilitytree",
    "ariasnapshot",
    "snapshot",
    "nodes",
    "domsnapshot",
}
_BROWSER_NODE_KEYS = {
    "role",
    "name",
    "children",
    "nodeid",
    "backendnodeid",
    "aria-label",
}
_WORD = re.compile(r"[A-Za-z0-9_./:@-]{2,}")
_AX_ROLE = re.compile(
    r"(?i)^\s*(?:[-*]\s*)?(?:\[[^\]]+\]\s*)?"
    r"(button|link|textbox|searchbox|checkbox|radio|combobox|menuitem|"
    r"option|tab|treeitem|slider|spinbutton|heading|alert|dialog|navigation|"
    r"main|form|table|row|cell|list|listitem|tabpanel)\b"
)
_HTML_HINT = re.compile(
    r"<(?:html|body|div|table|form|button|a|input|main|nav|dialog|h[1-6])\b",
    re.I,
)
_STATE_KEYS = (
    "value",
    "checked",
    "selected",
    "disabled",
    "expanded",
    "pressed",
    "focused",
    "level",
    "placeholder",
    "href",
    "url",
)


@dataclass(frozen=True)
class BrowserContextResult:
    """Describe one focused browser-payload transform."""

    text: str
    changed: bool
    original_tokens: int
    output_tokens: int
    recovery_handle: str | None
    matched_terms: tuple[str, ...]
    kind: str = "text"
    source_items: int = 0
    shown_items: int = 0
    interactive_items: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe result."""
        return {
            "text": self.text,
            "changed": self.changed,
            "original_tokens": self.original_tokens,
            "output_tokens": self.output_tokens,
            "recovery_handle": self.recovery_handle,
            "matched_terms": list(self.matched_terms),
            "kind": self.kind,
            "source_items": self.source_items,
            "shown_items": self.shown_items,
            "interactive_items": self.interactive_items,
        }


class _FocusedHTML(HTMLParser):
    """Extract compact visible, structural, and actionable lines from HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_stack: list[bool] = []
        self._skip_depth = 0
        self.lines: list[str] = []
        self.interactive: set[int] = set()
        self.structural: set[int] = set()

    def _append(self, line: str, *, interactive: bool = False, structural: bool = False) -> None:
        """Append one normalized non-duplicate line and classify it."""
        normalized = " ".join(line.split())
        if not normalized:
            return
        if self.lines and self.lines[-1] == normalized:
            return
        index = len(self.lines)
        self.lines.append(normalized)
        if interactive:
            self.interactive.add(index)
        if structural:
            self.structural.add(index)

    def handle_starttag(self, tag: str, attrs) -> None:
        """Record useful controls/landmarks while suppressing hidden/noise subtrees."""
        lowered = tag.lower()
        attr_map = {
            str(key).lower(): value
            for key, value in attrs
            if isinstance(key, str)
        }
        style = str(attr_map.get("style") or "").replace(" ", "").lower()
        hidden = (
            lowered in _NOISE_TAGS
            or "hidden" in attr_map
            or str(attr_map.get("aria-hidden") or "").lower() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )
        is_void = lowered in _VOID_TAGS
        if not is_void:
            self._skip_stack.append(hidden)
        if hidden:
            if not is_void:
                self._skip_depth += 1
            return
        if self._skip_depth:
            return

        role = str(attr_map.get("role") or "").lower()
        interactive = lowered in _INTERACTIVE_TAGS or role in _INTERACTIVE_ROLES
        structural = lowered in _STRUCTURAL_TAGS or role in _STRUCTURAL_ROLES
        if not interactive and not structural:
            return

        useful = []
        for key in (
            "id",
            "name",
            "type",
            "role",
            "href",
            "value",
            "placeholder",
            "aria-label",
            "aria-expanded",
            "aria-selected",
            "aria-checked",
            "title",
            "alt",
        ):
            value = attr_map.get(key)
            if value not in (None, ""):
                useful.append(f"{key}={value!r}")
        suffix = (" " + " ".join(useful)) if useful else ""
        self._append(
            f"<{lowered}{suffix}>",
            interactive=interactive,
            structural=structural,
        )

    def handle_startendtag(self, tag: str, attrs) -> None:
        """Handle self-closing tags without disturbing surrounding parser state."""
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        """Leave the most recent hidden/noise subtree."""
        if not self._skip_stack:
            return
        hidden = self._skip_stack.pop()
        if hidden and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        """Keep normalized visible text outside hidden/noise subtrees."""
        if self._skip_depth:
            return
        self._append(data)


def _terms(query: str) -> set[str]:
    """Return normalized focus terms."""
    return {match.group(0).lower() for match in _WORD.finditer(query)}


def _browser_json_score(value: Any, *, limit: int = 240) -> int:
    """Score whether parsed JSON resembles a browser/AX snapshot."""
    score = 0
    visited = 0
    stack = [value]
    while stack and visited < limit:
        item = stack.pop()
        visited += 1
        if isinstance(item, dict):
            lowered = {str(key).lower() for key in item}
            if lowered & _BROWSER_HINT_KEYS:
                score += 3
            if "role" in lowered and ("name" in lowered or "children" in lowered):
                score += 2
            if len(lowered & _BROWSER_NODE_KEYS) >= 3:
                score += 1
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item[:80])
        if score >= 6:
            break
    return score


def looks_like_browser_json(value: Any) -> bool:
    """Return whether parsed JSON has enough browser/AX structure for specialization."""
    return _browser_json_score(value) >= 4


def detect_browser_payload_kind(text: str, *, format_hint: str = "auto") -> str:
    """Classify caller-supplied browser context as html, ax, json, or text."""
    hint = format_hint.strip().lower()
    if hint not in {"auto", "html", "ax", "json", "text"}:
        raise ValueError("browser format must be auto, html, ax, json, or text")
    if hint != "auto":
        return hint
    stripped = text.lstrip()
    if _HTML_HINT.search(text):
        return "html"
    if stripped[:1] in "[{":
        try:
            value = json.loads(stripped)
        except (TypeError, ValueError):
            value = None
        if looks_like_browser_json(value):
            return "json"
    lines = [line for line in text.splitlines() if line.strip()]
    role_lines = sum(bool(_AX_ROLE.search(line)) for line in lines[:160])
    if role_lines >= 3 or (role_lines >= 1 and len(lines) <= 8):
        return "ax"
    return "text"


def _json_node_line(node: dict[str, Any]) -> tuple[str | None, bool, bool]:
    """Render one browser/AX JSON node as a compact semantic line."""
    role = str(node.get("role") or "").strip()
    name = node.get("name")
    if not isinstance(name, str) or not name.strip():
        name = node.get("text")
    if not isinstance(name, str) or not name.strip():
        name = node.get("label")
    name = str(name or "").strip()

    if not role and not name:
        if isinstance(node.get("url"), str):
            return f"page url={node['url']!r}", False, True
        return None, False, False

    prefix = role or "text"
    rendered = f"{prefix} {name!r}" if name else prefix
    states = []
    for key in _STATE_KEYS:
        value = node.get(key)
        if value not in (None, "", False):
            states.append(f"{key}={value!r}")
    if states:
        rendered += " " + " ".join(states)
    normalized_role = role.lower()
    return (
        rendered,
        normalized_role in _INTERACTIVE_ROLES,
        normalized_role in _STRUCTURAL_ROLES,
    )


def _browser_json_lines(value: Any) -> tuple[list[str], set[int], set[int]]:
    """Flatten browser JSON into bounded semantic lines without mutating the source."""
    lines: list[str] = []
    interactive: set[int] = set()
    structural: set[int] = set()
    visited = 0
    stack: list[Any] = [value]
    while stack and visited < 20_000:
        item = stack.pop()
        visited += 1
        if isinstance(item, dict):
            line, is_interactive, is_structural = _json_node_line(item)
            if line and (not lines or lines[-1] != line):
                index = len(lines)
                lines.append(line)
                if is_interactive:
                    interactive.add(index)
                if is_structural:
                    structural.add(index)

            children = item.get("children")
            preferred: list[Any] = []
            if isinstance(children, list):
                preferred.extend(reversed(children))
            for key, nested in reversed(list(item.items())):
                if key == "children":
                    continue
                lowered = str(key).lower()
                if lowered in {
                    "nodes",
                    "snapshot",
                    "accessibility",
                    "accessibilitytree",
                    "ariasnapshot",
                    "domsnapshot",
                } and isinstance(nested, (dict, list)):
                    preferred.append(nested)
            stack.extend(preferred)
        elif isinstance(item, list):
            stack.extend(reversed(item))
    return lines, interactive, structural


def _text_lines(text: str, kind: str) -> tuple[list[str], set[int], set[int]]:
    """Extract normalized lines and classify AX role lines."""
    lines: list[str] = []
    interactive: set[int] = set()
    structural: set[int] = set()
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line or (lines and lines[-1] == line):
            continue
        index = len(lines)
        lines.append(line)
        if kind == "ax":
            match = _AX_ROLE.search(line)
            if match:
                role = match.group(1).lower()
                if role in _INTERACTIVE_ROLES:
                    interactive.add(index)
                if role in _STRUCTURAL_ROLES:
                    structural.add(index)
    return lines, interactive, structural


def _focused_lines(
    lines: list[str],
    query: str,
    max_lines: int,
    *,
    interactive: set[int],
    structural: set[int],
) -> tuple[list[str], tuple[str, ...], int]:
    """Select query neighborhoods, landmarks, controls, and bounded fallback context."""
    if max_lines <= 0:
        raise ValueError("browser max_lines must be positive")
    if not lines:
        return [], (), 0

    query_terms = _terms(query)
    selected: set[int] = set()
    matched: set[str] = set()

    if query_terms:
        for index, line in enumerate(lines):
            lowered = line.lower()
            hits = {term for term in query_terms if term in lowered}
            if not hits:
                continue
            matched.update(hits)
            for candidate in range(max(0, index - 1), min(len(lines), index + 2)):
                selected.add(candidate)

    # Preserve high-value page structure and actionable controls, but do not let
    # a huge navigation/menu skeleton crowd out focused evidence.
    skeleton_budget = max(4, min(max_lines // 3, 24))
    for index in sorted(structural):
        if len(selected) >= max_lines or skeleton_budget <= 0:
            break
        if index not in selected:
            selected.add(index)
            skeleton_budget -= 1
    for index in sorted(interactive):
        if len(selected) >= max_lines or skeleton_budget <= 0:
            break
        if index not in selected:
            selected.add(index)
            skeleton_budget -= 1

    if not query_terms or not matched:
        for index in range(min(len(lines), max_lines)):
            selected.add(index)
            if len(selected) >= max_lines:
                break
    elif len(selected) < max_lines:
        for index in range(min(len(lines), max(6, max_lines // 6))):
            selected.add(index)
            if len(selected) >= max_lines:
                break

    ordered_indices = sorted(selected)[:max_lines]
    shown_interactive = sum(index in interactive for index in ordered_indices)
    return [lines[index] for index in ordered_indices], tuple(sorted(matched)), shown_interactive


def compress_browser_payload(
    text: str,
    *,
    query: str = "",
    max_lines: int = 120,
    recovery: RecoveryStore | None = None,
    format_hint: str = "auto",
    min_tokens: int = 0,
) -> BrowserContextResult:
    """Focus captured browser payloads without performing browser/network access."""
    if min_tokens < 0:
        raise ValueError("browser min_tokens must be nonnegative")
    original_tokens = estimate_tokens(text)
    kind = detect_browser_payload_kind(text, format_hint=format_hint)
    if original_tokens < min_tokens:
        return BrowserContextResult(
            text=text,
            changed=False,
            original_tokens=original_tokens,
            output_tokens=original_tokens,
            recovery_handle=None,
            matched_terms=(),
            kind=kind,
        )

    if kind == "html":
        parser = _FocusedHTML()
        try:
            parser.feed(text)
            lines = parser.lines
            interactive = parser.interactive
            structural = parser.structural
        except Exception:
            lines, interactive, structural = _text_lines(text, "text")
    elif kind == "json":
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            lines, interactive, structural = _text_lines(text, "text")
            kind = "text"
        else:
            lines, interactive, structural = _browser_json_lines(parsed)
    else:
        lines, interactive, structural = _text_lines(text, kind)

    selected, matched, shown_interactive = _focused_lines(
        lines,
        query,
        max_lines,
        interactive=interactive,
        structural=structural,
    )
    body = "\n".join(selected).strip()
    omitted = max(0, len(lines) - len(selected))
    if omitted:
        body += f"\n[... {omitted} browser items omitted]"
    output_tokens = estimate_tokens(body)
    changed = (
        bool(body)
        and len(body.encode()) < len(text.encode())
        and output_tokens < original_tokens
    )
    if not changed:
        return BrowserContextResult(
            text=text,
            changed=False,
            original_tokens=original_tokens,
            output_tokens=original_tokens,
            recovery_handle=None,
            matched_terms=matched,
            kind=kind,
            source_items=len(lines),
            shown_items=len(selected),
            interactive_items=shown_interactive,
        )

    handle = None
    if recovery is not None:
        content_type = (
            "text/html"
            if kind == "html"
            else "application/json"
            if kind == "json"
            else "text/plain"
        )
        try:
            handle = recovery.put(
                text,
                content_type=content_type,
                metadata={
                    "transform": "browser-context",
                    "kind": kind,
                    "query_terms": list(matched),
                    "source_items": len(lines),
                    "shown_items": len(selected),
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
                kind=kind,
                source_items=len(lines),
                shown_items=len(selected),
                interactive_items=shown_interactive,
            )
        body += f"\n[acco recovery: {handle}]"
        output_tokens = estimate_tokens(body)
        if output_tokens >= original_tokens:
            return BrowserContextResult(
                text=text,
                changed=False,
                original_tokens=original_tokens,
                output_tokens=original_tokens,
                recovery_handle=None,
                matched_terms=matched,
                kind=kind,
                source_items=len(lines),
                shown_items=len(selected),
                interactive_items=shown_interactive,
            )
    return BrowserContextResult(
        text=body,
        changed=True,
        original_tokens=original_tokens,
        output_tokens=output_tokens,
        recovery_handle=handle,
        matched_terms=matched,
        kind=kind,
        source_items=len(lines),
        shown_items=len(selected),
        interactive_items=shown_interactive,
    )
