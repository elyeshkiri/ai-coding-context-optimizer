"""Task-aware context packing for coding agents.

The packer spends a fixed token budget on the source most relevant to a task.
It is intentionally local and deterministic: no embeddings, network calls, or
LLM summarisation are required. Exact source windows are emitted for matches so
an agent can reason about/edit code without first ingesting whole files.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import math
import re
import subprocess
from pathlib import Path

from .estimate import estimate_tokens
from .skeleton import file_priority, skeletonize, walk_repo

_WORD = re.compile(r"[A-Za-z0-9_$]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "code", "do",
    "for", "from", "how", "i", "if", "in", "into", "is", "it", "me", "of",
    "on", "or", "our", "please", "project", "the", "this", "to", "use", "we",
    "with", "you", "your", "fix", "implement", "add", "build", "create",
}
_MAX_FILE_BYTES = 2_000_000
_DEFAULT_MAX_FILES = 12
_DEFAULT_CONTEXT_LINES = 6


@dataclass
class RankedFile:
    path: Path
    rel: str
    text: str
    outline: str
    score: float
    reasons: list[str] = field(default_factory=list)
    term_hits: int = 0
    changed: bool = False


@dataclass
class ContextPack:
    text: str
    estimated_tokens: int
    scanned_files: int
    selected_files: list[str]
    ranked: list[RankedFile]


def _terms(text: str) -> list[str]:
    """Tokenise prose, paths and identifiers into stable search terms."""
    expanded = _CAMEL.sub(" ", text.replace("_", " ").replace("-", " ").replace("/", " "))
    out: list[str] = []
    for match in _WORD.finditer(expanded):
        term = match.group(0).lower().strip("_$")
        if len(term) < 2 or term in _STOP:
            continue
        out.append(term)
    return out


def _changed_files(root: Path) -> set[str]:
    """Return working-tree/staged paths when git is available."""
    commands = (
        ["git", "-C", str(root), "diff", "--name-only", "--relative", "HEAD"],
        ["git", "-C", str(root), "diff", "--name-only", "--relative", "--cached"],
    )
    changed: set[str] = set()
    for command in commands:
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode != 0:
            continue
        changed.update(line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip())
    return changed


def _read_source(path: Path) -> str | None:
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _document_terms(text: str, outline: str, rel: str) -> Counter[str]:
    # Full source gets one vote, structural API gets two, path gets three. This
    # keeps identifier/path matches ahead of incidental comments/log strings.
    counts = Counter(_terms(text))
    counts.update(_terms(outline))
    counts.update(_terms(outline))
    for term in _terms(rel):
        counts[term] += 3
    return counts


def rank_files(
    root: Path,
    query: str,
    *,
    use_gitignore: bool = True,
    changed_boost: bool = True,
) -> list[RankedFile]:
    """Rank repository source files for `query` using BM25 + code-aware boosts."""
    root = root.resolve()
    q_terms = list(dict.fromkeys(_terms(query)))
    changed = _changed_files(root) if changed_boost else set()
    docs: list[tuple[Path, str, str, str, Counter[str]]] = []
    for path in walk_repo(root, use_gitignore=use_gitignore):
        text = _read_source(path)
        if text is None:
            continue
        rel = path.relative_to(root).as_posix()
        outline = skeletonize(text, path.suffix, line_numbers=True)
        docs.append((path, rel, text, outline, _document_terms(text, outline, rel)))

    if not docs:
        return []

    lengths = [sum(counts.values()) for *_, counts in docs]
    avg_len = max(1.0, sum(lengths) / len(lengths))
    doc_freq = Counter({term: sum(1 for *_, counts in docs if term in counts) for term in q_terms})
    query_lower = query.strip().lower()
    ranked: list[RankedFile] = []
    for (path, rel, text, outline, counts), length in zip(docs, lengths):
        score = 0.0
        reasons: list[str] = []
        matched = 0
        for term in q_terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            matched += tf
            df = doc_freq[term]
            idf = math.log(1.0 + (len(docs) - df + 0.5) / (df + 0.5))
            k1, b = 1.5, 0.75
            denom = tf + k1 * (1.0 - b + b * length / avg_len)
            score += idf * (tf * (k1 + 1.0) / denom)

        rel_terms = set(_terms(rel))
        outline_terms = set(_terms(outline))
        path_hits = sum(1 for term in q_terms if term in rel_terms)
        symbol_hits = sum(1 for term in q_terms if term in outline_terms)
        if path_hits:
            score += 2.5 * path_hits
            reasons.append(f"path:{path_hits}")
        if symbol_hits:
            score += 1.25 * symbol_hits
            reasons.append(f"symbols:{symbol_hits}")
        if query_lower and len(query_lower) >= 4 and query_lower in text.lower():
            score += 5.0
            reasons.append("exact phrase")

        # Entry points/public source stay useful under vague prompts, but never
        # overpower a concrete lexical match.
        priority = file_priority(rel)
        score += max(0.0, 1.2 - 0.3 * priority)
        if rel in changed:
            score += 4.0
            reasons.append("changed")
        if matched:
            reasons.insert(0, f"term-hits:{matched}")

        ranked.append(
            RankedFile(
                path=path,
                rel=rel,
                text=text,
                outline=outline,
                score=score,
                reasons=reasons or [f"priority:{priority}"],
                term_hits=matched,
                changed=rel in changed,
            )
        )

    ranked.sort(key=lambda item: (-item.score, file_priority(item.rel), item.rel))
    return ranked


def _hit_lines(text: str, query_terms: set[str]) -> list[tuple[int, int]]:
    hits: list[tuple[int, int]] = []
    if not query_terms:
        return hits
    for number, line in enumerate(text.splitlines(), start=1):
        line_terms = set(_terms(line))
        overlap = len(query_terms & line_terms)
        if overlap:
            hits.append((number, overlap))
    hits.sort(key=lambda pair: (-pair[1], pair[0]))
    return hits


def _merge_windows(lines: list[int], total: int, radius: int) -> list[tuple[int, int]]:
    windows = sorted((max(1, n - radius), min(total, n + radius)) for n in lines)
    merged: list[tuple[int, int]] = []
    for start, end in windows:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _source_window(text: str, start: int, end: int) -> str:
    lines = text.splitlines()
    width = len(str(end))
    body = [f"{n:>{width}}|{lines[n - 1]}" for n in range(start, end + 1)]
    return f"#### lines {start}-{end}\n```\n" + "\n".join(body) + "\n```\n"


def _file_section(item: RankedFile, query_terms: set[str], context_lines: int) -> str:
    lines = item.text.splitlines()
    hit_lines = _hit_lines(item.text, query_terms)
    # Prefer a few high-signal windows. More can be added later if budget remains.
    top_numbers = [n for n, _ in hit_lines[:4]]
    windows = _merge_windows(top_numbers, len(lines), max(0, context_lines))
    pieces = [
        f"## {item.rel}",
        f"# relevance={item.score:.2f} ({', '.join(item.reasons)})",
        "### outline",
        item.outline.rstrip(),
    ]
    if windows:
        pieces.append("### exact source windows")
        pieces.extend(_source_window(item.text, start, end).rstrip() for start, end in windows)
    return "\n".join(pieces).rstrip() + "\n"


def _fingerprint(section: str) -> str:
    normal = re.sub(r"\s+", " ", section).strip().encode("utf-8", "replace")
    return hashlib.sha256(normal).hexdigest()


def _fit_section(section: str, budget: int) -> str:
    """Fit on line boundaries. Never return text estimated above `budget`."""
    if budget <= 0:
        return ""
    if estimate_tokens(section) <= budget:
        return section
    lines = section.splitlines(keepends=True)
    lo, hi = 0, len(lines)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = "".join(lines[:mid])
        if estimate_tokens(candidate) <= budget:
            lo = mid
        else:
            hi = mid - 1
    if lo <= 2:
        return ""
    out = "".join(lines[:lo]).rstrip() + "\n# … section clipped to token budget\n"
    while out and estimate_tokens(out) > budget:
        lo -= 1
        if lo <= 2:
            return ""
        out = "".join(lines[:lo]).rstrip() + "\n# … section clipped to token budget\n"
    return out


def build_context_pack(
    root: Path,
    query: str,
    *,
    max_tokens: int = 6000,
    max_files: int = _DEFAULT_MAX_FILES,
    context_lines: int = _DEFAULT_CONTEXT_LINES,
    use_gitignore: bool = True,
    changed_boost: bool = True,
) -> ContextPack:
    """Create a relevance-ranked, deduplicated context pack under a hard cap."""
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if max_files <= 0:
        raise ValueError("max_files must be positive")
    root = root.resolve()
    ranked = rank_files(root, query, use_gitignore=use_gitignore, changed_boost=changed_boost)
    q_terms = set(_terms(query))
    header = (
        f"# TOKEN-SAVER CONTEXT PACK: {root.name}\n"
        f"# task: {query.strip() or '(no query; structural priority mode)'}\n"
        f"# budget: {max_tokens} tokens; exact source windows preserve editable bytes\n"
        f"# scanned: {len(ranked)} source files\n\n"
    )
    if estimate_tokens(header) >= max_tokens:
        fitted = _fit_section(header, max_tokens)
        return ContextPack(fitted, estimate_tokens(fitted), len(ranked), [], ranked)

    blocks = [header]
    selected: list[str] = []
    seen: set[str] = set()
    used = estimate_tokens(header)

    # Concrete matches first. For an empty/vague query all files still have a
    # small structural score and fall back to source priority.
    candidates = [item for item in ranked if item.term_hits or item.changed] or ranked
    for item in candidates:
        if len(selected) >= max_files:
            break
        remaining = max_tokens - used
        if remaining <= 20:
            break
        section = _file_section(item, q_terms, context_lines)
        fingerprint = _fingerprint(section)
        if fingerprint in seen:
            continue
        fitted = _fit_section(section, remaining)
        if not fitted:
            continue
        blocks.append(fitted)
        selected.append(item.rel)
        seen.add(fingerprint)
        used += estimate_tokens(fitted)

    text = "\n".join(block.rstrip() for block in blocks if block).rstrip() + "\n"
    # Defensive final cap in case heuristic token counting changed between calls.
    if estimate_tokens(text) > max_tokens:
        text = _fit_section(text, max_tokens)
    return ContextPack(
        text=text,
        estimated_tokens=estimate_tokens(text),
        scanned_files=len(ranked),
        selected_files=selected,
        ranked=ranked,
    )
