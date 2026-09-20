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
        "jaccard_similarity",
        "char_ngrams",
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


def status() -> dict:
    """Return machine-readable accelerator availability and fallback behavior."""
    return {
        "available": available(),
        "backend": "rust" if available() else "python",
        "capabilities": list(capabilities()),
        "env_override": os.environ.get("TOKEN_SAVER_RUST_FASTPATH"),
    }
