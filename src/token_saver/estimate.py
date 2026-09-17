"""Token counting.

Two modes are intentionally separate:

* **exact** uses the provider's tokenizer/counting mechanism for a concrete
  model: Anthropic's count-tokens API or OpenAI's local tiktoken model map.
* **estimate** is the existing conservative offline file-type heuristic used
  for fast context budgeting. It is not billing-grade and remains provider
  neutral so ranking does not silently change when a model name changes.
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_MODEL = "claude-sonnet-4-5"

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
    """Offline estimate. ``suffix`` selects the calibration; omit for prose."""
    if not text:
        return 0
    ratio = _RATIOS.get(
        suffix.lower(), _PROSE_DEFAULT if not suffix else _CODE_DEFAULT
    )
    return max(1, int(len(text) / ratio))


def estimate_file(path: Path) -> int:
    try:
        return estimate_tokens(
            path.read_text(encoding="utf-8", errors="replace"), path.suffix
        )
    except OSError:
        return 0


def provider_for_model(model: str) -> str | None:
    """Infer a supported tokenizer provider from a model id."""
    name = model.strip().lower()
    if name.startswith("claude-"):
        return "anthropic"
    if name.startswith(("gpt-", "chatgpt-", "o1", "o3", "o4")):
        return "openai"
    return None


def _count_anthropic(text: str, model: str) -> int:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "exact Anthropic counting needs: pip install 'token-saver[exact]'"
        ) from exc
    client = anthropic.Anthropic()
    resp = client.messages.count_tokens(
        model=model,
        messages=[{"role": "user", "content": text}],
    )
    return int(resp.input_tokens)


def _count_openai(text: str, model: str) -> int:
    try:
        import tiktoken
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "exact OpenAI counting needs: pip install 'token-saver[exact]'"
        ) from exc
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError as exc:
        # Do not silently call a fallback tokenizer and label the result exact.
        raise RuntimeError(
            f"tiktoken does not have an exact tokenizer mapping for model {model!r}; "
            "upgrade tiktoken or use offline estimate mode"
        ) from exc
    return len(encoding.encode(text))


def count_tokens_exact(
    text: str,
    model: str = DEFAULT_MODEL,
    *,
    provider: str | None = None,
) -> int:
    """Count model input tokens with the selected provider.

    Anthropic uses its message-count API and therefore includes provider message
    framing. OpenAI uses the model's local tiktoken encoding and counts the text
    content itself; callers that need full request accounting should add their
    own message/tool schema overhead rather than pretending a generic wrapper is
    exact for every API surface.
    """
    chosen = (provider or provider_for_model(model) or "").lower()
    if chosen == "anthropic":
        return _count_anthropic(text, model)
    if chosen == "openai":
        return _count_openai(text, model)
    raise ValueError(
        f"unsupported token-counting provider for model {model!r}; "
        "pass provider='anthropic' or provider='openai'"
    )


class Counter:
    """Counts tokens, exactly or by estimate, behind one interface."""

    def __init__(
        self,
        exact: bool = False,
        model: str = DEFAULT_MODEL,
        provider: str | None = None,
    ) -> None:
        self.exact = exact
        self.model = model
        self.provider = provider

    @property
    def label(self) -> str:
        if not self.exact:
            return "≈est"
        provider = self.provider or provider_for_model(self.model)
        return f"exact:{provider}" if provider else "exact"

    def count(self, text: str, suffix: str = "") -> int:
        if self.exact:
            return count_tokens_exact(
                text, self.model, provider=self.provider
            )
        return estimate_tokens(text, suffix)


def format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)
