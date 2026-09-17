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
from .closure import dependency_closure
from .feedback import load_feedback
from .repo_index import RepositoryIndex, build_index, similarity
from .security import inspect_path, redact_secrets
from .skeleton import file_priority, skeletonize, walk_repo
from .working_set import load_working_set, save_working_set

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
_TERM_ALIASES = {
    "outline": "skeleton",
    "structural": "skeleton",
}


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
    selected_symbols: list[str] = field(default_factory=list)
    redactions: list[str] = field(default_factory=list)
    closure_files: list[str] = field(default_factory=list)


def _terms(text: str) -> list[str]:
    """Tokenise prose, paths and identifiers into stable search terms."""
    expanded = _CAMEL.sub(" ", text.replace("_", " ").replace("-", " ").replace("/", " "))
    out: list[str] = []
    for match in _WORD.finditer(expanded):
        term = match.group(0).lower().strip("_$")
        if len(term) < 2 or term in _STOP:
            continue
        out.append(term)
        alias = _TERM_ALIASES.get(term)
        if alias:
            out.append(alias)
        if term.endswith("ize") and len(term) > 6:
            out.append(term[:-3])
        elif term.endswith("ing") and len(term) > 6:
            stem = term[:-3]
            if len(stem) > 2 and stem[-1] == stem[-2]:
                stem = stem[:-1]
            if stem.endswith("c"):
                stem += "e"
            out.append(stem)
        elif term.endswith("ed") and len(term) > 5:
            stem = term[:-2]
            if stem.endswith(("s", "g", "c", "v")):
                stem += "e"
            out.append(stem)
        elif term.endswith("s") and len(term) > 4:
            out.append(term[:-1])
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
    index: RepositoryIndex | None = None,
    graph_hops: int = 1,
    session: str | None = None,
    embeddings: bool = False,
    feedback_boost: bool = True,
    closure_max_items: int = 20,
) -> list[RankedFile]:
    """Rank repository source files for `query` using BM25 + code-aware boosts."""
    root = root.resolve()
    if graph_hops < 0:
        raise ValueError("graph_hops must be nonnegative")
    index = index or build_index(root, use_gitignore=use_gitignore)
    q_terms = list(dict.fromkeys(_terms(query)))
    changed = _changed_files(root) if changed_boost else set()
    remembered_files, remembered_terms = load_working_set(root, session) if session else (set(), set())
    feedback = load_feedback(root) if feedback_boost else {}
    query_continues = bool(set(q_terms) & remembered_terms)
    docs: list[tuple[Path, str, str, str, Counter[str]]] = []
    for path in walk_repo(root, use_gitignore=use_gitignore):
        if not inspect_path(root, path).allowed:
            continue
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
            score += 8.0 * path_hits
            reasons.append(f"path:{path_hits}")
        if symbol_hits:
            score += 5.0 * symbol_hits
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
        if query_continues and rel in remembered_files:
            score += 2.0
            reasons.append("working-set")
        if feedback.get(rel):
            boost = max(-2.0, min(2.0, feedback[rel] * 0.4))
            score += boost
            reasons.append(f"feedback:{feedback[rel]:+d}")
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

    # Graph seeds must be the strongest lexical/changed candidates, independent
    # of filesystem traversal order.
    ranked.sort(key=lambda item: (-item.score, file_priority(item.rel), item.rel))
    by_rel = {item.rel: item for item in ranked}
    seeds = [item.rel for item in ranked if item.term_hits or item.changed][:6]
    for related in dependency_closure(
        index, seeds, max_hops=graph_hops, max_items=closure_max_items,
    ):
        item = by_rel.get(related.path)
        if item is None:
            continue
        item.score += 2.5 * related.confidence
        item.reasons.append(f"graph:{related.reason}@{related.distance}")
        item.reasons.append(
            f"closure:{related.source}@{related.distance}:{related.confidence:.2f}"
        )

    if embeddings:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "embedding reranking requires: pip install 'token-saver[embeddings]'"
            ) from exc
        try:
            model = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)
        except OSError as exc:
            raise RuntimeError(
                "local embedding model all-MiniLM-L6-v2 is not downloaded"
            ) from exc
        descriptions = [f"{item.rel} {' '.join(index.records[item.rel].symbols)} {item.outline}" for item in ranked]
        vectors = model.encode([query] + descriptions, normalize_embeddings=True)
        query_vector = vectors[0]
        for item, vector in zip(ranked, vectors[1:]):
            semantic = float(query_vector @ vector)
            item.score += max(0.0, semantic) * 3.0
            item.reasons.append(f"embedding:{semantic:.2f}")

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


def _merge_ranges(windows: list[tuple[int, int]], total: int) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted((max(1, a), min(total, b)) for a, b in windows):
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


def _symbol_windows(
    item: RankedFile, index: RepositoryIndex, query_terms: set[str], target_symbol: str | None,
) -> tuple[list[tuple[int, int]], list[str]]:
    record = index.records.get(item.rel)
    if record is None:
        return [], []
    wanted = (target_symbol or "").lower()
    matches: list[tuple[int, object]] = []
    source_lines = item.text.splitlines()
    for symbol in record.definitions or []:
        name_terms = set(_terms(symbol.name + " " + symbol.signature))
        body = "\n".join(source_lines[max(0, symbol.start_line - 1):symbol.end_line])
        body_terms = set(_terms(body))
        exact = bool(wanted and symbol.name.lower() == wanted)
        partial = bool(wanted and wanted in symbol.name.lower())
        score = (100 if exact else 50 if partial else 0)
        if not wanted:
            score = 20 * len(query_terms & name_terms) + len(query_terms & body_terms)
        if score:
            matches.append((score, symbol))
    matches.sort(key=lambda pair: (-pair[0], pair[1].start_line, pair[1].name))
    selected = [symbol for _, symbol in matches[:2]]
    windows = [(max(1, symbol.start_line - 1), symbol.end_line + 1) for symbol in selected]
    labels = [f"{item.rel}:{symbol.name}@{symbol.start_line}" for symbol in selected]
    return windows, labels


def _file_section(
    item: RankedFile, query_terms: set[str], context_lines: int,
    index: RepositoryIndex, target_symbol: str | None = None,
) -> tuple[str, list[str], list[str]]:
    lines = item.text.splitlines()
    symbol_windows, symbol_labels = _symbol_windows(item, index, query_terms, target_symbol)
    hit_lines = _hit_lines(item.text, query_terms)
    # Prefer a few high-signal windows. More can be added later if budget remains.
    top_numbers = [n for n, _ in hit_lines[:4]]
    lexical = _merge_windows(top_numbers, len(lines), max(0, context_lines))
    windows = _merge_ranges(symbol_windows + lexical, len(lines))
    pieces = [
        f"## {item.rel}",
        f"# relevance={item.score:.2f} ({', '.join(item.reasons)})",
        "### outline",
        item.outline.rstrip(),
    ]
    if windows:
        pieces.append("### exact source windows")
        pieces.extend(_source_window(item.text, start, end).rstrip() for start, end in windows)
    section, redactions = redact_secrets("\n".join(pieces).rstrip() + "\n")
    return section, symbol_labels, redactions


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
    graph_hops: int = 1,
    duplicate_threshold: float = 0.92,
    session: str | None = None,
    embeddings: bool = False,
    persist_index: bool = True,
    target_symbol: str | None = None,
    feedback_boost: bool = True,
    closure_max_items: int = 20,
    index: RepositoryIndex | None = None,
) -> ContextPack:
    """Create a relevance-ranked, deduplicated context pack under a hard cap."""
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if max_files <= 0:
        raise ValueError("max_files must be positive")
    if not 0.0 <= duplicate_threshold <= 1.0:
        raise ValueError("duplicate_threshold must be between 0 and 1")
    root = root.resolve()
    index = index or build_index(root, use_gitignore=use_gitignore, persist=persist_index)
    effective_query = f"{query} {target_symbol or ''}".strip()
    ranked = rank_files(
        root, effective_query, use_gitignore=use_gitignore, changed_boost=changed_boost,
        index=index, graph_hops=graph_hops, session=session, embeddings=embeddings,
        feedback_boost=feedback_boost,
        closure_max_items=closure_max_items,
    )
    q_terms = set(_terms(effective_query))
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
    selected_records = []
    selected_symbols: list[str] = []
    redactions: set[str] = set()
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
        section, symbols, section_redactions = _file_section(
            item, q_terms, context_lines, index, target_symbol
        )
        fingerprint = _fingerprint(section)
        if fingerprint in seen:
            continue
        record = index.records.get(item.rel)
        if record is not None and any(
            similarity(record, prior) >= duplicate_threshold for prior in selected_records
        ):
            item.reasons.append("near-duplicate-skipped")
            continue
        fitted = _fit_section(section, remaining)
        if not fitted:
            continue
        blocks.append(fitted)
        selected.append(item.rel)
        selected_symbols.extend(symbols)
        redactions.update(section_redactions)
        seen.add(fingerprint)
        if record is not None:
            selected_records.append(record)
        used += estimate_tokens(fitted)

    text = "\n".join(block.rstrip() for block in blocks if block).rstrip() + "\n"
    # Defensive final cap in case heuristic token counting changed between calls.
    if estimate_tokens(text) > max_tokens:
        text = _fit_section(text, max_tokens)
    result = ContextPack(
        text=text,
        estimated_tokens=estimate_tokens(text),
        scanned_files=len(ranked),
        selected_files=selected,
        ranked=ranked,
        selected_symbols=selected_symbols,
        redactions=sorted(redactions),
        closure_files=[
            item.rel for item in ranked
            if any(reason.startswith("closure:") for reason in item.reasons)
        ],
    )
    if session:
        save_working_set(root, session, query, selected)
    return result
