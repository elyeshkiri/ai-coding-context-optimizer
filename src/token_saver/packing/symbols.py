"""Compatibility facade for symbol scoring and source-window stages.

New internal code should import scoring policy from
:mod:`token_saver.packing.symbol_scoring` and rendering/window policy from
:mod:`token_saver.packing.symbol_windows`.
"""

from .symbol_scoring import (
    _ACTION_TERMS as _ACTION_TERMS,
    _SymbolScope as _SymbolScope,
    _apply_overload_dimensions as _apply_overload_dimensions,
    _apply_parent_credit as _apply_parent_credit,
    _best_child_by_container as _best_child_by_container,
    _build_symbol_scope as _build_symbol_scope,
    _call_graph_bonus as _call_graph_bonus,
    _contained_children_by_parent as _contained_children_by_parent,
    _containers_by_qualified as _containers_by_qualified,
    _corpus_term_weights as _corpus_term_weights,
    _explicit_member_bonus as _explicit_member_bonus,
    _family_signature_bonus as _family_signature_bonus,
    _fuzzy_identifier_bonus as _fuzzy_identifier_bonus,
    _generic_arity_delta as _generic_arity_delta,
    _lexical_symbol_score as _lexical_symbol_score,
    _overload_family_stats as _overload_family_stats,
    _score_symbol as _score_symbol,
    _symbol_key as _symbol_key,
    _symbol_term_maps as _symbol_term_maps,
    _unique_leaf_bonus as _unique_leaf_bonus,
)
from .symbol_windows import (
    _LARGE_CONTAINER_LINES as _LARGE_CONTAINER_LINES,
    _container_windows as _container_windows,
    _file_section as _file_section,
    _hit_lines as _hit_lines,
    _merge_ranges as _merge_ranges,
    _merge_windows as _merge_windows,
    _prioritized_ranges as _prioritized_ranges,
    _render_symbol_windows as _render_symbol_windows,
    _source_window as _source_window,
    _symbol_windows as _symbol_windows,
)
