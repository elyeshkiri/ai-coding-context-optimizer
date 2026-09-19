"""Query interpretation and file-ranking stages for context packing."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
import math
import re
import subprocess
from pathlib import Path

from ..closure import authoritative_providers, dependency_closure
from ..feedback import load_feedback
from ..lexical import (
    document_counts,
    fuzzy_symbol_terms,
    identifier_terms,
    symbol_terms,
    terms,
)
from ..repo_index import RepositoryIndex, build_index
from ..skeleton import file_priority
from ..working_set import load_working_set
from .contracts import RankedFile

_MAX_FILE_BYTES = 2_000_000
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
}


def _generic_parameter_names(signature: str, name: str) -> tuple[str, ...]:
    """Return generic parameters declared directly on a callable name."""
    match = re.search(
        rf"\b{re.escape(name)}\s*<([^<>]+)>\s*\(", signature,
        re.IGNORECASE,
    )
    if not match:
        return ()
    return tuple(part.strip() for part in match.group(1).split(",") if part.strip())


def _generic_arity(signature: str, name: str) -> int:
    """Handle generic arity."""
    return len(_generic_parameter_names(signature, name))


def _query_generic_arity(query: str, name: str) -> int | None:
    """Infer requested generic arity only from explicit or strongly-worded evidence."""
    explicit_match = re.search(
        rf"\b{re.escape(name)}\s*<([^<>]+)>", query,
        re.IGNORECASE,
    )
    if explicit_match:
        return len([
            part for part in explicit_match.group(1).split(",") if part.strip()
        ])

    lowered = query.lower()
    match = re.search(
        r"\b(one|two|three|four|five|six|seven|eight)\s+"
        r"(?:generic\s+)?input\s+types?\b",
        lowered,
    )
    if match and re.search(r"\b(?:a\s+)?return\s+type\b", lowered):
        # Multi-map APIs conventionally have N input generic types plus one
        # return generic type. Keep this inference narrow to explicit wording.
        return _NUMBER_WORDS[match.group(1)] + 1
    return None


def _callable_signature_terms(symbol) -> set[str]:
    """Lexical + structural terms that distinguish overloads of one callable."""
    raw = symbol.signature or ""
    out = set(symbol_terms(raw)) | set(identifier_terms(raw))
    generic_params = _generic_parameter_names(raw, symbol.name)
    if generic_params:
        out.add("generic")
        for param in generic_params:
            # C#/Java conventions such as TFirst/TSecond/TReturn carry useful
            # semantic evidence that ordinary camel splitting intentionally
            # keeps fused elsewhere.
            if len(param) > 1 and param[0] == "T" and param[1].isupper():
                out.update(identifier_terms(param[1:]))
    if "[]" in raw:
        out.add("array")
    if "func" in out:
        out.add("function")
    if symbol.name.lower().endswith("async") or re.search(r"\basync\b", raw, re.I):
        out.add("async")
    return out


def _query_member_hints(query: str) -> set[tuple[str, str]]:
    """Return explicit adjacent Container member mentions.

    Containers conventionally start with an uppercase identifier, while member
    casing is language-specific. Requiring an uppercase member silently
    disabled the strongest structural signal for Java, TypeScript and Rust.
    """
    pairs: set[tuple[str, str]] = set()
    for match in re.finditer(
        r"\b([A-Z][A-Za-z0-9_]*)\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)(?:<[^<>]+>)?",
        query,
    ):
        pairs.add((match.group(1).lower(), match.group(2).lower()))
    return pairs


def _query_wants_top_level(query: str) -> bool:
    """Handle query wants top level."""
    return bool(re.search(
        r"\b(?:package|module|top)[ -]?level\b", query, re.IGNORECASE
    ))


def _query_array_preference(query: str) -> bool | None:
    """Return whether an overload request explicitly wants or excludes arrays."""
    lowered = query.lower()
    if re.search(
        r"\b(?:rather\s+than|without|not|instead\s+of)\b[^,.;]{0,32}\barray\b",
        lowered,
    ):
        return False
    if re.search(r"\barrays?\b", lowered):
        return True
    return None


def _query_parameter_count(query: str) -> int | None:
    """Infer only parameter counts that are explicit enough to be reliable."""
    lowered = query.lower()
    if re.search(
        r"\b(?:takes?|accepts?)\s+no\s+(?:arguments?|parameters?)\b",
        lowered,
    ):
        return 0
    if re.search(r"\baccepts?\s+only\s+(?:a|an|one)\b", lowered):
        return 1
    return None


def _signature_parameter_count(signature: str, name: str) -> int | None:
    """Count top-level callable parameters without parsing the whole language."""
    match = re.search(
        rf"\b{re.escape(name)}\s*(?:<[^<>]+>)?\s*\(",
        signature,
        re.IGNORECASE,
    )
    if not match:
        return None
    start = match.end()
    depth_round = depth_square = depth_curly = depth_angle = 0
    commas = 0
    saw_token = False
    for char in signature[start:]:
        if char == "(":
            depth_round += 1
        elif char == ")":
            if depth_round == 0:
                return 0 if not saw_token else commas + 1
            depth_round -= 1
        elif char == "[":
            depth_square += 1
        elif char == "]" and depth_square:
            depth_square -= 1
        elif char == "{":
            depth_curly += 1
        elif char == "}" and depth_curly:
            depth_curly -= 1
        elif char == "<":
            depth_angle += 1
        elif char == ">" and depth_angle:
            depth_angle -= 1
        elif (
            char == ","
            and depth_round == depth_square == depth_curly == depth_angle == 0
        ):
            commas += 1
        elif not char.isspace():
            saw_token = True
    return None


def _signature_has_implementation(signature: str) -> bool:
    """Handle signature has implementation."""
    return "{ … }" in signature


def _query_declaration_preference(query: str) -> str | None:
    """Handle query declaration preference."""
    lowered = query.lower()
    if re.search(r"\bimplementation\b", lowered):
        return "implementation"
    if re.search(r"\boverload\b", lowered):
        return "declaration"
    return None


def _query_negative_terms(query: str) -> set[str]:
    """Terms explicitly excluded by phrases such as 'without an end index'."""
    out: set[str] = set()
    for match in re.finditer(
        r"\b(?:without|rather\s+than|instead\s+of)\s+"
        r"(?:a|an|the)?\s*"
        r"([A-Za-z_][A-Za-z0-9_]*(?:\s+[A-Za-z_][A-Za-z0-9_]*){0,2})",
        query,
        re.IGNORECASE,
    ):
        out.update(symbol_terms(match.group(1)))
    return out


# A callable whose bare name is defined in more than this many files (get, add,
# run, route, ...) is generic API vocabulary, not evidence that any one of those
# files is the answer to a query that happens to contain the same common word.
_GENERIC_CALLABLE_MAX_FILES = 3
_AUTHORITY_CALLABLE_KINDS = frozenset({"method", "function", "constructor"})


@lru_cache(maxsize=65536)
def _leaf_identifier_terms(name: str) -> frozenset[str]:
    """Handle leaf identifier terms."""
    return frozenset(identifier_terms(name))


@lru_cache(maxsize=65536)
def _authority_leaf_terms(name: str) -> frozenset[str]:
    """Leaf terms comparable with repository/query tokenization.

    File authority consumes symbol_terms(query), which intentionally drops prose
    stopwords such as "is" and "with". Requiring every raw identifier component
    made isPrimitive and WithTimeout impossible to recognize structurally.
    Mirror repository tokenization for the gate, while preserving the small set
    of API verbs that symbol matching deliberately restores.
    """
    out = set(terms(name))
    out.update(
        set(identifier_terms(name)) & {"add", "build", "create", "use"}
    )
    return frozenset(out)


def _callable_file_counts(index: RepositoryIndex) -> Counter[str]:
    """How many files define a callable with each (lowercased) bare name."""
    counts: Counter[str] = Counter()
    for record in index.records.values():
        names = {
            symbol.name.lower()
            for symbol in record.definitions or []
            if symbol.kind in _AUTHORITY_CALLABLE_KINDS
        }
        counts.update(names)
    return counts


def _structural_file_authority(
    record,
    query: str,
    *,
    query_terms: set[str] | None = None,
    explicit_pairs: set[tuple[str, str]] | None = None,
    callable_file_counts: Counter[str] | None = None,
) -> float:
    """Length-independent authority for files that define a requested callable.

    ``query_terms``/``explicit_pairs``/``callable_file_counts`` are per-query,
    per-repository values; ``rank_files`` computes them once instead of once per
    file. When omitted, no generic-name filtering is applied.
    """
    if record is None or not record.definitions:
        return 0.0
    if query_terms is None:
        query_terms = set(symbol_terms(query))
    if explicit_pairs is None:
        explicit_pairs = _query_member_hints(query)
    best = 0.0
    for symbol in record.definitions:
        if symbol.kind not in _AUTHORITY_CALLABLE_KINDS:
            continue
        leaf_terms = _authority_leaf_terms(symbol.name)
        if not leaf_terms or not leaf_terms <= query_terms:
            continue
        parent = (symbol.parent or "").rsplit(".", 1)[-1].lower()
        name_lower = symbol.name.lower()
        # File authority only needs identifier-level shape evidence.
        # Avoid symbol_terms() here: this loop runs once per candidate symbol
        # and query tokenization must remain O(1) per repository query.
        authority_signature_terms = set(
            identifier_terms(symbol.signature or "")
        )
        non_leaf_signature_hits = len(
            (query_terms - leaf_terms) & authority_signature_terms
        )
        signature_bonus = min(48.0, 12.0 * non_leaf_signature_hits)
        wants_top_level = _query_wants_top_level(query)
        if wants_top_level:
            if not parent:
                # Same-named module helpers are common in large JS/TS repos.
                # Prefer the top-level declaration whose signature actually
                # matches the query; an exported API gets a small bounded edge
                # over an otherwise-equivalent file-local helper.
                export_bonus = (
                    80.0
                    if re.search(r"\bexport\b", symbol.signature or "", re.I)
                    else 0.0
                )
                best = max(best, 140.0 + signature_bonus + export_bonus)
            continue
        if parent and (parent, name_lower) in explicit_pairs:
            # A literal parser-backed Container Member pair is stronger than
            # arbitrarily many call-site mentions of a common method name
            # (e.g. Client WithTimeout vs context.WithTimeout across a repo).
            best = max(best, 200.0 + signature_bonus)
            continue
        if (
            callable_file_counts is not None
            and callable_file_counts.get(name_lower, 0) > _GENERIC_CALLABLE_MAX_FILES
        ):
            continue
        qualified_terms = _leaf_identifier_terms(symbol.qualified or symbol.name)
        parent_terms = qualified_terms - leaf_terms
        parent_hits = len(parent_terms & query_terms)
        score = 38.0 + 8.0 * len(leaf_terms) + min(24.0, 8.0 * parent_hits)
        if parent_terms and not parent_hits:
            score *= 0.45
        best = max(best, score)
    return min(320.0, best)


# Kept as private compatibility aliases for callers/tests that imported these
# helpers before retrieval was moved into the persistent index.
def _terms(text: str) -> list[str]:
    """Handle terms."""
    return terms(text)


def _document_terms(text: str, outline: str, rel: str) -> Counter[str]:
    """Handle document terms."""
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
    """Read source."""
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


@dataclass
class _FileRankingScope:
    """Query-scoped inputs shared by every file's score in one ranking pass."""

    index: RepositoryIndex
    q_terms: list[str]
    changed: set[str]
    feedback: dict
    remembered_files: set[str]
    query_continues: bool
    authority_terms: set[str]
    authority_pairs: set
    callable_file_counts: Counter
    query: str
    structural_authority: Callable = _structural_file_authority


def _expand_query_terms(index: RepositoryIndex, query: str) -> list[str]:
    """Query terms plus conservative repository-scope typo corrections.

    Only identifier vocabulary participates, and the global thresholds are
    intentionally stricter than the within-file fallback used during symbol
    selection. Original query terms are always retained; corrected terms are
    additive evidence, never rewrites.
    """
    q_terms = list(dict.fromkeys(terms(query)))
    symbol_vocabulary: set[str] = set()
    for record in index.records.values():
        for symbol_name in record.symbols:
            symbol_vocabulary.update(terms(symbol_name))
    typo_corrections = fuzzy_symbol_terms(
        set(q_terms), symbol_vocabulary, min_ratio=0.88, min_margin=0.08,
    )
    for _source_term, (corrected, _ratio) in typo_corrections.items():
        if corrected not in q_terms:
            q_terms.append(corrected)
    return q_terms


def _resolve_changed_files(
    root: Path, changed_boost: bool, changed_files: set[str] | None,
) -> set[str]:
    """Resolve changed files."""
    if not changed_boost:
        return set()
    if changed_files is not None:
        return changed_files
    return _changed_files(root)


def _candidate_documents(
    root: Path, index: RepositoryIndex,
    exclude_files: set[str] | None, restrict_files: set[str] | None,
) -> list[tuple[Path, str, str, Counter[str]]]:
    """Indexed files eligible for this query, with their weighted term counts."""
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
            # Older index records predate persisted term counts. Rebuild them
            # through the same canonical weighting the index itself uses
            # (outline counted twice, path terms at 3x) so a legacy record
            # cannot silently rank on a stale formula. Source bytes are not
            # hydrated at ranking time, so indexed tokens stand in for text.
            counts = _document_terms(" ".join(record.tokens), record.outline, rel)
        docs.append((root / rel, rel, record.outline, counts))
    return docs


def _bm25_score(
    counts: Counter[str], q_terms: list[str], doc_freq: Counter[str],
    length: int, avg_len: float, n_docs: int,
) -> tuple[float, int]:
    """Standard BM25 accumulation. Returns (score, total matched term count)."""
    score = 0.0
    matched = 0
    for term in q_terms:
        tf = counts.get(term, 0)
        if not tf:
            continue
        matched += tf
        df = doc_freq[term]
        idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
        k1, b = 1.5, 0.75
        denom = tf + k1 * (1.0 - b + b * length / avg_len)
        score += idf * (tf * (k1 + 1.0) / denom)
    return score, matched


def _apply_file_boosts(
    scope: _FileRankingScope, rel: str, outline: str, score: float,
    reasons: list[str],
) -> float:
    """Code-aware boosts layered on top of the BM25 base, in a fixed order."""
    rel_terms = set(terms(rel))
    outline_terms = set(terms(outline))
    path_hits = sum(1 for term in scope.q_terms if term in rel_terms)
    symbol_hits = sum(1 for term in scope.q_terms if term in outline_terms)
    if path_hits:
        score += 8.0 * path_hits
        reasons.append(f"path:{path_hits}")
    if symbol_hits:
        score += 5.0 * symbol_hits
        reasons.append(f"symbols:{symbol_hits}")

    # Parser-backed declaration authority must survive BM25 document-length
    # normalisation. This especially matters for partial-class APIs split
    # across large implementation files: exact container+member evidence is
    # stronger than incidental prose/body overlap in smaller neighbors. It is
    # added *before* the low-value-directory dampening below so a test or
    # example file that merely defines a same-named helper is not exempt
    # from that penalty.
    authority = scope.structural_authority(
        scope.index.records.get(rel), scope.query,
        query_terms=scope.authority_terms, explicit_pairs=scope.authority_pairs,
        callable_file_counts=scope.callable_file_counts,
    )
    if authority:
        score += authority
        reasons.append(f"structural-symbol:{authority:.1f}")

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
    if rel in scope.changed:
        score += 4.0
        reasons.append("changed")
    if scope.query_continues and rel in scope.remembered_files:
        score += 2.0
        reasons.append("working-set")
    if scope.feedback.get(rel):
        boost = max(-2.0, min(2.0, scope.feedback[rel] * 0.4))
        score += boost
        reasons.append(f"feedback:{scope.feedback[rel]:+d}")
    return score


def _score_documents(
    scope: _FileRankingScope, docs: list[tuple[Path, str, str, Counter[str]]],
) -> list[RankedFile]:
    """Handle score documents."""
    lengths = [sum(counts.values()) for *_, counts in docs]
    avg_len = max(1.0, sum(lengths) / len(lengths))
    doc_freq = Counter({
        term: sum(1 for *_, counts in docs if term in counts)
        for term in scope.q_terms
    })

    ranked: list[RankedFile] = []
    for (path, rel, outline, counts), length in zip(docs, lengths):
        reasons: list[str] = []
        score, matched = _bm25_score(
            counts, scope.q_terms, doc_freq, length, avg_len, len(docs),
        )
        score = _apply_file_boosts(scope, rel, outline, score, reasons)
        if matched:
            reasons.insert(0, f"term-hits:{matched}")
        ranked.append(RankedFile(
            path=path,
            rel=rel,
            text="",
            outline=outline,
            score=score,
            reasons=reasons or [f"priority:{file_priority(rel)}"],
            term_hits=matched,
            changed=rel in scope.changed,
        ))
    return ranked


def _credit_closure(item: RankedFile, related) -> None:
    """Handle credit closure."""
    item.score += 2.5 * related.confidence
    item.reasons.append(f"graph:{related.reason}@{related.distance}")
    item.reasons.append(
        f"closure:{related.source}@{related.distance}:{related.confidence:.2f}"
    )


def _apply_graph_boosts(
    scope: _FileRankingScope, ranked: list[RankedFile],
    priority_files: set[str] | None, seed_limit: int,
    graph_hops: int, closure_max_items: int,
) -> None:
    """Boost files reachable from the top seeds, then authoritative providers."""
    by_rel = {item.rel: item for item in ranked}
    seed_pool = [item.rel for item in ranked if item.term_hits or item.changed]
    if priority_files:
        seed_pool.sort(key=lambda rel: rel not in priority_files)
    seeds = seed_pool[:seed_limit]
    for related in dependency_closure(
        scope.index, seeds, max_hops=graph_hops, max_items=closure_max_items,
    ):
        item = by_rel.get(related.path)
        if item is None:
            continue
        _credit_closure(item, related)

    # dependency_closure above is seeded from only the top seed_limit files
    # (deliberately small/cost-bounded, since most of its edge kinds are
    # transitive and can fan out). A source ranked just below that cutoff --
    # e.g. behind several near-duplicate files that outscore it on raw term
    # overlap alone -- would otherwise never get a chance to surface an exact
    # value it imports. Run the cheap, non-transitive semantic-ref lookup over
    # every relevant candidate instead of just the seed set.
    for related in authoritative_providers(scope.index, seed_pool):
        item = by_rel.get(related.path)
        if item is None or any(
            reason.startswith("graph:") for reason in item.reasons
        ):
            continue
        _credit_closure(item, related)


def _apply_embedding_rerank(
    scope: _FileRankingScope, ranked: list[RankedFile],
) -> None:
    """Optional local-only semantic rerank on top of deterministic ranking."""
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
        f"{item.rel} {' '.join(scope.index.records[item.rel].symbols)} {item.outline}"
        for item in ranked
    ]
    vectors = model.encode([scope.query] + descriptions, normalize_embeddings=True)
    query_vector = vectors[0]
    for item, vector in zip(ranked, vectors[1:]):
        semantic = float(query_vector @ vector)
        item.score += max(0.0, semantic) * 3.0
        item.reasons.append(f"embedding:{semantic:.2f}")


def _rank_sort_key(item: RankedFile) -> tuple[float, int, str]:
    """Rank sort key."""
    return (-item.score, file_priority(item.rel), item.rel)


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
    _symbol_terms_fn: Callable[[str], list[str]] = symbol_terms,
    _load_feedback_fn: Callable[[Path], dict] = load_feedback,
    _structural_authority_fn: Callable = _structural_file_authority,
) -> list[RankedFile]:
    """Rank indexed files for ``query`` using BM25 + code-aware boosts.

    The expensive parse/skeleton/token-frequency work is performed when a file
    enters or changes in the index. Query-time ranking touches only cached
    records; exact source is read later for final context candidates.

    Pipeline: expand the query, collect candidate documents, score each with
    BM25 plus code-aware boosts, then layer graph-closure and optional
    embedding evidence before the final ordering.
    """
    root = root.resolve()
    if graph_hops < 0:
        raise ValueError("graph_hops must be nonnegative")
    if seed_limit <= 0:
        raise ValueError("seed_limit must be positive")
    index = index or build_index(root, use_gitignore=use_gitignore)

    q_terms = _expand_query_terms(index, query)
    changed = _resolve_changed_files(root, changed_boost, changed_files)
    remembered_files, remembered_terms = (
        load_working_set(root, session) if session else (set(), set())
    )
    feedback = _load_feedback_fn(root) if feedback_boost else {}
    query_continues = bool(set(q_terms) & remembered_terms)

    docs = _candidate_documents(root, index, exclude_files, restrict_files)
    if not docs:
        return []

    # Built only once a candidate set exists: _callable_file_counts walks the
    # whole index and is not memoized, so an empty result must not pay for it.
    scope = _FileRankingScope(
        index=index,
        q_terms=q_terms,
        changed=changed,
        feedback=feedback,
        remembered_files=remembered_files,
        query_continues=query_continues,
        authority_terms=set(_symbol_terms_fn(query)),
        authority_pairs=_query_member_hints(query),
        callable_file_counts=_callable_file_counts(index),
        query=query,
        structural_authority=_structural_authority_fn,
    )
    ranked = _score_documents(scope, docs)
    ranked.sort(key=_rank_sort_key)
    _apply_graph_boosts(
        scope, ranked, priority_files, seed_limit, graph_hops, closure_max_items,
    )
    if embeddings:
        _apply_embedding_rerank(scope, ranked)
    ranked.sort(key=_rank_sort_key)
    return ranked


