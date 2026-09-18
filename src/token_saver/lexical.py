"""Shared lexical primitives used by the persistent index and context packer."""
from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import re

_WORD = re.compile(r"[A-Za-z0-9_$]+")
# A lower/digit-to-upper transition splits ordinary camelCase (fetchUser ->
# fetch, User); a run of two-or-more uppercase letters followed by a
# title-case word splits an acronym prefix from the word after it
# (HTTPBasicAuth -> HTTP, Basic, Auth), which the first pattern alone can't
# see since "P" to "B" is an upper-to-upper transition. Without the second
# pattern, identifiers like HTTPBasicAuth/URLPattern collapse into one
# fused token ("httpbasic") that never matches a query's separate
# "http"/"basic" terms. The lookbehind requires *two* preceding uppercase
# letters, not one, so a single leading capital (ETag, IPage) -- most
# often just an ordinary capitalized word, not an acronym -- is left
# whole, matching how the same word appears all-lowercase elsewhere
# (an "etag" property vs. an "ETag" HTTP header in prose).
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z][A-Z])(?=[A-Z][a-z])")
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "code", "do",
    "for", "from", "how", "i", "if", "in", "into", "is", "it", "me", "of",
    "on", "or", "our", "please", "project", "the", "this", "to", "use", "we",
    "with", "you", "your", "fix", "implement", "add", "build", "create",
}
_TERM_ALIASES = {
    "outline": "skeleton",
    "structural": "skeleton",
}

# Symbol matching can safely use a slightly richer equivalence set than file
# retrieval: it only reranks definitions inside a file that has already been
# selected. Keep these aliases deliberately small and code-oriented so we do
# not perturb repository-wide BM25 ranking.
_SYMBOL_ALIASES = {
    "first": "start",
    "begin": "start",
}


def terms(text: str) -> list[str]:
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


def symbol_terms(text: str) -> list[str]:
    """Tokenise for within-file symbol matching with conservative inflections.

    This intentionally does *not* feed repository-wide BM25. Natural-language
    task wording often names a code identifier through a nearby inflection
    (connection -> connect, equality -> equal, completion -> complete). At the
    file level those expansions are too broad; once the correct file is already
    selected they are useful evidence for choosing the exact definition.
    """
    out = list(terms(text))
    seen = set(out)

    def add(value: str) -> None:
        if len(value) >= 3 and value not in seen and value not in _STOP:
            seen.add(value)
            out.append(value)

    for term in tuple(out):
        alias = _SYMBOL_ALIASES.get(term)
        if alias:
            add(alias)

        # connection -> connect; validation -> validat + validate;
        # completion -> complet + complete; extraction -> extract.
        if term.endswith("tion") and len(term) > 6:
            stem = term[:-3]
            add(stem)
            if stem.endswith(("at", "et")):
                add(stem + "e")

        # equality -> equal; similarity -> similar.
        if term.endswith("ity") and len(term) > 6:
            add(term[:-3])

        # persistence -> persist; dependence -> depend.
        if term.endswith(("ance", "ence")) and len(term) > 7:
            add(term[:-4])

    return out


def document_counts(text: str, outline: str, rel: str) -> dict[str, int]:
    """Return the weighted BM25 term-frequency payload persisted in the index."""
    counts: Counter[str] = Counter(terms(text))
    counts.update(terms(outline))
    counts.update(terms(outline))
    for term in terms(rel):
        counts[term] += 3
    return dict(counts)


def fuzzy_symbol_terms(
    query_terms: set[str],
    vocabulary: set[str],
    *,
    min_ratio: float = 0.82,
    min_margin: float = 0.06,
) -> dict[str, tuple[str, float]]:
    """Map likely typo terms to identifier terms inside an already-selected file.

    This is intentionally *not* a general query expander. It only compares
    query words against the symbol-name vocabulary from one retrieved file,
    requires similar length and prefix shape, and rejects ambiguous near-ties.
    That makes fuzzy matching a late, structure-gated fallback rather than a
    repository-wide source of semantic noise.
    """
    vocab = {term.lower() for term in vocabulary if len(term) >= 4}
    matches: dict[str, tuple[str, float]] = {}
    for raw in query_terms:
        query = raw.lower()
        if len(query) < 4 or query in vocab:
            continue

        ranked: list[tuple[float, str]] = []
        for candidate in vocab:
            if query[0] != candidate[0]:
                continue
            if abs(len(query) - len(candidate)) > 2:
                continue
            ratio = SequenceMatcher(None, query, candidate).ratio()
            threshold = min_ratio if max(len(query), len(candidate)) >= 7 else max(min_ratio, 0.86)
            if ratio >= threshold:
                ranked.append((ratio, candidate))
        if not ranked:
            continue

        ranked.sort(key=lambda item: (-item[0], item[1]))
        best_ratio, best = ranked[0]
        second_ratio = ranked[1][0] if len(ranked) > 1 else 0.0
        if best_ratio < 0.94 and best_ratio - second_ratio < min_margin:
            continue
        matches[query] = (best, best_ratio)
    return matches
