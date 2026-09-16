"""Token counting.

Two modes:

* **exact** - `POST /v1/messages/count_tokens` via the Anthropic SDK. Model-specific
  and correct. Requires credentials and a network round trip.
* **estimate** - an offline heuristic, per file type. Free and instant, but only
  good to roughly ±20%. Use it for budgets, never for billing.

The heuristic's chars-per-token ratios were measured over ~17 MB of real source
with a BPE tokenizer, then corrected: Claude's tokenizer is not cl100k, and cl100k
undercounts Claude by ~15-20% on prose and more on code. The ratios below fold in
that correction, so they are deliberately conservative — they bias toward
over-estimating, because a budget that is too tight is cheaper to discover than
one that is silently blown. When a number actually matters, use exact mode.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_MODEL = "claude-sonnet-4-5"

# chars per Claude token, by file extension
_RATIOS = {
    ".py": 3.1,
    ".pyi": 3.1,
    ".rb": 3.1,
    ".go": 3.3,
    ".rs": 3.3,
    ".c": 3.3,
    ".h": 3.3,
    ".cpp": 3.3,
    ".hpp": 3.3,
    ".java": 3.6,
    ".kt": 3.6,
    ".cs": 3.6,
    ".swift": 3.4,
    ".php": 3.2,
    ".js": 3.8,
    ".jsx": 3.8,
    ".mjs": 3.8,
    ".cjs": 3.8,
    ".ts": 3.8,
    ".tsx": 3.8,
    ".json": 2.4,
    ".yaml": 2.9,
    ".yml": 2.9,
    ".toml": 2.9,
    ".md": 3.5,
    ".markdown": 3.5,
    ".txt": 3.0,
}
_CODE_DEFAULT = 3.3
_PROSE_DEFAULT = 3.5


def ratio_for(suffix: str) -> float:
    return _RATIOS.get(suffix.lower(), _CODE_DEFAULT)


def estimate_tokens(text: str, suffix: str = "") -> int:
    """Offline estimate. `suffix` selects the calibration; omit it for prose."""
    if not text:
        return 0
    ratio = _RATIOS.get(suffix.lower(), _PROSE_DEFAULT if not suffix else _CODE_DEFAULT)
    return max(1, int(len(text) / ratio))


def estimate_file(path: Path) -> int:
    try:
        return estimate_tokens(path.read_text(encoding="utf-8", errors="replace"), path.suffix)
    except OSError:
        return 0


def count_tokens_exact(text: str, model: str = DEFAULT_MODEL) -> int:
    """Exact count from the Messages API. Raises if the SDK or credentials are missing."""
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "exact counting needs the Anthropic SDK: pip install 'token-saver[exact]'"
        ) from exc
    client = anthropic.Anthropic()
    resp = client.messages.count_tokens(
        model=model,
        messages=[{"role": "user", "content": text}],
    )
    return resp.input_tokens


class Counter:
    """Counts tokens, exactly or by estimate, behind one interface."""

    def __init__(self, exact: bool = False, model: str = DEFAULT_MODEL) -> None:
        self.exact = exact
        self.model = model

    @property
    def label(self) -> str:
        return "exact" if self.exact else "≈est"

    def count(self, text: str, suffix: str = "") -> int:
        if self.exact:
            return count_tokens_exact(text, self.model)
        return estimate_tokens(text, suffix)


def format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)
