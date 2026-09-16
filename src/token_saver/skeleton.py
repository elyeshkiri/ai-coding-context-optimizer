"""Extract a compact structural map of a repo.

Keeps imports, signatures, class/field names and headings. Drops bodies.

Python is parsed with `ast`, so signatures are exact even when they span
several source lines. Everything else falls back to line patterns.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from pathlib import Path

from .estimate import estimate_tokens
from .ignore import should_skip_dir, should_skip_file

# ---------------------------------------------------------------- patterns

# leading modifiers shared across curly-brace languages
_MODIFIERS = (
    r"(?:export\s+default\s+|export\s+|default\s+|public\s+|private\s+|protected\s+"
    r"|internal\s+|pub(?:\([^)]*\))?\s+|static\s+|abstract\s+|final\s+|sealed\s+"
    r"|open\s+|override\s+|async\s+|unsafe\s+|extern\s+|inline\s+|virtual\s+"
    r"|declare\s+|suspend\s+)*"
)

_DECL_KEYWORDS = (
    r"(?:def|class|fn|func|function|interface|type|enum|struct|impl|trait"
    r"|protocol|record|namespace)"
)

DECL_RE = re.compile(rf"^{_MODIFIERS}{_DECL_KEYWORDS}\b")

# const f = (x) => ..., export const f = async (x) => ...
ARROW_RE = re.compile(
    rf"^{_MODIFIERS}(?:const|let|var)\s+[\w$]+\s*(?::[^=]+?)?=\s*"
    r"(?:async\s+)?(?:\([^)]*\)|[\w$]+)\s*=>"
)

EXPORT_RE = re.compile(r"^(?:export\s|module\.exports\s*=|exports\.[\w$]+\s*=)")

IMPORT_RE = re.compile(
    r"^(?:import|from|package|use|using|require|#include|#import|include"
    r"|extern\s+crate)\b"
)

ATTR_RE = re.compile(r"^(?:@[\w.$]+|#\[[^\]]*\])")

HEADING_RE = re.compile(r"^#{1,6}\s+\S")

CONST_RE = re.compile(r"^[A-Z_][A-Z0-9_]*\s*(?::[^=]+)?=")

# bare method in a class body: `render() {`, `async load(): Promise<X> {`
METHOD_RE = re.compile(
    r"^(?:(?:public|private|protected|static|async|get|set|readonly|override"
    r"|abstract)\s+)*\*?\s*[A-Za-z_$][\w$]*\s*(?:<[^>()]*>)?\s*\([^;{}]*\)\s*"
    r"(?::\s*[^{;]+?)?\s*\{"
)
# ...but these look identical to a method and are not one
METHOD_STOPWORDS = {
    "if", "for", "while", "switch", "catch", "do", "else", "try", "return",
    "with", "when", "using", "match", "unless", "elif",
}

BRACE_LANGS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".java", ".kt", ".cs", ".swift"}
PYTHON_SUFFIXES = {".py", ".pyi"}
MARKDOWN_SUFFIXES = {".md", ".markdown"}

CODE_SUFFIXES = {
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".swift",
    ".rb",
    ".php",
    ".cs",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".md",
}

MAX_VALUE_CHARS = 60
MAX_SIG_CONTINUATION = 20
# `… (1 line omitted)` costs more tokens than the line it replaces
MIN_OMIT_LINES = 2

_EXTRA_FILENAMES = {"Makefile", "Dockerfile", "CLAUDE.md"}


def _omitted(n: int, indent: int = 4) -> str:
    return f"{' ' * indent}… ({n} lines omitted)"


def _numbered(lines: list[str], nums: list[int | None]) -> str:
    """Prefix each emitted line with the source line it came from.

    Costs a few tokens per signature and buys back the ability to ask for an
    exact range instead of re-reading the file, which is the whole point of an
    outline. Omission markers get a blank gutter so the columns still line up.
    """
    width = max((len(str(n)) for n in nums if n), default=1)
    out = []
    for text, num in zip(lines, nums):
        gutter = f"{num:>{width}}|" if num else " " * width + "|"
        out.append(f"{gutter}{text}")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------ python (ast)


def _fmt_value(node: ast.AST) -> str:
    """Render a constant's value, collapsing big literals to a count."""
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        n = len(node.elts)
        text = ast.unparse(node)
        if n > 6 or len(text) > MAX_VALUE_CHARS:
            open_c, close_c = {ast.Set: "{}", ast.List: "[]", ast.Tuple: "()"}[type(node)]
            return f"{open_c}…{n} items{close_c}"
        return text
    if isinstance(node, ast.Dict):
        n = len(node.keys)
        text = ast.unparse(node)
        if n > 6 or len(text) > MAX_VALUE_CHARS:
            return f"{{…{n} keys}}"
        return text
    text = ast.unparse(node)
    if len(text) > MAX_VALUE_CHARS:
        return text[: MAX_VALUE_CHARS - 1] + "…"
    return text


def _node_start(node: ast.AST) -> int:
    """First source line of a node, counting its decorators."""
    decorators = getattr(node, "decorator_list", None)
    if decorators:
        return min(d.lineno for d in decorators)
    return node.lineno


def _is_field(node: ast.AST, *, module_level: bool) -> bool:
    """Module constants and class-level fields are API; locals are not."""
    if isinstance(node, ast.AnnAssign):
        return isinstance(node.target, ast.Name)
    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
        return False
    target = node.targets[0]
    if not isinstance(target, ast.Name):
        return False
    if not module_level:
        return True
    name = target.id
    return name.isupper() or (name.startswith("__") and name.endswith("__"))


def _is_main_guard(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
    )


class _PyEmitter:
    def __init__(self, src_lines: list[str], docstrings: bool) -> None:
        self.out: list[str] = []
        # source line for each entry of `out`; None for omission markers.
        # An outline without these tells you a symbol exists but not where, so
        # the only way to read a body is to re-read the whole file — which
        # spends more than the outline ever saved.
        self.nums: list[int | None] = []
        self.src = src_lines
        self.docstrings = docstrings

    def line(self, indent: int, text: str, lineno: int | None = None) -> None:
        self.out.append(" " * indent + text)
        self.nums.append(lineno)

    def count(self, first: int, last: int) -> int:
        """Non-blank source lines in the inclusive 1-indexed range."""
        lo = max(1, first) - 1
        hi = min(len(self.src), last)
        return sum(1 for ln in self.src[lo:hi] if ln.strip())

    def omit(self, indent: int, n: int) -> None:
        if n >= MIN_OMIT_LINES:
            self.out.append(_omitted(n, indent))
            self.nums.append(None)

    def docstring(self, node: ast.AST, indent: int) -> None:
        if not self.docstrings:
            return
        doc = ast.get_docstring(node, clean=True)
        if not doc:
            return
        first = doc.strip().splitlines()[0].strip()
        if first:
            self.line(indent, f'"""{first[:80]}"""')

    def body(self, body: list[ast.stmt], indent: int, *, module_level: bool) -> None:
        pending = 0
        cursor: int | None = None
        for node in body:
            start = _node_start(node)
            if cursor is not None and start > cursor:
                # comments between nodes count; blank lines do not
                pending += self.count(cursor, start - 1)
            cursor = (node.end_lineno or node.lineno) + 1
            pending = self.node(node, indent, pending, module_level=module_level)
        self.omit(indent, pending)

    def node(self, node: ast.stmt, indent: int, pending: int, *, module_level: bool) -> int:
        """Emit `node` if it is structural. Returns the new pending-omitted count."""
        span = self.count(_node_start(node), node.end_lineno or node.lineno)

        if isinstance(node, (ast.Import, ast.ImportFrom)):
            self.omit(indent, pending)
            self.line(indent, ast.unparse(node), _node_start(node))
            return 0

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.omit(indent, pending)
            for dec in node.decorator_list:
                self.line(indent, f"@{ast.unparse(dec)}", dec.lineno)
            kw = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            sig = f"{kw} {node.name}({ast.unparse(node.args)})"
            if node.returns is not None:
                sig += f" -> {ast.unparse(node.returns)}"
            self.line(indent, sig + ":", node.lineno)
            self.docstring(node, indent + 4)
            body_lines = self.count(node.body[0].lineno, node.end_lineno or node.lineno)
            self.omit(indent + 4, body_lines)
            return 0

        if isinstance(node, ast.ClassDef):
            self.omit(indent, pending)
            for dec in node.decorator_list:
                self.line(indent, f"@{ast.unparse(dec)}", dec.lineno)
            parts = [ast.unparse(b) for b in node.bases]
            parts += [f"{k.arg}={ast.unparse(k.value)}" for k in node.keywords if k.arg]
            head = f"class {node.name}"
            if parts:
                head += "(" + ", ".join(parts) + ")"
            self.line(indent, head + ":", node.lineno)
            self.docstring(node, indent + 4)
            self.body(node.body, indent + 4, module_level=False)
            return 0

        if _is_field(node, module_level=module_level):
            self.omit(indent, pending)
            if isinstance(node, ast.AnnAssign):
                text = f"{ast.unparse(node.target)}: {ast.unparse(node.annotation)}"
                if node.value is not None:
                    text += f" = {_fmt_value(node.value)}"
            else:
                text = f"{ast.unparse(node.targets[0])} = {_fmt_value(node.value)}"
            self.line(indent, text, _node_start(node))
            return 0

        if _is_main_guard(node):
            self.omit(indent, pending)
            self.line(indent, "if __name__ == '__main__':", node.lineno)
            self.omit(indent + 4, span - 1)
            return 0

        return pending + span


def skeletonize_python(
    text: str, docstrings: bool = False, line_numbers: bool = False
) -> str:
    """Exact signatures via the stdlib parser. Raises SyntaxError on bad input."""
    tree = ast.parse(text)
    emitter = _PyEmitter(text.splitlines(), docstrings)
    if docstrings:
        emitter.docstring(tree, 0)
    body = tree.body
    if docstrings and body and isinstance(body[0], ast.Expr) and isinstance(
        getattr(body[0], "value", None), ast.Constant
    ) and isinstance(body[0].value.value, str):
        body = body[1:]
    emitter.body(body, 0, module_level=True)
    if line_numbers:
        return _numbered(emitter.out, emitter.nums)
    return "\n".join(emitter.out) + "\n"


# ----------------------------------------------------------- regex fallback


def _open_brackets(line: str) -> int:
    """Net unclosed ( / [ on a line, ignoring string contents crudely."""
    depth = 0
    quote: str | None = None
    prev = ""
    for ch in line:
        if quote:
            if ch == quote and prev != "\\":
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        prev = ch
    return depth


def line_is_signature(line: str, suffix: str = "") -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if suffix in MARKDOWN_SUFFIXES:
        return bool(HEADING_RE.match(stripped))
    if DECL_RE.match(stripped) or ARROW_RE.match(stripped):
        return True
    if IMPORT_RE.match(stripped) or ATTR_RE.match(stripped):
        return True
    if EXPORT_RE.match(stripped):
        return True
    if suffix in BRACE_LANGS and METHOD_RE.match(stripped):
        first = stripped.split("(", 1)[0].split()[-1].lstrip("*")
        return first not in METHOD_STOPWORDS
    return False


def skeletonize_text(
    text: str, suffix: str = "", line_numbers: bool = False
) -> str:
    """Keep signatures and a tiny hint that a body was omitted."""
    suffix = suffix.lower()
    is_md = suffix in MARKDOWN_SUFFIXES
    lines = text.splitlines()
    out: list[str] = []
    nums: list[int | None] = []
    body_skipped = 0
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if is_md and line.lstrip().startswith(("```", "~~~")):
            # a `# comment` inside a fenced block is not a heading
            in_fence = not in_fence
            body_skipped += 1
            i += 1
            continue
        if in_fence:
            if line.strip():
                body_skipped += 1
            i += 1
            continue
        if line_is_signature(line, suffix):
            if body_skipped >= MIN_OMIT_LINES:
                out.append(_omitted(body_skipped))
                nums.append(None)
            body_skipped = 0
            sig_line = i + 1
            # join continuation lines so multi-line signatures stay readable
            parts = [line.rstrip()]
            depth = _open_brackets(line)
            consumed = 0
            while depth > 0 and i + 1 < len(lines) and consumed < MAX_SIG_CONTINUATION:
                i += 1
                consumed += 1
                nxt = lines[i]
                parts.append(nxt.strip())
                depth += _open_brackets(nxt)
            out.append(" ".join(p for p in parts if p) if consumed else parts[0])
            nums.append(sig_line)
        else:
            stripped = line.strip()
            if not is_md and CONST_RE.match(stripped):
                out.append(line.rstrip())
                nums.append(i + 1)
            elif is_md and stripped.startswith(("---", "===")):
                out.append(line.rstrip())
                nums.append(i + 1)
            elif stripped:
                body_skipped += 1
        i += 1
    if body_skipped >= MIN_OMIT_LINES:
        out.append(_omitted(body_skipped))
        nums.append(None)
    if line_numbers:
        return _numbered(out, nums)
    return "\n".join(out) + "\n"


def skeletonize(
    text: str,
    suffix: str = "",
    docstrings: bool = False,
    line_numbers: bool = False,
) -> str:
    """Dispatch to the parser that fits `suffix`, falling back to patterns."""
    from .syntax import JS_TS, symbols
    if suffix.lower() in JS_TS:
        try:
            items = symbols(text, suffix.lower())
            rows = [(item.start, item.signature) for item in items]
            rows.extend((i, line.strip()) for i, line in enumerate(text.splitlines(), 1)
                        if IMPORT_RE.match(line.strip()) or "require(" in line)
            rows.sort(key=lambda row: row[0])
            if not rows: return text  # no useful navigational structure; preserve content
            lines = [row[1] for row in rows]
            return _numbered(lines, [row[0] for row in rows]) if line_numbers else "\n".join(lines) + "\n"
        except ValueError:
            # Truncated or invalid source must not produce a falsely authoritative map.
            lines = text.splitlines()
            return _numbered(lines, list(range(1, len(lines) + 1))) if line_numbers else text
    if suffix.lower() in PYTHON_SUFFIXES:
        try:
            return skeletonize_python(
                text, docstrings=docstrings, line_numbers=line_numbers
            )
        except (SyntaxError, ValueError, RecursionError):
            pass  # unparseable (py2, template, truncated) — use line patterns
    return skeletonize_text(text, suffix, line_numbers=line_numbers)


# ------------------------------------------------------------------- walk


def _git_tracked(root: Path) -> list[Path] | None:
    """Files git would show you: tracked plus untracked-but-not-ignored.

    Delegating to git is exact — it honours .gitignore, nested ignore files,
    global excludes and .git/info/exclude — and avoids shipping a glob matcher
    that would drift from git's real semantics. Returns None when this is not a
    git repo or git is unavailable.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others",
             "--exclude-standard", "-z"],
            capture_output=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    names = proc.stdout.decode("utf-8", "replace").split("\0")
    return [root / n for n in names if n]


def walk_repo(root: Path, use_gitignore: bool = True) -> list[Path]:
    tracked = _git_tracked(root) if use_gitignore else None
    if tracked is not None:
        return sorted(
            p for p in tracked
            if p.is_file()
            and not should_skip_file(p)
            and not any(should_skip_dir(part) for part in p.relative_to(root).parts[:-1])
            and (p.suffix.lower() in CODE_SUFFIXES or p.name in _EXTRA_FILENAMES)
        )
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
        for name in filenames:
            p = here / name
            if should_skip_file(p):
                continue
            if p.suffix.lower() not in CODE_SUFFIXES and name not in _EXTRA_FILENAMES:
                continue
            files.append(p)
    return sorted(files)


# ------------------------------------------------------------ prioritisation

# lower tier = more likely to survive a tight budget
_LOW_VALUE_DIRS = {
    "tests", "test", "spec", "specs", "__tests__", "examples", "example",
    "docs", "doc", "fixtures", "migrations", "benchmarks", "bench", "scripts",
}
_ENTRY_NAMES = {
    "__init__.py", "__main__.py", "main.py", "app.py", "cli.py", "index.ts",
    "index.js", "index.tsx", "main.go", "main.rs", "lib.rs", "mod.rs",
    "README.md", "CLAUDE.md",
}
_SRC_DIRS = {"src", "lib", "app", "pkg", "internal", "core"}


def file_priority(rel: str) -> int:
    """0 = keep first. Entry points and public API outrank tests and fixtures."""
    parts = rel.split("/")
    name = parts[-1]
    if any(d in _LOW_VALUE_DIRS for d in parts[:-1]):
        return 3
    if name.startswith("test_") or name.endswith(("_test.py", ".test.ts", ".spec.ts")):
        return 3
    if name in _ENTRY_NAMES:
        return 0
    if parts[0] in _SRC_DIRS or (len(parts) > 1 and parts[0] == "."):
        return 1
    return 2


def _rank(rel: str, skel: str) -> tuple:
    """Sort key: tier, then shallower paths, then bigger API surface."""
    symbols = sum(1 for ln in skel.splitlines() if ln.strip() and "omitted" not in ln)
    return (file_priority(rel), rel.count("/"), -symbols, rel)


def _symbol_count(skel: str) -> int:
    return sum(1 for ln in skel.splitlines() if ln.strip() and "omitted" not in ln)


def _summary_line(rel: str, skel: str) -> str:
    return f"- {rel} ({_symbol_count(skel)} symbols)"


def _rollup(listed: list[tuple[str, int]]) -> list[str]:
    """Collapse per-file lines into one line per directory."""
    dirs: dict[str, list[int]] = {}
    for rel, symbols in listed:
        key = rel.rsplit("/", 1)[0] + "/" if "/" in rel else "./"
        bucket = dirs.setdefault(key, [0, 0])
        bucket[0] += 1
        bucket[1] += symbols
    return [
        f"- {d} ({n} files, {sym} symbols)"
        for d, (n, sym) in sorted(dirs.items(), key=lambda kv: -kv[1][1])
    ]


# a fixed-width stand-in so header substitution cannot change the token count
# how many consecutive refill misses before we stop trying to top up the map
_REFILL_MISS_LIMIT = 10

_MAP_SLOT = "#" * 12


def _fit(n: int) -> str:
    """Render `n` no wider than the slot, so substitution cannot grow the map."""
    text = str(n)
    return text if len(text) <= len(_MAP_SLOT) else text[: len(_MAP_SLOT)]


_LISTING_HEADER = (
    "## not expanded (budget)\n"
    "# these exist; ask for one by path when you need its signatures"
)


def build_map(
    root: Path,
    docstrings: bool = False,
    max_tokens: int | None = None,
    use_gitignore: bool = True,
) -> str:
    """Structural map of `root`, hard-capped at `max_tokens` if given.

    Files are ranked by priority; whatever does not fit in full is indexed by
    path (or by directory, if even that does not fit) so the map stays a
    complete picture of the repo even when bodies are dropped.
    """
    root = root.resolve()
    entries: list[tuple[tuple, str, str, int, int]] = []
    raw_tokens = 0
    for path in walk_repo(root, use_gitignore=use_gitignore):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        skel = skeletonize(text, path.suffix, docstrings=docstrings)
        raw_tokens += estimate_tokens(text, path.suffix)
        section = f"## {rel}\n{skel.rstrip()}\n"
        entries.append(
            (_rank(rel, skel), rel, section, estimate_tokens(section, path.suffix),
             _symbol_count(skel))
        )
    entries.sort(key=lambda e: e[0])

    def render(chosen: list[int]) -> tuple[str, int]:
        picked = set(chosen)
        included = [entries[i][2] for i in chosen]
        overflow = [(entries[i][1], entries[i][4])
                    for i in range(len(entries)) if i not in picked]
        blocks = [""]
        blocks.extend(included)
        if overflow:
            lines = [f"- {rel} ({sym} symbols)" for rel, sym in overflow]
            block = _LISTING_HEADER + "\n" + "\n".join(lines)
            cap = max_tokens * 0.15 if max_tokens else None
            if cap and estimate_tokens(block) > cap:
                rolled = _rollup(overflow)
                block = _LISTING_HEADER + "\n" + "\n".join(rolled)
                if estimate_tokens(block) > cap:
                    keep = max(1, int(len(rolled) * cap / max(1, estimate_tokens(block))))
                    block = (
                        _LISTING_HEADER + "\n" + "\n".join(rolled[:keep])
                        + f"\n- …and {len(rolled) - keep} more directories"
                    )
            blocks.append(block)
        header = [
            f"# CODE MAP: {root.name}",
            f"# files={len(entries)} expanded={len(chosen)} listed={len(overflow)}",
            # _MAP_SLOT is replaced by an equal-length string after measuring,
            # so the measurement stays valid for the text we actually return
            f"# raw≈{raw_tokens} map≈{_MAP_SLOT} saved≈{_MAP_SLOT}",
        ]
        if overflow and max_tokens:
            header.append(f"# capped at {max_tokens} tokens")
        blocks[0] = "\n".join(header)
        out = "\n".join(blocks)
        return out, estimate_tokens(out)

    if max_tokens is None:
        chosen = list(range(len(entries)))
    else:
        # pack in priority order, skipping anything that would overflow
        chosen = []
        used = 0
        for i, e in enumerate(entries):
            if used + e[3] <= max_tokens * 0.80:
                chosen.append(i)
                used += e[3]
        # the index block can still push us over: drop the cheapest-value picks
        while chosen and render(chosen)[1] > max_tokens:
            chosen.pop()
        # Then spend whatever the index freed up. Each trial re-renders the
        # whole map, so try the cheapest candidates first and give up after a
        # short run of misses — without this the loop is O(files²) and a
        # 4k-file repo takes seconds instead of milliseconds.
        picked = set(chosen)
        candidates = sorted(
            (i for i in range(len(entries)) if i not in picked),
            # priority tier still wins; cost only breaks ties within a tier, so
            # leftover budget cannot be padded with cheap low-value files
            key=lambda i: (entries[i][0][0], entries[i][3]),
        )
        misses = 0
        for i in candidates:
            if misses >= _REFILL_MISS_LIMIT:
                break
            trial = sorted(chosen + [i])
            if render(trial)[1] <= max_tokens:
                chosen = trial
                misses = 0
            else:
                misses += 1

    text, tokens = render(chosen)
    saved = max(0, raw_tokens - tokens)
    text = text.replace(f"map≈{_MAP_SLOT}", f"map≈{_fit(tokens)}", 1).replace(
        f"saved≈{_MAP_SLOT}", f"saved≈{_fit(saved)}", 1
    )
    # strip the slot padding; removing characters can only keep us under the cap
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"
