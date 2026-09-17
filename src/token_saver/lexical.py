"""Shared lexical primitives used by the persistent index and context packer."""
from __future__ import annotations

from collections import Counter
import re

_WORD = re.compile(r"[A-Za-z0-9_$]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
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


def document_counts(text: str, outline: str, rel: str) -> dict[str, int]:
    """Return the weighted BM25 term-frequency payload persisted in the index."""
    counts: Counter[str] = Counter(terms(text))
    counts.update(terms(outline))
    counts.update(terms(outline))
    for term in terms(rel):
        counts[term] += 3
    return dict(counts)
