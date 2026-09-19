"""Task-aware context packing facade and final orchestration stage.

The algorithm is implemented as private pipeline stages under
:mod:`token_saver.packing`. This module preserves the historical public and
private import surface while keeping final budgeted pack assembly centralized.
"""

from __future__ import annotations

from pathlib import Path

from .budget import plan_retrieval
from .estimate import estimate_tokens
from .feedback import load_feedback as load_feedback
from .lexical import symbol_terms as symbol_terms, terms
from .repo_index import RepositoryIndex, build_index, similarity
from .working_set import save_working_set
from .packing.contracts import ContextPack as ContextPack, RankedFile as RankedFile
from .packing.ranking import (
    _AUTHORITY_CALLABLE_KINDS as _AUTHORITY_CALLABLE_KINDS,
    _FileRankingScope as _FileRankingScope,
    _GENERIC_CALLABLE_MAX_FILES as _GENERIC_CALLABLE_MAX_FILES,
    _MAX_FILE_BYTES as _MAX_FILE_BYTES,
    _NUMBER_WORDS as _NUMBER_WORDS,
    _apply_embedding_rerank as _apply_embedding_rerank,
    _apply_file_boosts as _apply_file_boosts,
    _apply_graph_boosts as _apply_graph_boosts,
    _authority_leaf_terms as _authority_leaf_terms,
    _bm25_score as _bm25_score,
    _callable_file_counts as _callable_file_counts,
    _callable_signature_terms as _callable_signature_terms,
    _candidate_documents as _candidate_documents,
    _changed_files as _ranking_changed_files,
    _credit_closure as _credit_closure,
    _document_terms as _document_terms,
    _expand_query_terms as _expand_query_terms,
    _generic_arity as _generic_arity,
    _generic_parameter_names as _generic_parameter_names,
    _leaf_identifier_terms as _leaf_identifier_terms,
    _query_array_preference as _query_array_preference,
    _query_declaration_preference as _query_declaration_preference,
    _query_generic_arity as _query_generic_arity,
    _query_member_hints as _query_member_hints,
    _query_negative_terms as _query_negative_terms,
    _query_parameter_count as _query_parameter_count,
    _query_wants_top_level as _query_wants_top_level,
    _rank_sort_key as _rank_sort_key,
    _read_source as _read_source,
    _resolve_changed_files as _resolve_changed_files,
    _score_documents as _score_documents,
    _signature_has_implementation as _signature_has_implementation,
    _signature_parameter_count as _signature_parameter_count,
    _structural_file_authority as _structural_file_authority,
    _terms as _terms,
    rank_files as _rank_files,
)
from .packing.render import (
    _fingerprint as _fingerprint,
    _fit_section as _fit_section,
    _static_plan as _static_plan,
    _visible_symbol_labels as _visible_symbol_labels,
)
from .packing.symbols import (
    _ACTION_TERMS as _ACTION_TERMS,
    _LARGE_CONTAINER_LINES as _LARGE_CONTAINER_LINES,
    _SymbolScope as _SymbolScope,
    _apply_overload_dimensions as _apply_overload_dimensions,
    _apply_parent_credit as _apply_parent_credit,
    _best_child_by_container as _best_child_by_container,
    _build_symbol_scope as _build_symbol_scope,
    _call_graph_bonus as _call_graph_bonus,
    _contained_children_by_parent as _contained_children_by_parent,
    _container_windows as _container_windows,
    _containers_by_qualified as _containers_by_qualified,
    _corpus_term_weights as _corpus_term_weights,
    _explicit_member_bonus as _explicit_member_bonus,
    _family_signature_bonus as _family_signature_bonus,
    _file_section as _file_section,
    _fuzzy_identifier_bonus as _fuzzy_identifier_bonus,
    _generic_arity_delta as _generic_arity_delta,
    _hit_lines as _hit_lines,
    _lexical_symbol_score as _lexical_symbol_score,
    _merge_ranges as _merge_ranges,
    _merge_windows as _merge_windows,
    _overload_family_stats as _overload_family_stats,
    _prioritized_ranges as _prioritized_ranges,
    _render_symbol_windows as _render_symbol_windows,
    _score_symbol as _score_symbol,
    _source_window as _source_window,
    _symbol_key as _symbol_key,
    _symbol_term_maps as _symbol_term_maps,
    _symbol_windows as _symbol_windows,
    _unique_leaf_bonus as _unique_leaf_bonus,
)

_DEFAULT_MAX_FILES = 12
_DEFAULT_CONTEXT_LINES = 6


def _changed_files(root: Path) -> set[str]:
    """Compatibility seam for changed-file discovery and monkeypatching."""
    return _ranking_changed_files(root)


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
    """Rank files through the extracted stage while preserving patch seams."""
    resolved_changed = changed_files
    if changed_boost and resolved_changed is None:
        resolved_changed = _changed_files(root)
    if not changed_boost:
        resolved_changed = set()
    return _rank_files(
        root,
        query,
        use_gitignore=use_gitignore,
        changed_boost=changed_boost,
        index=index,
        graph_hops=graph_hops,
        session=session,
        embeddings=embeddings,
        feedback_boost=feedback_boost,
        closure_max_items=closure_max_items,
        changed_files=resolved_changed,
        priority_files=priority_files,
        exclude_files=exclude_files,
        restrict_files=restrict_files,
        seed_limit=seed_limit,
        _symbol_terms_fn=symbol_terms,
        _load_feedback_fn=load_feedback,
        _structural_authority_fn=_structural_file_authority,
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
            text=fitted,
            estimated_tokens=estimate_tokens(fitted),
            scanned_files=len(ranked),
            selected_files=[],
            ranked=ranked,
            retrieval_plan=plan.to_dict(),
        )

    blocks = [header]
    selected: list[str] = []
    seen: set[str] = set()
    selected_records = []
    selected_symbols: list[str] = []
    selected_symbol_identities: list[str] = []
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

        section, symbols, identities, section_redactions = _file_section(
            item, q_terms, plan.context_lines, index, target_symbol,
            symbol_query_text=effective_query,
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
        selected_symbol_identities.extend(_visible_symbol_labels(fitted, identities))
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
        selected_symbol_identities=selected_symbol_identities,
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

