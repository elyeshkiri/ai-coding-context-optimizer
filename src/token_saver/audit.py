"""Measure what a project loads into context on *every* turn.

The always-on slice is the one that matters most: it is multiplied by every
request in the session. This module finds the files Claude Code actually loads
at launch, measures them, and separates them from the parts that load on demand.

Load rules implemented here follow Claude Code's documented behaviour:

* `./CLAUDE.md`, `./.claude/CLAUDE.md` and `./CLAUDE.local.md` load at launch,
  as do the same files in every directory *above* the working directory.
* `~/.claude/CLAUDE.md` (user scope) loads at launch.
* `@path` imports inside those files are expanded at launch, up to 4 hops.
* `.claude/rules/**/*.md` loads at launch **unless** it has `paths:` frontmatter,
  in which case it loads only when a matching file is read.
* Skills load on demand; only their frontmatter is needed for discovery.
* Block-level HTML comments are stripped before injection, so they cost nothing.
* Auto memory loads the first 200 lines / 25KB of `MEMORY.md`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .estimate import Counter

MAX_IMPORT_DEPTH = 4
MEMORY_MAX_LINES = 200
MEMORY_MAX_BYTES = 25_000
CLAUDE_MD_TARGET_LINES = 200

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_FENCE = re.compile(r"```.*?```|~~~.*?~~~", re.S)
_CODE_SPAN = re.compile(r"`[^`\n]*`")
_IMPORT = re.compile(r"(?<![\w`])@([~\w./-]+)")
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)


@dataclass
class Item:
    path: str
    kind: str          # claude_md | import | rule | memory | skill | mcp
    tokens: int
    always_on: bool
    note: str = ""


@dataclass
class Report:
    items: list[Item] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    window: int = 200_000
    counter_label: str = "≈est"

    @property
    def always_on(self) -> int:
        return sum(i.tokens for i in self.items if i.always_on)

    @property
    def on_demand(self) -> int:
        return sum(i.tokens for i in self.items if not i.always_on)


def strip_noncounting(text: str) -> str:
    """Remove what Claude Code drops before injecting a memory file."""
    return _HTML_COMMENT.sub("", text)


def parse_frontmatter(text: str) -> dict:
    m = _FRONTMATTER.match(text)
    if not m:
        return {}
    block = m.group(1)
    data: dict = {}
    key = None
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.match(r"^\s*-\s+", line) and key:
            data.setdefault(key, []).append(line.split("-", 1)[1].strip().strip("\"'"))
        elif ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip("\"'")
            data[key] = value if value else []
    return data


def find_imports(text: str) -> list[str]:
    """`@path` imports, skipping code spans and fenced blocks as Claude Code does."""
    cleaned = _CODE_SPAN.sub(" ", _FENCE.sub(" ", text))
    out = []
    for raw in _IMPORT.findall(cleaned):
        if raw.endswith((".", ",")):
            raw = raw[:-1]
        if "/" in raw or raw.endswith(".md") or raw.startswith("~"):
            out.append(raw)
    return out


def _add_file(
    report: Report, counter: Counter, path: Path, kind: str, always_on: bool,
    root: Path, note: str = "", depth: int = 0, seen: set | None = None,
) -> None:
    seen = seen if seen is not None else set()
    resolved = path.resolve()
    if resolved in seen or not path.is_file():
        return
    seen.add(resolved)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    counted = strip_noncounting(text)
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = str(path)
    lines = len(text.splitlines())
    if kind == "claude_md" and lines > CLAUDE_MD_TARGET_LINES:
        note = note or f"{lines} lines — over the 200-line guidance"
    report.items.append(Item(rel, kind, counter.count(counted, path.suffix), always_on, note))

    if depth < MAX_IMPORT_DEPTH:
        for target in find_imports(counted):
            child = (
                Path(target).expanduser()
                if target.startswith("~")
                else (path.parent / target)
            )
            if not child.exists() and not str(child).endswith(".md"):
                child = child.with_suffix(".md")
            _add_file(
                report, counter, child, "import", always_on, root,
                note=f"imported by {rel}", depth=depth + 1, seen=seen,
            )


def audit(root: Path, counter: Counter | None = None, window: int = 200_000,
          user_scope: bool = True) -> Report:
    root = root.resolve()
    counter = counter or Counter()
    report = Report(window=window, counter_label=counter.label)

    # user scope
    if user_scope:
        home = Path.home() / ".claude"
        _add_file(report, counter, home / "CLAUDE.md", "claude_md", True, root,
                  note="user scope (~/.claude)")
        for rule in sorted((home / "rules").rglob("*.md")) if (home / "rules").is_dir() else []:
            _scan_rule(report, counter, rule, root, "user rule")
        _scan_skills(report, counter, home / "skills", root, "user scope")

    # project + ancestors
    for directory in [root, *root.parents]:
        for name in ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md"):
            candidate = directory / name
            if candidate.is_file():
                note = "" if directory == root else f"inherited from {directory}"
                _add_file(report, counter, candidate, "claude_md", True, root, note=note)
        if (directory / ".git").exists():
            break

    for rule in sorted((root / ".claude" / "rules").rglob("*.md")) \
            if (root / ".claude" / "rules").is_dir() else []:
        _scan_rule(report, counter, rule, root, "")

    _scan_skills(report, counter, root / ".claude" / "skills", root, "")

    # auto memory index
    memory = Path.home() / ".claude" / "projects"
    for index in sorted(memory.glob(f"*{root.name}*/memory/MEMORY.md")):
        text = index.read_text(encoding="utf-8", errors="replace")
        head = "\n".join(text.splitlines()[:MEMORY_MAX_LINES])[:MEMORY_MAX_BYTES]
        report.items.append(
            Item(str(index), "memory", counter.count(head, ".md"), True,
                 "auto memory index (first 200 lines / 25KB)")
        )

    for config in (root / ".mcp.json", root / ".claude" / "mcp.json"):
        if config.is_file():
            try:
                data = json.loads(config.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            report.mcp_servers.extend(sorted(data.get("mcpServers", {})))

    return report


def _scan_rule(report: Report, counter: Counter, rule: Path, root: Path, prefix: str) -> None:
    try:
        text = rule.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    meta = parse_frontmatter(text)
    scoped = bool(meta.get("paths"))
    try:
        rel = str(rule.relative_to(root))
    except ValueError:
        rel = str(rule)
    note = "path-scoped — loads only on matching files" if scoped else "no paths: — always on"
    if prefix:
        note = f"{prefix}; {note}"
    report.items.append(
        Item(rel, "rule", counter.count(strip_noncounting(text), ".md"), not scoped, note)
    )


def _scan_skills(report: Report, counter: Counter, skills_dir: Path, root: Path,
                 prefix: str) -> None:
    """A skill's body loads on demand; its frontmatter is read for discovery."""
    if not skills_dir.is_dir():
        return
    for skill in sorted(skills_dir.glob("*/SKILL.md")):
        try:
            text = skill.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta = parse_frontmatter(text)
        head = f"{meta.get('name', '')} {meta.get('description', '')}".strip()
        try:
            rel = str(skill.relative_to(root))
        except ValueError:
            rel = str(skill)
        discovery = "frontmatter only (discovery)"
        body = "body loads on demand"
        if prefix:
            discovery = f"{prefix}; {discovery}"
            body = f"{prefix}; {body}"
        report.items.append(Item(rel, "skill", counter.count(head), True, discovery))
        report.items.append(Item(rel, "skill", counter.count(text, ".md"), False, body))
