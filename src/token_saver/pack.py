"""Task-aware context packing for coding agents.

Ranking operates on the persistent repository index. Source bytes are hydrated
only for files that survive retrieval and are considered for the final context
pack, avoiding a full repository reread on every query.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import math
import re
import subprocess
from pathlib import Path

from .budget import RetrievalPlan, plan_retrieval
from .closure import authoritative_providers, dependency_closure
from .estimate import estimate_tokens
from .feedback import load_feedback
from .lexical import document_counts, symbol_terms, terms
from .repo_index import RepositoryIndex, build_index, similarity
from .security import redact_secrets
from .skeleton import file_priority
from .working_set import load_working_set, save_working_set

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
    selected_symbols: list[str] = field(default_factory=list)
    redactions: list[str] = field(default_factory=list)
    closure_files: list[str] = field(default_factory=list)
    retrieval_plan: dict[str, int] = field(default_factory=dict)


# Kept as private compatibility aliases for callers/tests that imported these
# helpers before retrieval was moved into the persistent index.
def _terms(text: str) -> list[str]:
    return terms(text)


def _document_terms(text: str, outline: str, rel: str) -> Counter[str]:
    return Counter(document_counts(text, outline, rel))


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
        changed.update(
            line.strip().replace("\\", "/")
            for line in proc.stdout.splitlines() if line.strip()
        )
    return changed


def _read_source(path: Path) -> str | None:
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


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
    changed_files: set[str] | None = None,
    priority_files: set[str] | None = None,
    exclude_files: set[str] | None = None,
    restrict_files: set[str] | None = None,
    seed_limit: int = 6,
) -> list[RankedFile]:
    """Rank indexed files for ``query`` using BM25 + code-aware boosts.

    The expensive parse/skeleton/token-frequency work is performed when a file
    enters or changes in the index. Query-time ranking touches only cached
    records; exact source is read later for final context candidates.
    """
    root = root.resolve()
    if graph_hops < 0:
        raise ValueError("graph_hops must be nonnegative")
    if seed_limit <= 0:
        raise ValueError("seed_limit must be positive")
    index = index or build_index(root, use_gitignore=use_gitignore)
    q_terms = list(dict.fromkeys(terms(query)))

    if not changed_boost:
        changed = set()
    elif changed_files is not None:
        changed = changed_files
    else:
        changed = _changed_files(root)

    remembered_files, remembered_terms = (
        load_working_set(root, session) if session else (set(), set())
    )
    feedback = load_feedback(root) if feedback_boost else {}
    query_continues = bool(set(q_terms) & remembered_terms)

    docs: list[tuple[Path, str, str, Counter[str]]] = []
    for rel, record in index.records.items():
        if exclude_files and rel in exclude_files:
            continue
        if restrict_files is not None and rel not in restrict_files:
            continue
        if record.size > _MAX_FILE_BYTES:
            continue
        counts = Counter(record.term_counts or {})
        if not counts:
            counts.update(terms(" ".join(record.tokens)))
            counts.update(terms(record.outline))
            counts.update(terms(record.outline))
            for term in terms(rel):
                counts[term] += 3
        docs.append((root / rel, rel, record.outline, counts))

    if not docs:
        return []

    lengths = [sum(counts.values()) for *_, counts in docs]
    avg_len = max(1.0, sum(lengths) / len(lengths))
    doc_freq = Counter({
        term: sum(1 for *_, counts in docs if term in counts)
        for term in q_terms
    })

    ranked: list[RankedFile] = []
    for (path, rel, outline, counts), length in zip(docs, lengths):
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

        rel_terms = set(terms(rel))
        outline_terms = set(terms(outline))
        path_hits = sum(1 for term in q_terms if term in rel_terms)
        symbol_hits = sum(1 for term in q_terms if term in outline_terms)
        if path_hits:
            score += 8.0 * path_hits
            reasons.append(f"path:{path_hits}")
        if symbol_hits:
            score += 5.0 * symbol_hits
            reasons.append(f"symbols:{symbol_hits}")

        priority = file_priority(rel)
        score += max(0.0, 1.2 - 0.3 * priority)
        if priority == 3:
            # file_priority's flat additive bonus above (max spread 0.9) is
            # dwarfed by BM25 term-overlap scores that routinely run into
            # the tens of points, so it can't meaningfully counteract a
            # test/doc/fixture file that happens to share heavy vocabulary
            # with an implementation query -- a test exercising a feature
            # extensively, or a doc page explaining it in prose, both
            # legitimately overlap a lot without being themselves the right
            # answer to "how does X work." Dampen the whole score instead
            # of adding a fixed amount, so it scales with however large the
            # underlying (possibly very large) score actually is.
            score *= 0.35
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

        ranked.append(RankedFile(
            path=path,
            rel=rel,
            text="",
            outline=outline,
            score=score,
            reasons=reasons or [f"priority:{priority}"],
            term_hits=matched,
            changed=rel in changed,
        ))

    ranked.sort(key=lambda item: (-item.score, file_priority(item.rel), item.rel))
    by_rel = {item.rel: item for item in ranked}
    seed_pool = [item.rel for item in ranked if item.term_hits or item.changed]
    if priority_files:
        seed_pool.sort(key=lambda rel: rel not in priority_files)
    seeds = seed_pool[:seed_limit]
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

    # dependency_closure above is seeded from only the top seed_limit files
    # (deliberately small/cost-bounded, since most of its edge kinds are
    # transitive and can fan out). A source ranked just below that cutoff --
    # e.g. behind several near-duplicate files that outscore it on raw term
    # overlap alone -- would otherwise never get a chance to surface an exact
    # value it imports. Run the cheap, non-transitive semantic-ref lookup over
    # every relevant candidate instead of just the seed set.
    for related in authoritative_providers(index, seed_pool):
        item = by_rel.get(related.path)
        if item is None or any(reason.startswith("graph:") for reason in item.reasons):
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
        descriptions = [
            f"{item.rel} {' '.join(index.records[item.rel].symbols)} {item.outline}"
            for item in ranked
        ]
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
        line_terms = set(terms(line))
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


def _prioritized_ranges(
    primary: list[tuple[int, int]],
    secondary: list[tuple[int, int]],
    total: int,
) -> list[tuple[int, int]]:
    """Deduplicate source windows without destroying relevance order.

    ``primary`` is already ordered by symbol score. Sorting every window by
    source line lets an earlier-but-weaker definition consume a clipped section
    before a later, higher-scoring symbol. Preserve primary order and append
    lexical navigation windows only when they add source not already covered.
    """
    result: list[tuple[int, int]] = []

    def add(window: tuple[int, int]) -> None:
        start, end = max(1, window[0]), min(total, window[1])
        if start > end:
            return
        for idx, (existing_start, existing_end) in enumerate(result):
            if start <= existing_end + 1 and end >= existing_start - 1:
                result[idx] = (min(start, existing_start), max(end, existing_end))
                return
        result.append((start, end))

    for window in primary:
        add(window)
    for window in secondary:
        add(window)
    return result


def _symbol_windows(
    item: RankedFile, index: RepositoryIndex, query_terms: set[str], target_symbol: str | None,
) -> tuple[list[tuple[int, int]], list[str]]:
    record = index.records.get(item.rel)
    if record is None:
        return [], []
    wanted = (target_symbol or "").lower()
    definitions = record.definitions or []
    source_lines = item.text.splitlines()
    # File retrieval stays on the conservative global tokenizer. Once a file
    # has already won retrieval, symbol selection can safely normalize nearby
    # inflections (connection/connect, equality/equal, completion/complete)
    # without perturbing repository-wide ranking.
    symbol_query_terms = set(symbol_terms(" ".join(sorted(query_terms))))

    term_weight: dict[str, float] = {}
    if not wanted and definitions:
        doc_freq: Counter[str] = Counter()
        for symbol in definitions:
            name_terms = set(terms(symbol.name + " " + symbol.signature))
            body = "\n".join(source_lines[max(0, symbol.start_line - 1):symbol.end_line])
            for term in name_terms | set(terms(body)):
                doc_freq[term] += 1
        n = len(definitions)
        term_weight = {term: math.log((n + 1) / (df + 1)) + 1 for term, df in doc_freq.items()}

    matches: list[tuple[float, object]] = []
    for symbol in definitions:
        name_terms = set(terms(symbol.name + " " + symbol.signature))
        body = "\n".join(source_lines[max(0, symbol.start_line - 1):symbol.end_line])
        body_terms = set(terms(body))
        exact = bool(wanted and symbol.name.lower() == wanted)
        partial = bool(wanted and wanted in symbol.name.lower())
        score = 100 if exact else 50 if partial else 0
        if not wanted:
            name_hits = symbol_query_terms & name_terms
            body_hits = symbol_query_terms & body_terms
            score = (
                20 * sum(term_weight.get(t, 1.0) for t in name_hits)
                + sum(term_weight.get(t, 1.0) for t in body_hits)
            )
        if score:
            matches.append((score, symbol))

    if not wanted:
        # A container is any symbol that structurally has at least one
        # other symbol recorded as its child in this file -- not just
        # kind == "class" (Python's ast.ClassDef), which excludes every
        # JS/TS container (tree-sitter extraction tags all JS/TS symbols
        # "symbol" regardless of shape) even though a JS/TS class or a
        # pre-ES6 `X.prototype.method = ...` constructor-function has the
        # exact same "one member outscoring its own container" failure
        # shape as a Python class does.
        container_names = {symbol.parent for symbol in definitions if symbol.parent}
        own_score = {symbol.name: score for score, symbol in matches}
        best_child_score: dict[str, float] = {}
        best_child_symbol: dict[str, object] = {}
        for score, symbol in matches:
            if symbol.parent and symbol.parent in own_score and symbol.parent in container_names:
                if score > best_child_score.get(symbol.parent, 0):
                    best_child_score[symbol.parent] = score
                    best_child_symbol[symbol.parent] = symbol
        boosted = {
            name: score + best_child_score.get(name, 0)
            for name, score in own_score.items()
        }
        matches = [(boosted.get(symbol.name, score), symbol) for score, symbol in matches]
    else:
        best_child_symbol = {}

    matches.sort(key=lambda pair: (-pair[0], pair[1].start_line, pair[1].name))
    selected = [symbol for _, symbol in matches[:2]]
    windows = [(max(1, symbol.start_line - 1), symbol.end_line + 1) for symbol in selected]
    labels = [f"{item.rel}:{symbol.name}@{symbol.start_line}" for symbol in selected]
    for symbol in selected:
        child = best_child_symbol.get(symbol.name)
        if child is None or child in selected:
            continue
        if child.start_line >= symbol.start_line and child.end_line <= symbol.end_line:
            labels.append(f"{item.rel}:{child.name}@{child.start_line}")
    return windows, labels


def _file_section(
    item: RankedFile, query_terms: set[str], context_lines: int,
    index: RepositoryIndex, target_symbol: str | None = None,
) -> tuple[str, list[str], list[str]]:
    lines = item.text.splitlines()
    symbol_windows, symbol_labels = _symbol_windows(item, index, query_terms, target_symbol)
    hit_lines = _hit_lines(item.text, query_terms)
    top_numbers = [n for n, _ in hit_lines[:4]]
    lexical = _merge_windows(top_numbers, len(lines), max(0, context_lines))
    windows = _prioritized_ranges(symbol_windows, lexical, len(lines))
    # Exact implementation evidence is the primary payload. Put it before the
    # navigation outline so a tight per-file budget clips optional structure
    # rather than silently dropping the symbol source that caused the file to
    # be selected in the first place.
    pieces = [f"## {item.rel}"]
    if windows:
        pieces.append("### exact source windows")
        pieces.extend(_source_window(item.text, start, end).rstrip() for start, end in windows)
    pieces.extend([
        f"# relevance={item.score:.2f} ({', '.join(item.reasons)})",
        "### outline",
        item.outline.rstrip(),
    ])
    section, redactions = redact_secrets("\n".join(pieces).rstrip() + "\n")
    return section, symbol_labels, redactions


def _fingerprint(section: str) -> str:
    normal = re.sub(r"\s+", " ", section).strip().encode("utf-8", "replace")
    return hashlib.sha256(normal).hexdigest()


def _visible_symbol_labels(section: str, labels: list[str]) -> list[str]:
    """Keep only labels whose exact source line survived section fitting."""
    marker = "### exact source windows"
    if marker not in section:
        return []
    source = section.split(marker, 1)[1]
    visible: list[str] = []
    for label in labels:
        try:
            line = int(label.rsplit("@", 1)[1])
        except (ValueError, IndexError):
            continue
        if re.search(rf"^\s*{line}\|", source, re.MULTILINE):
            visible.append(label)
    return visible


def _fit_section(section: str, budget: int) -> str:
    """Fit on line boundaries. Never return text estimated above ``budget``."""
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


def _static_plan(
    graph_hops: int, closure_max_items: int, context_lines: int,
) -> RetrievalPlan:
    return RetrievalPlan(
        seed_limit=6,
        graph_hops=graph_hops,
        closure_items=closure_max_items,
        context_lines=context_lines,
    )


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
    changed_files: set[str] | None = None,
    priority_files: set[str] | None = None,
    exclude_files: set[str] | None = None,
    restrict_files: set[str] | None = None,
    adaptive_budget: bool = True,
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
    q_terms = set(terms(effective_query))

    resolved_changed = changed_files
    if changed_boost and resolved_changed is None:
        resolved_changed = _changed_files(root)
    if not changed_boost:
        resolved_changed = set()

    plan = (
        plan_retrieval(
            max_tokens=max_tokens,
            query_terms=len(q_terms),
            changed_count=len(resolved_changed or ()),
            graph_hops=graph_hops,
            closure_items=closure_max_items,
            context_lines=context_lines,
        )
        if adaptive_budget
        else _static_plan(graph_hops, closure_max_items, context_lines)
    )

    ranked = rank_files(
        root, effective_query, use_gitignore=use_gitignore, changed_boost=changed_boost,
        index=index, graph_hops=plan.graph_hops, session=session, embeddings=embeddings,
        feedback_boost=feedback_boost, closure_max_items=plan.closure_items,
        changed_files=resolved_changed, priority_files=priority_files,
        exclude_files=exclude_files, restrict_files=restrict_files,
        seed_limit=plan.seed_limit,
    )
    task_display = query.strip() or "(no query; structural priority mode)"
    if len(task_display) > 300:
        task_display = task_display[:300] + f"… (+{len(task_display) - 300} chars)"
    header = (
        f"# TOKEN-SAVER CONTEXT PACK: {root.name}\n"
        f"# task: {task_display}\n"
        f"# budget: {max_tokens} tokens; exact source windows preserve editable bytes\n"
        f"# scanned: {len(ranked)} source files\n\n"
    )
    if estimate_tokens(header) >= max_tokens:
        fitted = _fit_section(header, max_tokens)
        return ContextPack(
            fitted, estimate_tokens(fitted), len(ranked), [], ranked,
            retrieval_plan=plan.to_dict(),
        )

    blocks = [header]
    selected: list[str] = []
    seen: set[str] = set()
    selected_records = []
    selected_symbols: list[str] = []
    redactions: set[str] = set()
    used = estimate_tokens(header)

    candidates = [item for item in ranked if item.term_hits or item.changed] or ranked
    if priority_files:
        candidates = sorted(candidates, key=lambda item: item.rel not in priority_files)
    priority_total = sum(
        1 for item in candidates if priority_files and item.rel in priority_files
    )
    priority_seen = 0

    # Reserve a bounded slot for the highest-ranked exact one-hop value
    # provider among the candidates. This prevents a huge consumer outline
    # from monopolizing the whole context budget before its provider is
    # considered, without imposing global fair-sharing on ordinary files. Scan
    # every candidate, not just the leading few: a "graph:semantic-ref@1" tag
    # is only ever attached to the small, already-bounded set of files
    # rank_files() actually found via a real one-hop reference (see
    # closure.authoritative_providers), never a large fraction of the repo,
    # so the scan stays cheap regardless of where such a file ranks by raw
    # lexical score -- which, being a tiny provider file, is often low.
    authoritative_rel = next(
        (
            item.rel
            for item in candidates
            if any(reason.startswith("graph:semantic-ref@1") for reason in item.reasons)
        ),
        None,
    )
    authoritative_reserve = (
        min(900, max(240, max_tokens // 8)) if authoritative_rel else 0
    )

    for idx, item in enumerate(candidates):
        if len(selected) >= max_files:
            break
        remaining = max_tokens - used
        if remaining <= 20:
            break
        if priority_files and item.rel in priority_files:
            priority_seen += 1
            slots_left = priority_total - priority_seen + 1
            if slots_left > 1:
                remaining = min(remaining, max(remaining // slots_left, 200))
        elif len(selected) + 1 < max_files and idx + 1 < len(candidates):
            # Cap an ordinary candidate's share of what's left so one large,
            # top-ranked file can't silently consume the whole budget before
            # any other candidate is even considered -- found via the second
            # frozen external holdout: a single oversized test file used
            # 5993 of a 6000-token budget by itself, leaving the correctly
            # ranked #4 implementation file with literally nothing. Only
            # kicks in while more candidates and slots remain to benefit
            # from the reserved room; the true last usable candidate still
            # gets whatever's left rather than wasting it unused.
            remaining = min(remaining, max(remaining * 3 // 5, 300))

        section_budget = remaining
        if (
            authoritative_rel
            and authoritative_rel not in selected
            and item.rel != authoritative_rel
        ):
            section_budget = max(0, remaining - authoritative_reserve)
            if section_budget <= 20:
                continue

        if not item.text:
            item.text = _read_source(item.path) or ""
        if not item.text:
            item.reasons.append("source-unavailable")
            continue

        record = index.records.get(item.rel)
        if record is not None and any(
            similarity(record, prior) >= duplicate_threshold for prior in selected_records
        ):
            item.reasons.append("near-duplicate-skipped")
            continue

        section, symbols, section_redactions = _file_section(
            item, q_terms, plan.context_lines, index, target_symbol
        )
        fingerprint = _fingerprint(section)
        if fingerprint in seen:
            continue
        fitted = _fit_section(section, section_budget)
        if not fitted:
            continue
        blocks.append(fitted)
        selected.append(item.rel)
        selected_symbols.extend(_visible_symbol_labels(fitted, symbols))
        redactions.update(section_redactions)
        seen.add(fingerprint)
        if record is not None:
            selected_records.append(record)
        used += estimate_tokens(fitted)

    text = "\n".join(block.rstrip() for block in blocks if block).rstrip() + "\n"
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
        retrieval_plan=plan.to_dict(),
    )
    if session:
        save_working_set(root, session, query, selected)
    return result
