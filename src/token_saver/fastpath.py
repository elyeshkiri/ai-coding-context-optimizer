"""Optional Rust acceleration with exact Python fallbacks.

The Python implementation remains authoritative. Rust is used only for small,
pure primitives whose outputs are parity-tested; disabling or omitting the
extension must not change retrieval semantics.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable

_IDENT = re.compile(r"\b[A-Za-z_$][\w$]*\b")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_CRITICAL = re.compile(
    r"(?i)(Traceback|AssertionError|\b(?:ERROR|FAILED|FATAL|PANIC)\b|Caused by:|"
    r"(?:^|\s)[\w./\\-]+\.(?:py|pyi|ts|tsx|js|jsx|go|rs|java|cs|rb|php):\d+)"
)


def _extension():
    """Return the optional Rust extension unless explicitly disabled."""
    if os.environ.get("TOKEN_SAVER_RUST_FASTPATH", "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return None
    try:
        import _token_saver_fast
    except ImportError:
        return None
    return _token_saver_fast


def available() -> bool:
    """Return whether the optional compiled accelerator is active."""
    return _extension() is not None


def capabilities() -> tuple[str, ...]:
    """Return the currently parity-gated accelerated primitive names."""
    if not available():
        return ()
    return (
        "estimate_tokens",
        "identifier_tokens",
        "bm25_score",
        "jaccard_similarity",
        "char_ngrams",
        "strip_ansi",
        "collapse_repeated_lines",
        "critical_lines",
    )


def estimate_tokens(text: str, ratio: float) -> int:
    """Estimate tokens via Rust when present, otherwise exact Python parity."""
    ext = _extension()
    if ext is not None:
        return int(ext.estimate_tokens(text, float(ratio)))
    if not text:
        return 0
    return max(1, int(len(text) / ratio))


def identifier_tokens(text: str) -> list[str]:
    """Return normalized code identifiers using the indexer's reference rules."""
    ext = _extension()
    if ext is not None:
        return [str(value) for value in ext.identifier_tokens(text)]
    return sorted(
        {
            value.lower()
            for value in _IDENT.findall(text)
            if len(value) > 2
        }
    )


def bm25_score(
    counts: dict[str, int],
    q_terms: list[str],
    doc_freq: dict[str, int],
    length: int,
    avg_len: float,
    n_docs: int,
) -> tuple[float, int]:
    """Accumulate BM25 scores with an exact Python fallback."""
    ext = _extension()
    if ext is not None:
        score, matched = ext.bm25_score(
            counts,
            q_terms,
            doc_freq,
            length,
            avg_len,
            n_docs,
        )
        return float(score), int(matched)
    if avg_len <= 0 or n_docs <= 0:
        return 0.0, 0
    import math

    score = 0.0
    matched = 0
    for term in q_terms:
        tf = counts.get(term, 0)
        if not tf:
            continue
        matched += tf
        df = doc_freq.get(term, 0)
        idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
        k1, b = 1.5, 0.75
        denom = tf + k1 * (1.0 - b + b * length / avg_len)
        score += idf * (tf * (k1 + 1.0) / denom)
    return score, matched


def jaccard_similarity(left: Iterable[str], right: Iterable[str]) -> float:
    """Return Jaccard similarity with the same empty-set semantics as Python."""
    a, b = set(left), set(right)
    ext = _extension()
    if ext is not None:
        return float(ext.jaccard_similarity(sorted(a), sorted(b)))
    return len(a & b) / len(a | b) if a and b else 0.0


def char_ngrams(token: str, n: int = 3) -> list[str]:
    """Return padded character n-grams for future fuzzy/ranking hot paths."""
    if n <= 0:
        raise ValueError("n must be positive")
    ext = _extension()
    if ext is not None:
        return [str(value) for value in ext.char_ngrams(token, n)]
    padded = f"^{token}$"
    if len(padded) < n:
        return [padded]
    return [padded[i:i + n] for i in range(len(padded) - n + 1)]



def strip_ansi(text: str) -> str:
    """Remove ANSI escapes through Rust when present, otherwise Python parity."""
    ext = _extension()
    if ext is not None and hasattr(ext, "strip_ansi"):
        return str(ext.strip_ansi(text))
    return _ANSI.sub("", text)


def collapse_repeated_lines(text: str, minimum: int = 3) -> str:
    """Collapse consecutive identical lines through the parity-gated fastpath."""
    if minimum <= 0:
        raise ValueError("minimum must be positive")
    ext = _extension()
    if ext is not None and hasattr(ext, "collapse_repeated_lines"):
        return str(ext.collapse_repeated_lines(text, minimum))
    lines = text.splitlines()
    if len(lines) < minimum:
        return text
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        j = i + 1
        while j < len(lines) and lines[j] == line:
            j += 1
        count = j - i
        if line.strip() and count >= minimum:
            out.append(line)
            out.append(
                f"[token-saver: previous line repeated {count - 1} more times]"
            )
        else:
            out.extend(lines[i:j])
        i = j
    candidate = "\n".join(out) + ("\n" if text.endswith("\n") else "")
    return candidate if len(candidate) < len(text) else text


def critical_lines(text: str, max_lines: int = 20) -> list[str]:
    """Return unique critical diagnostics through Rust or exact Python fallback."""
    if max_lines <= 0:
        return []
    ext = _extension()
    if ext is not None and hasattr(ext, "critical_lines"):
        return [str(value) for value in ext.critical_lines(text, max_lines)]
    out: list[str] = []
    seen: set[str] = set()
    for line in strip_ansi(text).splitlines():
        key = line.strip()
        if not key or key in seen or not _CRITICAL.search(line):
            continue
        seen.add(key)
        out.append(line)
        if len(out) >= max_lines:
            break
    return out


def status() -> dict:
    """Return machine-readable accelerator availability and fallback behavior."""
    return {
        "available": available(),
        "backend": "rust" if available() else "python",
        "capabilities": list(capabilities()),
        "env_override": os.environ.get("TOKEN_SAVER_RUST_FASTPATH"),
    }
