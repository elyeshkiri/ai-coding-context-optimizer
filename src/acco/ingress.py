"""Safe pre-model staging for oversized Claude prompts.

Claude Code's UserPromptSubmit hook cannot replace prompt text. The safe runtime
therefore blocks an oversized prompt before model processing, stores the exact
original locally, and exposes a bounded recoverable packet that a tiny follow-up
prompt or plugin skill can load.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from .estimate import estimate_tokens
from .state import state_dir

SCHEMA = 1
MAX_STAGES = 40


@dataclass(frozen=True)
class IngressStage:
    """Metadata for one exact locally staged user prompt."""

    id: str
    created_at: int
    original_sha256: str
    original_tokens: int
    packet_tokens: int
    original_lines: int
    packet: str
    omitted_start_line: int | None
    omitted_end_line: int | None

    def to_dict(self) -> dict:
        """Return a JSON-compatible stage payload."""
        return asdict(self)


def _project_id(root: Path) -> str:
    """Return an opaque stable project identity for local stage storage."""
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:20]


def _directory(root: Path) -> Path:
    """Return the private project-scoped ingress directory."""
    return state_dir() / "ingress" / _project_id(root)


def _paths(root: Path, stage_id: str) -> tuple[Path, Path]:
    """Return metadata and exact-original paths for one stage id."""
    if not stage_id or any(ch not in "0123456789abcdef" for ch in stage_id.lower()):
        raise ValueError("invalid ingress stage id")
    directory = _directory(root)
    return directory / f"{stage_id}.json", directory / f"{stage_id}.txt"


def _write_private(path: Path, text: str) -> None:
    """Atomically write one private local state file."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        try:
            Path(temporary).unlink()
        except FileNotFoundError:
            pass


def _fit_lines(lines: list[str], token_budget: int, *, reverse: bool = False) -> list[str]:
    """Take whole exact lines from one edge without exceeding a token budget."""
    if token_budget <= 0:
        return []
    source = list(reversed(lines)) if reverse else lines
    selected: list[str] = []
    used = 0
    for line in source:
        cost = estimate_tokens(line + "\n")
        if selected and used + cost > token_budget:
            break
        if not selected and cost > token_budget:
            # One pathological line still needs a visible locator. Do not slice
            # its bytes and pretend the result is the source.
            break
        selected.append(line)
        used += cost
    return list(reversed(selected)) if reverse else selected


def _packet(
    stage_id: str,
    prompt: str,
    *,
    packet_tokens: int,
) -> tuple[str, int | None, int | None]:
    """Build a bounded exact-excerpt packet with explicit recoverability."""
    lines = prompt.splitlines()
    header = (
        "# TOKEN-SAVER STAGED PROMPT\n"
        f"# id: {stage_id}\n"
        "# The original prompt is stored exactly and was NOT sent to the model.\n"
        "# Omitted spans are recoverable with:\n"
        f"# token-saver ingress-read {stage_id} --start-line N --end-line M\n\n"
    )
    header_tokens = estimate_tokens(header)
    available = max(0, packet_tokens - header_tokens)
    if estimate_tokens(prompt) <= available:
        return header + prompt, None, None

    # User instructions for long-document prompts are commonly near the end,
    # so reserve more of the packet for the tail while keeping initial context.
    marker_reserve = min(80, max(20, available // 8))
    excerpt_budget = max(2, available - marker_reserve)
    head_budget = max(1, excerpt_budget * 2 // 5)
    tail_budget = max(1, excerpt_budget - head_budget)
    head = _fit_lines(lines, head_budget)
    tail = _fit_lines(lines[len(head):], tail_budget, reverse=True)
    if len(head) + len(tail) >= len(lines):
        return header + "\n".join(lines), None, None

    omitted_start = len(head) + 1
    omitted_end = len(lines) - len(tail)
    marker = (
        "\n\n"
        f"[TOKEN-SAVER: lines {omitted_start}-{omitted_end} omitted from this "
        "packet; exact original remains locally recoverable]\n\n"
    )
    body = "\n".join(head) + marker + "\n".join(tail)
    return header + body, omitted_start, omitted_end


def _prune(root: Path) -> None:
    """Bound staged prompt retention by deleting the oldest complete pairs."""
    directory = _directory(root)
    if not directory.is_dir():
        return
    metadata = sorted(
        directory.glob("*.json"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    for path in metadata[MAX_STAGES:]:
        stage_id = path.stem
        _meta, original = _paths(root, stage_id)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        try:
            original.unlink()
        except FileNotFoundError:
            pass


def stage_prompt(
    root: Path,
    prompt: str,
    *,
    packet_tokens: int = 1600,
) -> IngressStage:
    """Store an exact prompt and return its bounded recoverable packet."""
    if packet_tokens < 200:
        raise ValueError("ingress packet_tokens must be at least 200")
    root = root.resolve()
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    stage_id = digest[:12] + f"{int(time.time()) & 0xFFFF:04x}"
    packet, omitted_start, omitted_end = _packet(
        stage_id,
        prompt,
        packet_tokens=packet_tokens,
    )
    stage = IngressStage(
        id=stage_id,
        created_at=int(time.time()),
        original_sha256=digest,
        original_tokens=estimate_tokens(prompt),
        packet_tokens=estimate_tokens(packet),
        original_lines=max(1, len(prompt.splitlines())),
        packet=packet,
        omitted_start_line=omitted_start,
        omitted_end_line=omitted_end,
    )
    meta_path, original_path = _paths(root, stage_id)
    _write_private(original_path, prompt)
    _write_private(
        meta_path,
        json.dumps(
            {"schema": SCHEMA, **stage.to_dict()},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    _prune(root)
    return stage


def load_stage(root: Path, stage_id: str) -> IngressStage:
    """Load one staged prompt after verifying its exact-original digest."""
    meta_path, original_path = _paths(root.resolve(), stage_id)
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        original = original_path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise ValueError(f"unknown ingress stage: {stage_id}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError(f"invalid ingress stage: {stage_id}")
    digest = hashlib.sha256(original.encode()).hexdigest()
    if digest != payload.get("original_sha256"):
        raise ValueError(f"ingress stage integrity check failed: {stage_id}")
    fields = {
        key: payload[key]
        for key in (
            "id",
            "created_at",
            "original_sha256",
            "original_tokens",
            "packet_tokens",
            "original_lines",
            "packet",
            "omitted_start_line",
            "omitted_end_line",
        )
    }
    return IngressStage(**fields)


def read_stage(
    root: Path,
    stage_id: str,
    *,
    start_line: int,
    end_line: int,
) -> str:
    """Read an exact inclusive line range from a staged original prompt."""
    stage = load_stage(root, stage_id)
    if start_line < 1 or end_line < start_line:
        raise ValueError("ingress line range must satisfy 1 <= start <= end")
    if end_line > stage.original_lines:
        raise ValueError(
            f"ingress end line {end_line} exceeds {stage.original_lines}"
        )
    _meta, original_path = _paths(root.resolve(), stage_id)
    lines = original_path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[start_line - 1:end_line]) + "\n"


def maybe_stage_prompt(
    root: Path,
    prompt: str,
    *,
    enabled: bool,
    threshold_tokens: int,
    packet_tokens: int,
) -> IngressStage | None:
    """Stage only prompts that clear the explicit opt-in token threshold."""
    if not enabled or not prompt:
        return None
    if estimate_tokens(prompt) < threshold_tokens:
        return None
    return stage_prompt(root, prompt, packet_tokens=packet_tokens)
