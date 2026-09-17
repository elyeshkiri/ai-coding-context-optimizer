"""Provider-aware token counting.

Offline estimates are free and conservative. Provider-specific counters can be
selected when exact/raw-tokenizer accounting matters:

* anthropic: Messages ``count_tokens`` API;
* openai: exact raw-text tokenization with ``tiktoken`` for the requested model;
* google: Gemini ``count_tokens`` API through ``google-genai``.

Raw-text tokenizer counts intentionally do not pretend to include provider
request-envelope/tool-schema overhead. Billing validation should still use the
provider's reported usage from the actual agent run.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

Provider = Literal["anthropic", "openai", "google"]
DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": DEFAULT_MODEL,
    "openai": "gpt-5.6",
    "google": "gemini-2.5-pro",
}

_RATIOS = {
    ".py": 3.1, ".pyi": 3.1, ".rb": 3.1, ".go": 3.3, ".rs": 3.3,
    ".c": 3.3, ".h": 3.3, ".cpp": 3.3, ".hpp": 3.3, ".java": 3.6,
    ".kt": 3.6, ".cs": 3.6, ".swift": 3.4, ".php": 3.2,
    ".js": 3.8, ".jsx": 3.8, ".mjs": 3.8, ".cjs": 3.8,
    ".ts": 3.8, ".tsx": 3.8, ".json": 2.4, ".yaml": 2.9,
    ".yml": 2.9, ".toml": 2.9, ".md": 3.5, ".markdown": 3.5,
    ".txt": 3.0,
}
_CODE_DEFAULT = 3.3
_PROSE_DEFAULT = 3.5


def ratio_for(suffix: str) -> float:
    return _RATIOS.get(suffix.lower(), _CODE_DEFAULT)


def estimate_tokens(text: str, suffix: str = "") -> int:
    """Offline estimate suitable for local hard-budget planning."""
    if not text:
        return 0
    ratio = _RATIOS.get(suffix.lower(), _PROSE_DEFAULT if not suffix else _CODE_DEFAULT)
    return max(1, int(len(text) / ratio))


def estimate_file(path: Path) -> int:
    try:
        return estimate_tokens(path.read_text(encoding="utf-8", errors="replace"), path.suffix)
    except OSError:
        return 0


def _anthropic_count(text: str, model: str) -> int:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Anthropic counting needs: pip install 'token-saver[exact]' "
            "(alias: 'token-saver[anthropic]')"
        ) from exc
    client = anthropic.Anthropic()
    response = client.messages.count_tokens(model=model, messages=[{"role": "user", "content": text}])
    return int(response.input_tokens)


def _openai_count(text: str, model: str) -> int:
    try:
        import tiktoken
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("OpenAI tokenization needs: pip install 'token-saver[openai]'") from exc
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("o200k_base")
    return len(encoding.encode(text))


def _google_count(text: str, model: str) -> int:
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Google counting needs: pip install 'token-saver[google]'") from exc
    client = genai.Client()
    response = client.models.count_tokens(model=model, contents=text)
    return int(response.total_tokens or 0)


def count_tokens_exact(
    text: str,
    model: str = DEFAULT_MODEL,
    provider: Provider = "anthropic",
) -> int:
    """Count text with the selected provider/tokenizer."""
    if provider == "anthropic":
        return _anthropic_count(text, model)
    if provider == "openai":
        return _openai_count(text, model)
    if provider == "google":
        return _google_count(text, model)
    raise ValueError(f"unsupported token provider: {provider}")


class Counter:
    """Counts tokens exactly/provider-specifically or by offline estimate."""

    def __init__(
        self,
        exact: bool = False,
        model: str | None = None,
        provider: Provider = "anthropic",
    ) -> None:
        if provider not in DEFAULT_MODELS:
            raise ValueError(f"unsupported token provider: {provider}")
        self.exact = exact
        self.provider = provider
        self.model = model or DEFAULT_MODELS[provider]

    @property
    def label(self) -> str:
        if not self.exact:
            return "≈est"
        return "exact" if self.provider == "anthropic" else f"{self.provider}:exact"

    def count(self, text: str, suffix: str = "") -> int:
        if self.exact:
            return count_tokens_exact(text, self.model, self.provider)
        return estimate_tokens(text, suffix)


def format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)
