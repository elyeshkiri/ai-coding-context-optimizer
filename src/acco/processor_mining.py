"""Mine real agent transcripts for high-cost unsupported command families."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import shlex

from .estimate import estimate_tokens
from .output.pipeline import detect_failure
from .output.registry import DEFAULT_REGISTRY, ProcessorRegistry


def command_signature(command: str) -> str:
    """Return a privacy-reduced command family without argument values."""
    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        parts = command.strip().split()
    while parts and ("=" in parts[0] and not parts[0].startswith(("./", "/"))):
        parts.pop(0)
    while parts and parts[0] in {"sudo", "env", "command", "time"}:
        parts.pop(0)
    if not parts:
        return "unknown"
    first = Path(parts[0]).name
    if first in {"python", "python3"} and len(parts) >= 3 and parts[1] == "-m":
        return " ".join((first, "-m", Path(parts[2]).name))
    if first in {"npm", "pnpm", "yarn", "bun"} and len(parts) >= 3 and parts[1] == "run":
        return " ".join((first, "run", parts[2]))
    if first in {"git", "cargo", "go", "docker", "kubectl", "gh", "pytest", "ruff", "uv", "pip", "pip3", "npx"}:
        return " ".join([first, *parts[1:2]])
    return first


def _result_text(result: object) -> str:
    """Extract the text-bearing portion of one transcript tool result."""
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)
    parts = []
    for key in ("stdout", "stderr", "content", "output", "text"):
        value = result.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    return "\n".join(parts) if parts else json.dumps(result, ensure_ascii=False)


def _result_exit_code(result: object) -> int | None:
    """Return an explicit integer exit code when the transcript exposes one."""
    if not isinstance(result, dict):
        return None
    for key in ("exitCode", "exit_code", "status"):
        value = result.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _tool_result_id(record: dict, message: dict, known: dict[str, tuple[str, str]]) -> str | None:
    """Resolve the tool-use id associated with one transcript result record."""
    for block in message.get("content") or []:
        if not isinstance(block, dict):
            continue
        uid = block.get("tool_use_id") or block.get("toolUseId")
        if uid in known:
            return str(uid)
    uid = record.get("toolUseID") or record.get("tool_use_id")
    return str(uid) if uid in known else None


def mine_transcripts(
    paths: list[Path],
    *,
    registry: ProcessorRegistry | None = None,
    min_tokens: int = 0,
    top: int = 20,
) -> dict:
    """Aggregate Bash output cost by processor and unsupported command family."""
    if min_tokens < 0:
        raise ValueError("min_tokens must be nonnegative")
    if top <= 0:
        raise ValueError("top must be positive")
    active = registry or DEFAULT_REGISTRY
    buckets: dict[str, dict] = {}
    processor_tokens: dict[str, int] = defaultdict(int)
    sessions = 0
    calls = 0
    total_tokens = 0
    generic_tokens = 0

    for path in paths:
        known: dict[str, tuple[str, str]] = {}
        try:
            handle = path.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        sessions += 1
        with handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                message = record.get("message") or {}
                if not isinstance(message, dict):
                    message = {}
                for block in message.get("content") or []:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    uid = block.get("id")
                    name = block.get("name") or "unknown"
                    payload = block.get("input") or {}
                    command = payload.get("command") if isinstance(payload, dict) else None
                    if uid and name == "Bash" and isinstance(command, str):
                        known[str(uid)] = (name, command)

                result = record.get("toolUseResult")
                if result is None:
                    continue
                uid = _tool_result_id(record, message, known)
                if uid is None:
                    continue
                _name, command = known[uid]
                text = _result_text(result)
                tokens = estimate_tokens(text)
                if tokens < min_tokens:
                    continue
                failed = detect_failure(text, _result_exit_code(result))
                processor = active.select(command, failed=failed).name
                signature = command_signature(command)
                bucket = buckets.setdefault(
                    signature,
                    {
                        "signature": signature,
                        "processor": processor,
                        "calls": 0,
                        "failed_calls": 0,
                        "output_tokens": 0,
                    },
                )
                bucket["calls"] += 1
                bucket["failed_calls"] += int(failed)
                bucket["output_tokens"] += tokens
                if bucket["processor"] == "generic" and processor != "generic":
                    bucket["processor"] = processor
                processor_tokens[processor] += tokens
                total_tokens += tokens
                calls += 1
                if processor == "generic":
                    generic_tokens += tokens

    unsupported = sorted(
        (item for item in buckets.values() if item["processor"] == "generic"),
        key=lambda item: (-item["output_tokens"], -item["calls"], item["signature"]),
    )[:top]
    specialized = max(0, total_tokens - generic_tokens)
    return {
        "sessions": sessions,
        "bash_calls": calls,
        "total_output_tokens": total_tokens,
        "specialized_output_tokens": specialized,
        "generic_output_tokens": generic_tokens,
        "specialized_coverage": specialized / total_tokens if total_tokens else None,
        "processor_tokens": dict(
            sorted(processor_tokens.items(), key=lambda item: (-item[1], item[0]))
        ),
        "unsupported": unsupported,
    }
