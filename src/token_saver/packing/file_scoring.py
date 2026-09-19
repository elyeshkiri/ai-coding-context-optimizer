"""Deterministic file scoring for the context-packing ranking pipeline."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
import math
import re
import subprocess
from pathlib import Path

from ..lexical import document_counts, identifier_terms, symbol_terms, terms
from ..repo_index import RepositoryIndex
from ..skeleton import file_priority
from .contracts import RankedFile
from .query_analysis import _query_member_hints, _query_wants_top_level

_MAX_FILE_BYTES = 2_000_000

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


def _rank_sort_key(item: RankedFile) -> tuple[float, int, str]:
    """Rank sort key."""
    return (-item.score, file_priority(item.rel), item.rel)


