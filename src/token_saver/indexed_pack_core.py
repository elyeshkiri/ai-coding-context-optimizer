"""Index-backed task-aware context packing.

Ranking operates entirely on persisted repository-index metadata. Source files
are opened only after they have won a place in the bounded candidate set, which
removes the previous O(repository source bytes) read/tokenize work from every
query while preserving exact source windows in the final pack.
"""
from __future__ import annotations

from collections import Counter
import math
from pathlib import Path

from .adaptive_budget import plan_retrieval
from .closure import dependency_closure
from .estimate import estimate_tokens
from .feedback import load_feedback
from .legacy_pack import (
    ContextPack,
    RankedFile,
    _changed_files,
    _file_section,
    _fingerprint,
    _fit_section,
    _read_source,
)
from .lexical import terms
from .repo_index import RepositoryIndex, build_index, similarity
from .skeleton import file_priority
from .working_set import load_working_set, save_working_set

_DEFAULT_MAX_FILES = 12
_DEFAULT_CONTEXT_LINES = 6


def rank_files_indexed(
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
    adaptive_budget: bool = False,
    max_tokens: int = 6000,
    typescript_semantic: bool | None = None,
    strict_semantic: bool = False,
) -> list[RankedFile]:
    """Rank files from persistent metadata; do not read source bodies."""
    root = root.resolve()
    if graph_hops < 0:
        raise ValueError("graph_hops must be nonnegative")
    index = index or build_index(
        root,
        use_gitignore=use_gitignore,
        typescript_semantic=typescript_semantic,
        strict_semantic=strict_semantic,
    )
    q_terms = list(dict.fromkeys(terms(query)))
    if not changed_boost:
        changed = set()
    elif changed_files is not None:
        changed = changed_files
    else:
        changed = _changed_files(root)
    remembered_files, remembered_terms = load_working_set(root, session) if session else (set(), set())
    feedback = load_feedback(root) if feedback_boost else {}
    query_continues = bool(set(q_terms) & remembered_terms)

    docs: list[tuple[str, object, Counter[str]]] = []
    for rel, record in index.records.items():
        if exclude_files and rel in exclude_files:
            continue
        if restrict_files is not None and rel not in restrict_files:
            continue
        counts = Counter(record.term_counts or {token: 1 for token in record.tokens})
        docs.append((rel, record, counts))
    if not docs:
        return []

    lengths = [sum(counts.values()) for _, _, counts in docs]
    avg_len = max(1.0, sum(lengths) / len(lengths))
    doc_freq = Counter({term: sum(1 for _, _, counts in docs if term in counts) for term in q_terms})
    query_lower = query.strip().lower()
    ranked: list[RankedFile] = []

    for (rel, record, counts), length in zip(docs, lengths):
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
        outline = record.outline or ""
        outline_terms = set(terms(outline))
        path_hits = sum(1 for term in q_terms if term in rel_terms)
        symbol_hits = sum(1 for term in q_terms if term in outline_terms)
        if path_hits:
            score += 8.0 * path_hits
            reasons.append(f"path:{path_hits}")
        if symbol_hits:
            score += 5.0 * symbol_hits
            reasons.append(f"symbols:{symbol_hits}")
        # Exact-phrase bonus remains index-only: outlines/path can prove it
        # without reopening the source body. Source-only phrase matches still
        # contribute through persisted term frequencies.
        if query_lower and len(query_lower) >= 4 and (
            query_lower in outline.lower() or query_lower in rel.lower()
        ):
            score += 5.0
            reasons.append("exact phrase")

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
        if record.semantic_refs:
            reasons.append(f"semantic-edges:{len(record.semantic_refs)}")

        ranked.append(RankedFile(
            path=root / rel,
            rel=rel,
            text="",  # lazily hydrated only for selected evidence
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

    if adaptive_budget:
        plan = plan_retrieval(ranked, max_tokens, graph_hops=None, closure_items=None)
        seed_count = plan.seed_count
        effective_hops = plan.graph_hops
        effective_closure = plan.closure_items
        if ranked:
            ranked[0].reasons.append(f"adaptive-confidence:{plan.confidence:.2f}")
    else:
        seed_count = 6
        effective_hops = graph_hops
        effective_closure = closure_max_items

    seeds = seed_pool[:seed_count]
    for related in dependency_closure(
        index, seeds, max_hops=effective_hops, max_items=effective_closure,
    ):
        item = by_rel.get(related.path)
        if item is None:
            continue
        item.score += 2.5 * related.confidence
        item.reasons.append(f"graph:{related.reason}@{related.distance}")
        item.reasons.append(f"closure:{related.source}@{related.distance}:{related.confidence:.2f}")

    if embeddings:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("embedding reranking requires: pip install 'token-saver[embeddings]'") from exc
        try:
            model = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)
        except OSError as exc:
            raise RuntimeError("local embedding model all-MiniLM-L6-v2 is not downloaded") from exc
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


def build_context_pack_indexed(
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
    adaptive_budget: bool = False,
    typescript_semantic: bool | None = None,
    strict_semantic: bool = False,
) -> ContextPack:
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if max_files <= 0:
        raise ValueError("max_files must be positive")
    if not 0.0 <= duplicate_threshold <= 1.0:
        raise ValueError("duplicate_threshold must be between 0 and 1")

    root = root.resolve()
    index = index or build_index(
        root,
        use_gitignore=use_gitignore,
        persist=persist_index,
        typescript_semantic=typescript_semantic,
        strict_semantic=strict_semantic,
    )
    effective_query = f"{query} {target_symbol or ''}".strip()
    ranked = rank_files_indexed(
        root,
        effective_query,
        use_gitignore=use_gitignore,
        changed_boost=changed_boost,
        index=index,
        graph_hops=graph_hops,
        session=session,
        embeddings=embeddings,
        feedback_boost=feedback_boost,
        closure_max_items=closure_max_items,
        changed_files=changed_files,
        priority_files=priority_files,
        exclude_files=exclude_files,
        restrict_files=restrict_files,
        adaptive_budget=adaptive_budget,
        max_tokens=max_tokens,
        typescript_semantic=typescript_semantic,
        strict_semantic=strict_semantic,
    )
    q_terms = set(terms(effective_query))
    task_display = query.strip() or "(no query; structural priority mode)"
    if len(task_display) > 300:
        task_display = task_display[:300] + f"… (+{len(task_display) - 300} chars)"
    mode_bits = ["indexed"]
    if adaptive_budget:
        mode_bits.append("adaptive")
    if index.semantic_enabled:
        mode_bits.append("typescript-semantic")
    header = (
        f"# TOKEN-SAVER CONTEXT PACK: {root.name}\n"
        f"# task: {task_display}\n"
        f"# mode: {', '.join(mode_bits)}\n"
        f"# budget: {max_tokens} tokens; exact source windows preserve editable bytes\n"
        f"# scanned: {len(ranked)} indexed files\n\n"
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
    candidates = [item for item in ranked if item.term_hits or item.changed] or ranked
    if priority_files:
        candidates = sorted(candidates, key=lambda item: item.rel not in priority_files)
    priority_total = sum(1 for item in candidates if priority_files and item.rel in priority_files)
    priority_seen = 0
    adaptive = plan_retrieval(ranked, max_tokens) if adaptive_budget else None

    for position, item in enumerate(candidates):
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
        elif adaptive is not None and target_symbol is None:
            # Prevent one very large top file from consuming the complete pack
            # when the ranking is ambiguous. High-confidence plans naturally
            # have fewer seeds and therefore larger per-file shares.
            slots = min(max_files - len(selected), max(1, len(candidates) - position), adaptive.seed_count)
            if slots > 1:
                remaining = min(remaining, max(adaptive.per_file_floor, remaining // slots * 2))

        text = _read_source(item.path)
        if text is None:
            item.reasons.append("source-unavailable")
            continue
        item.text = text
        section, symbols, section_redactions = _file_section(item, q_terms, context_lines, index, target_symbol)
        fingerprint = _fingerprint(section)
        if fingerprint in seen:
            continue
        record = index.records.get(item.rel)
        if record is not None and any(similarity(record, prior) >= duplicate_threshold for prior in selected_records):
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
        closure_files=[item.rel for item in ranked if any(reason.startswith("closure:") for reason in item.reasons)],
    )
    if session:
        save_working_set(root, session, query, selected)
    return result
