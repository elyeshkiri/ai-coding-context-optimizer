"""Query interpretation helpers shared by file and symbol ranking."""

from __future__ import annotations

import re

from ..lexical import fuzzy_symbol_terms, identifier_terms, symbol_terms, terms
from ..repo_index import RepositoryIndex

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


