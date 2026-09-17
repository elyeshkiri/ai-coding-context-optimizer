"""Shared lexical primitives used by the persistent index and context packer."""
from __future__ import annotations

from collections import Counter
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
