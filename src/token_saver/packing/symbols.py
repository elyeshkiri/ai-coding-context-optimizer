"""Symbol scoring, source-window selection, and file-section rendering."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math

from ..lexical import fuzzy_symbol_terms, identifier_terms, symbol_terms, terms
from ..repo_index import RepositoryIndex
from ..security import redact_secrets
from .contracts import RankedFile
from .ranking import (
    _callable_signature_terms,
    _generic_arity,
    _query_array_preference,
    _query_declaration_preference,
    _query_generic_arity,
    _query_member_hints,
    _query_negative_terms,
    _query_parameter_count,
    _signature_has_implementation,
    _signature_parameter_count,
)

_LARGE_CONTAINER_LINES = 200

def _hit_lines(text: str, query_terms: set[str]) -> list[tuple[int, int]]:
    """Handle hit lines."""
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
    """Merge windows."""
    windows = sorted((max(1, n - radius), min(total, n + radius)) for n in lines)
    merged: list[tuple[int, int]] = []
    for start, end in windows:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _merge_ranges(windows: list[tuple[int, int]], total: int) -> list[tuple[int, int]]:
    """Merge ranges."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted((max(1, a), min(total, b)) for a, b in windows):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _source_window(text: str, start: int, end: int) -> str:
    """Handle source window."""
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


@dataclass
class _SymbolScope:
    """Per-file precomputation shared by every symbol score in one file.

    Building these maps once per file keeps the individual scoring stages
    below pure functions of (scope, symbol), which is what makes them
    independently testable and cheap to reason about.
    """

    rel: str
    definitions: list
    source_lines: list[str]
    container_names: set[str]
    symbol_query_terms: set[str]
    positive_query_terms: set[str]
    negative_query_terms: set[str]
    query_text: str
    identifier_terms_by_symbol: dict
    signature_terms_by_symbol: dict
    leaf_terms_by_symbol: dict
    leaf_doc_freq: Counter
    fuzzy_query_terms: dict
    term_weight: dict[str, float]
    family_sizes: Counter
    family_term_freq: dict
    family_body_shapes: dict
    explicit_member_hints: set
    array_preference: bool | None
    desired_parameter_count: int | None
    declaration_preference: str | None

    def key(self, symbol) -> tuple[str, int]:
        """Return key for symbol scope."""
        return (symbol.name, symbol.start_line)

    def family_of(self, symbol) -> str:
        """Return family of for symbol scope."""
        return (symbol.qualified or symbol.name).lower()

    def is_container(self, symbol) -> bool:
        """Return whether container."""
        return (symbol.qualified or symbol.name) in self.container_names

    def body_terms(self, symbol) -> set[str]:
        """Body vocabulary, deliberately empty for container declarations.

        Container relevance comes from explicit containment (see
        _apply_parent_credit), not from re-reading all descendant bodies as
        if they belonged to the class/type declaration itself.
        """
        if self.is_container(symbol):
            return set()
        body = "\n".join(
            self.source_lines[max(0, symbol.start_line - 1):symbol.end_line]
        )
        return set(terms(body))


def _symbol_term_maps(definitions: list) -> tuple[dict, dict, dict, Counter]:
    """Identifier/signature/leaf term maps plus leaf document frequency."""
    identifier_by_symbol = {
        (symbol.name, symbol.start_line): set(identifier_terms(
            symbol.qualified or symbol.name
        ))
        for symbol in definitions
    }
    signature_by_symbol = {
        (symbol.name, symbol.start_line): (
            _callable_signature_terms(symbol)
            - identifier_by_symbol[(symbol.name, symbol.start_line)]
        )
        for symbol in definitions
    }
    leaf_by_symbol = {
        (symbol.name, symbol.start_line): set(identifier_terms(symbol.name))
        for symbol in definitions
    }
    leaf_doc_freq: Counter[str] = Counter()
    for leaf_terms in leaf_by_symbol.values():
        leaf_doc_freq.update(leaf_terms)
    return identifier_by_symbol, signature_by_symbol, leaf_by_symbol, leaf_doc_freq


def _overload_family_stats(
    definitions: list, signature_terms_by_symbol: dict,
) -> tuple[Counter, dict, dict]:
    """Statistics scoped to one exact qualified-callable (overload) family.

    A second IDF scope is intentionally local to an overload family. Terms
    such as CommandDefinition, Type[], TFirst/TSecond, or string may be common
    in a large partial class while still being highly discriminating among
    definitions that share the exact same qualified callable name.
    """
    family_sizes: Counter[str] = Counter()
    family_term_freq: dict[str, Counter[str]] = {}
    family_body_shapes: dict[str, set[bool]] = {}
    for symbol in definitions:
        family = (symbol.qualified or symbol.name).lower()
        family_sizes[family] += 1
        family_body_shapes.setdefault(family, set()).add(
            _signature_has_implementation(symbol.signature or "")
        )
        bucket = family_term_freq.setdefault(family, Counter())
        for term in signature_terms_by_symbol[(symbol.name, symbol.start_line)]:
            bucket[term] += 1
    return family_sizes, family_term_freq, family_body_shapes


def _corpus_term_weights(scope: _SymbolScope) -> dict[str, float]:
    """File-local IDF over identifier, signature, and body vocabulary."""
    doc_freq: Counter[str] = Counter()
    for symbol in scope.definitions:
        key = scope.key(symbol)
        all_terms = (
            scope.identifier_terms_by_symbol[key]
            | scope.signature_terms_by_symbol[key]
            | scope.body_terms(symbol)
        )
        for term in all_terms:
            doc_freq[term] += 1
    n = len(scope.definitions)
    return {term: math.log((n + 1) / (df + 1)) + 1 for term, df in doc_freq.items()}


def _build_symbol_scope(
    item: RankedFile, record, query_terms: set[str],
    target_symbol: str | None, symbol_query_text: str | None,
) -> _SymbolScope:
    """Build symbol scope."""
    definitions = record.definitions or []
    # File retrieval stays on the conservative global tokenizer. Once a file
    # has already won retrieval, symbol selection can safely normalize nearby
    # inflections (connection/connect, equality/equal, completion/complete)
    # without perturbing repository-wide ranking.
    symbol_query_terms = set(symbol_terms(
        symbol_query_text if symbol_query_text is not None
        else " ".join(sorted(query_terms))
    ))
    (
        identifier_by_symbol, signature_by_symbol,
        leaf_by_symbol, leaf_doc_freq,
    ) = _symbol_term_maps(definitions)

    all_symbol_name_terms = (
        set().union(*identifier_by_symbol.values()) if definitions else set()
    )
    fuzzy_query_terms = (
        fuzzy_symbol_terms(symbol_query_terms, all_symbol_name_terms)
        if not (target_symbol or "").lower() else {}
    )
    query_text = symbol_query_text or ""
    negative_query_terms = _query_negative_terms(query_text)
    family_sizes, family_term_freq, family_body_shapes = _overload_family_stats(
        definitions, signature_by_symbol,
    )

    scope = _SymbolScope(
        rel=item.rel,
        definitions=definitions,
        source_lines=item.text.splitlines(),
        container_names={
            symbol.parent for symbol in definitions if symbol.parent
        },
        symbol_query_terms=symbol_query_terms,
        positive_query_terms=symbol_query_terms - negative_query_terms,
        negative_query_terms=negative_query_terms,
        query_text=query_text,
        identifier_terms_by_symbol=identifier_by_symbol,
        signature_terms_by_symbol=signature_by_symbol,
        leaf_terms_by_symbol=leaf_by_symbol,
        leaf_doc_freq=leaf_doc_freq,
        fuzzy_query_terms=fuzzy_query_terms,
        term_weight={},
        family_sizes=family_sizes,
        family_term_freq=family_term_freq,
        family_body_shapes=family_body_shapes,
        explicit_member_hints=_query_member_hints(query_text),
        array_preference=_query_array_preference(query_text),
        desired_parameter_count=_query_parameter_count(query_text),
        declaration_preference=_query_declaration_preference(query_text),
    )
    if not (target_symbol or "").lower() and definitions:
        scope.term_weight = _corpus_term_weights(scope)
    return scope


# Common API verbs that are also ordinary natural-language imperatives
# ("build a compact outline"), so they carry less identifier evidence.
_ACTION_TERMS = frozenset({"add", "build", "create", "use"})


def _lexical_symbol_score(
    scope: _SymbolScope, identifier_hits: set[str],
    signature_hits: set[str], body_hits: set[str],
) -> float:
    """Weighted identifier/signature/body overlap, IDF-scaled."""
    weight = scope.term_weight
    specific_identifier_hits = identifier_hits - _ACTION_TERMS
    action_identifier_hits = identifier_hits & _ACTION_TERMS
    action_weight = 20 if specific_identifier_hits else 4
    return (
        20 * sum(weight.get(t, 1.0) for t in specific_identifier_hits)
        + action_weight * sum(weight.get(t, 1.0) for t in action_identifier_hits)
        + 8 * sum(weight.get(t, 1.0) for t in signature_hits)
        + 3 * sum(weight.get(t, 1.0) for t in body_hits)
    )


def _explicit_member_bonus(scope: _SymbolScope, symbol) -> float:
    """Credit a literal "Container Member" mention in the request.

    This is the strongest within-file signal. It prevents
    QueryFirstAsync/ExecuteScalarAsync from beating QueryAsync/ExecuteAsync
    just because their bodies share more task vocabulary. Overloads of that
    exact member all receive the same bonus and are still separated below by
    signature.
    """
    parent_leaf = (symbol.parent or "").rsplit(".", 1)[-1].lower()
    explicit = bool(
        parent_leaf
        and (parent_leaf, symbol.name.lower()) in scope.explicit_member_hints
    )
    return 120.0 if explicit else 0.0


def _family_signature_bonus(
    scope: _SymbolScope, symbol, signature_hits: set[str], family_size: int,
) -> float:
    """Reward signature terms that discriminate within an overload family."""
    if family_size <= 1 or not signature_hits:
        return 0.0
    family = scope.family_of(symbol)
    term_freq = scope.family_term_freq[family]
    discriminating = [
        term for term in signature_hits
        if term_freq.get(term, 0) < family_size
    ]
    if not discriminating:
        return 0.0
    family_bonus = 12.0 * sum(
        math.log((family_size + 1) / (term_freq[term] + 1)) + 1.0
        for term in discriminating
    )
    return min(72.0, family_bonus)


def _generic_arity_delta(scope: _SymbolScope, symbol, family_size: int) -> float:
    """Explicit generic syntax is structural overload evidence.

    Explicit generic syntax (QueryAsync<T>) and narrowly-worded multi-map
    requests ("two input types ... return type") are structural overload
    evidence, not ordinary lexical overlap.
    """
    desired_arity = _query_generic_arity(scope.query_text, symbol.name)
    if desired_arity is None:
        return 0.0
    actual_arity = _generic_arity(symbol.signature or "", symbol.name)
    if actual_arity == desired_arity:
        return 72.0
    return -24.0 if family_size > 1 else 0.0


def _apply_overload_dimensions(
    scope: _SymbolScope, symbol, signature_name_terms: set[str], score: float,
) -> float:
    """Structural overload dimensions, applied only within a real family.

    Some overload dimensions are structural rather than ordinary word overlap.
    Apply them to the exact qualified-name family even for top-level functions.
    Adjustments are applied in a fixed order against the running score.
    """
    has_array = "array" in signature_name_terms
    if scope.array_preference is not None:
        score += 56.0 if has_array == scope.array_preference else -16.0

    wants_command_definition = {"command", "definition"} <= scope.symbol_query_terms
    has_command_definition = {"command", "definition"} <= signature_name_terms
    if wants_command_definition:
        score += 48.0 if has_command_definition else -12.0

    if scope.desired_parameter_count is not None:
        actual_parameter_count = _signature_parameter_count(
            symbol.signature or "", symbol.name
        )
        if actual_parameter_count == scope.desired_parameter_count:
            score += 52.0
        elif actual_parameter_count is not None:
            score -= 16.0

    # TypeScript-style overload sets contain declaration-only signatures plus
    # one body-bearing implementation with the same qualified name. Only use
    # this signal when both shapes coexist, so ordinary C#/Java overload
    # families remain unaffected.
    shapes = scope.family_body_shapes.get(scope.family_of(symbol), set())
    if shapes == {False, True} and scope.declaration_preference:
        has_body = _signature_has_implementation(symbol.signature or "")
        wants_body = scope.declaration_preference == "implementation"
        score += 72.0 if has_body == wants_body else -24.0

    excluded_hits = scope.negative_query_terms & signature_name_terms
    if excluded_hits:
        # These terms were explicitly negated by the request, so they must
        # never be allowed to win back their own penalty through positive
        # signature overlap. A same-family overload carrying the excluded
        # parameter is strong counter-evidence.
        score -= min(120.0, 32.0 * len(excluded_hits))
    return score


def _unique_leaf_bonus(scope: _SymbolScope, symbol) -> float:
    """Credit a query that literally names this symbol's unique leaf identifier.

    Stronger evidence than the same word merely occurring in a sibling
    signature or container. Kept local, bounded, and IDF-weighted so generic
    names do not dominate by themselves. Action verbs are excluded here and
    left to the ordinary qualified-name score.
    """
    leaf_hits = {
        term
        for term in (
            scope.symbol_query_terms & scope.leaf_terms_by_symbol[scope.key(symbol)]
        )
        if scope.leaf_doc_freq.get(term, 0) == 1 and term not in _ACTION_TERMS
    }
    if not leaf_hits:
        return 0.0
    n_symbols = max(1, len(scope.definitions))
    strongest_leaf = max(
        math.log((n_symbols + 1) / (scope.leaf_doc_freq[t] + 1)) + 1
        for t in leaf_hits
    )
    return min(30.0, 18.0 * strongest_leaf)


def _fuzzy_identifier_bonus(scope: _SymbolScope, identifier_name_terms: set[str]) -> float:
    """Bounded fallback for identifier typos.

    Gated twice: the file has already survived structural/file retrieval, and
    only query terms with no exact identifier match anywhere in this file are
    eligible for correction.
    """
    fuzzy_bonus = 0.0
    for _query_term, (candidate, ratio) in scope.fuzzy_query_terms.items():
        if candidate in identifier_name_terms:
            fuzzy_bonus += 10.0 * ratio
    return min(12.0, fuzzy_bonus)


def _call_graph_bonus(scope: _SymbolScope, symbol) -> float:
    """Credit parser-derived calls naming an operation the task mentions.

    Parser-derived calls are stronger than incidental body vocabulary, but
    this stays bounded so call names never become a global ranker.
    """
    call_terms = set(terms(" ".join(symbol.calls or [])))
    call_hits = scope.positive_query_terms & call_terms
    if not call_hits:
        return 0.0
    return min(24.0, 6.0 * sum(scope.term_weight.get(t, 1.0) for t in call_hits))


def _score_symbol(scope: _SymbolScope, symbol, wanted: str) -> float:
    """Total relevance for one definition.

    With an explicit --target-symbol the score is purely name matching. The
    query-driven path composes the stages above in a fixed order.
    """
    if wanted:
        if symbol.name.lower() == wanted:
            return 100
        return 50 if wanted in symbol.name.lower() else 0

    key = scope.key(symbol)
    identifier_name_terms = scope.identifier_terms_by_symbol[key]
    signature_name_terms = scope.signature_terms_by_symbol[key]

    identifier_hits = scope.positive_query_terms & identifier_name_terms
    signature_hits = scope.positive_query_terms & signature_name_terms
    body_hits = scope.positive_query_terms & scope.body_terms(symbol)

    score = _lexical_symbol_score(
        scope, identifier_hits, signature_hits, body_hits,
    )
    family_size = scope.family_sizes.get(scope.family_of(symbol), 1)

    score += _explicit_member_bonus(scope, symbol)
    score += _family_signature_bonus(scope, symbol, signature_hits, family_size)
    score += _generic_arity_delta(scope, symbol, family_size)
    if family_size > 1:
        score = _apply_overload_dimensions(
            scope, symbol, signature_name_terms, score,
        )
    score += _unique_leaf_bonus(scope, symbol)
    score += _fuzzy_identifier_bonus(scope, identifier_name_terms)
    score += _call_graph_bonus(scope, symbol)
    return score


def _symbol_key(symbol) -> tuple[str, int, int]:
    """Handle symbol key."""
    return (symbol.qualified or symbol.name, symbol.start_line, symbol.end_line)


def _containers_by_qualified(scope: _SymbolScope) -> dict[str, list]:
    """Handle containers by qualified."""
    out: dict[str, list] = {}
    for candidate in scope.definitions:
        qualified = candidate.qualified or candidate.name
        if qualified in scope.container_names:
            out.setdefault(qualified, []).append(candidate)
    return out


def _best_child_by_container(
    matches: list[tuple[float, object]], containers_by_qualified: dict[str, list],
) -> tuple[dict, dict]:
    """Map each container to the highest-scoring member it actually contains."""
    best_child_score: dict[tuple[str, int, int], float] = {}
    best_child_symbol: dict[tuple[str, int, int], object] = {}
    for score, symbol in matches:
        if not symbol.parent:
            continue
        for parent in containers_by_qualified.get(symbol.parent, []):
            # Only synthesize parent relevance when the member is actually
            # nested in the parent's source extent. Go/Rust impl methods are
            # siblings of their type declaration and should remain
            # independent candidates.
            contained = (
                parent.start_line <= symbol.start_line
                and symbol.end_line <= parent.end_line
            )
            prototype_family = (
                not contained
                and parent.signature.lstrip().startswith(
                    ("function ", "export function ", "async function ")
                )
            )
            if not contained and not prototype_family:
                continue
            key = _symbol_key(parent)
            if score > best_child_score.get(key, 0):
                best_child_score[key] = score
                best_child_symbol[key] = symbol
    return best_child_score, best_child_symbol


def _apply_parent_credit(
    scope: _SymbolScope, matches: list[tuple[float, object]],
) -> tuple[list[tuple[float, object]], dict, dict]:
    """Promote containers to their best contained member's score.

    Container relevance comes from explicit containment, not from re-reading
    all descendant body vocabulary as if it belonged to the class/type
    declaration itself. This preserves parent-credit behavior without making
    large containers lexical hubs.
    """
    containers_by_qualified = _containers_by_qualified(scope)
    best_child_score, best_child_symbol = _best_child_by_container(
        matches, containers_by_qualified,
    )

    boosted_matches: list[tuple[float, object]] = []
    seen_keys: set[tuple[str, int, int]] = set()
    for score, symbol in matches:
        key = _symbol_key(symbol)
        boosted_matches.append((max(score, best_child_score.get(key, 0)), symbol))
        seen_keys.add(key)

    for _qualified, parents in containers_by_qualified.items():
        for parent in parents:
            key = _symbol_key(parent)
            child_score = best_child_score.get(key, 0)
            if child_score and key not in seen_keys:
                boosted_matches.append((child_score, parent))
                seen_keys.add(key)

    return boosted_matches, best_child_symbol, containers_by_qualified


def _contained_children_by_parent(
    matches: list[tuple[float, object]], containers_by_qualified: dict[str, list],
) -> dict[tuple[str, int, int], list]:
    """Handle contained children by parent."""
    out: dict[tuple[str, int, int], list] = {}
    for _score, candidate in matches:
        if not candidate.parent:
            continue
        for parent in containers_by_qualified.get(candidate.parent, []):
            contained = (
                parent.start_line <= candidate.start_line
                and candidate.end_line <= parent.end_line
            )
            if contained:
                out.setdefault(_symbol_key(parent), []).append(candidate)
    return out


def _container_windows(symbol, child) -> list[tuple[int, int]]:
    """Source windows for one selected symbol.

    A container large enough that rendering it in full risks being clipped by
    a tight per-file budget before ever reaching the specific member that
    earned it the boost -- found via a real regression: httpx's ~1400-line
    Client class was truncated well before its credited
    _send_handling_redirects method at line 964, even though the (untruncated)
    window nominally "contained" it. Render a tight window around that member
    instead of the container's full span -- still labeled as the container,
    since that's still why this slot was won, but backed by source that
    actually survives budget fitting regardless of the container's own size.
    Also keep a couple of lines at the container's own declaration so its
    label's line survives too -- omitting it caused a second real regression:
    the container's own label was then stripped as "not visible" by the same
    downstream check this whole fix exists to satisfy.
    """
    return [
        (max(1, symbol.start_line - 1), symbol.start_line + 1),
        (max(1, child.start_line - 1), child.end_line + 1),
    ]


def _render_symbol_windows(
    scope: _SymbolScope, selected: list, best_child_symbol: dict,
    relevant_children_by_parent: dict,
) -> tuple[list[tuple[int, int]], list[str], list[str]]:
    """Render symbol windows."""
    windows: list[tuple[int, int]] = []
    labels: list[str] = []
    identities: list[str] = []
    for symbol in selected:
        child = best_child_symbol.get(_symbol_key(symbol))
        child_contained = (
            child is not None
            and child.start_line >= symbol.start_line
            and child.end_line <= symbol.end_line
        )
        credit_child_label = child_contained and child not in selected
        is_large = symbol.end_line - symbol.start_line > _LARGE_CONTAINER_LINES
        if child_contained and is_large:
            windows.extend(_container_windows(symbol, child))
        else:
            windows.append((max(1, symbol.start_line - 1), symbol.end_line + 1))
        labels.append(f"{scope.rel}:{symbol.name}@{symbol.start_line}")
        identity_line = symbol.identity_line or symbol.start_line
        identities.append(
            f"{scope.rel}:{symbol.qualified or symbol.name}@{identity_line}"
        )

        # selected_symbols is an evidence ledger, not a strict 1:1 list of
        # rendered windows. When a selected container renders the exact source
        # of multiple relevant members, credit those members too; the downstream
        # visibility filter still drops any label whose declaration line was
        # clipped from the final section. This avoids losing a relevant sibling
        # merely because another member supplied the container's max parent
        # score.
        credited_children = list(
            relevant_children_by_parent.get(_symbol_key(symbol), [])
        )
        if credit_child_label and child not in credited_children:
            credited_children.insert(0, child)
        for credited in credited_children[:3]:
            if credited in selected:
                continue
            labels.append(f"{scope.rel}:{credited.name}@{credited.start_line}")
            credited_identity_line = credited.identity_line or credited.start_line
            identities.append(
                f"{scope.rel}:{credited.qualified or credited.name}"
                f"@{credited_identity_line}"
            )
    return windows, labels, identities


def _symbol_windows(
    item: RankedFile, index: RepositoryIndex, query_terms: set[str],
    target_symbol: str | None, symbol_query_text: str | None = None,
) -> tuple[list[tuple[int, int]], list[str], list[str]]:
    """Select, score, and render the best symbol windows for one file.

    Pipeline: build the per-file term scope, score every definition, promote
    containers to their best contained member, then render the top two as
    exact source windows with their evidence labels.
    """
    record = index.records.get(item.rel)
    if record is None:
        return [], [], []
    wanted = (target_symbol or "").lower()
    scope = _build_symbol_scope(
        item, record, query_terms, target_symbol, symbol_query_text,
    )

    matches: list[tuple[float, object]] = []
    for symbol in scope.definitions:
        score = _score_symbol(scope, symbol, wanted)
        if score:
            matches.append((score, symbol))

    if not wanted:
        matches, best_child_symbol, containers_by_qualified = _apply_parent_credit(
            scope, matches,
        )
    else:
        best_child_symbol = {}
        containers_by_qualified = {}

    matches.sort(key=lambda pair: (-pair[0], pair[1].start_line, pair[1].name))
    selected = [symbol for _, symbol in matches[:2]]

    relevant_children_by_parent = (
        _contained_children_by_parent(matches, containers_by_qualified)
        if not wanted else {}
    )
    return _render_symbol_windows(
        scope, selected, best_child_symbol, relevant_children_by_parent,
    )


def _file_section(
    item: RankedFile, query_terms: set[str], context_lines: int,
    index: RepositoryIndex, target_symbol: str | None = None,
    symbol_query_text: str | None = None,
) -> tuple[str, list[str], list[str], list[str]]:
    """Handle file section."""
    lines = item.text.splitlines()
    symbol_windows, symbol_labels, symbol_identities = _symbol_windows(
        item, index, query_terms, target_symbol, symbol_query_text
    )
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
    return section, symbol_labels, symbol_identities, redactions


