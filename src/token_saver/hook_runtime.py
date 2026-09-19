"""Host-neutral runtime for coding-agent hook events.

The runtime owns event policy but depends only on injected callables. Host adapters
translate their payload/configuration into :class:`HookConfig` and compose concrete
services at the edge.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .output.contracts import OutputPolicy, OutputResult

HookResponse = tuple[int, dict | None]
GuardService = Callable[[dict], HookResponse]
DeltaService = Callable[..., tuple[str, dict]]
StoreOutputService = Callable[[dict], str]
UserNudgeService = Callable[[Path, str], str | None]
ResetSessionService = Callable[..., None]
RecordReadService = Callable[..., None]
DigestService = Callable[[str], str]
EstimateTokensService = Callable[[str], int]


class OutputPipelineService(Protocol):
    """Process captured command output behind the hook runtime boundary."""

    def process(
        self,
        text: str,
        command: str = "",
        *,
        exit_code: int | None = None,
        policy: OutputPolicy | None = None,
    ) -> OutputResult:
        """Return the optimized output result for one captured command."""
        ...


DEFAULT_MIN_LINES = 40
DEFAULT_KEEP_TAIL = 15
MIN_NET_TOKENS = 50
DEFAULT_FILTERABLE_TOOLS = frozenset({"Bash"})


@dataclass(frozen=True)
class HookConfig:
    """Configure host-independent hook behavior for one invocation."""

    disabled: bool = False
    delta_enabled: bool = False
    min_lines: int = DEFAULT_MIN_LINES
    keep_tail: int = DEFAULT_KEEP_TAIL
    max_lines: int | None = None
    min_net_tokens: int = MIN_NET_TOKENS
    filterable_tools: frozenset[str] = DEFAULT_FILTERABLE_TOOLS


@dataclass(frozen=True)
class HookServices:
    """Provide side-effecting services required by :class:`HookRuntime`."""

    guard: GuardService
    output_pipeline: OutputPipelineService
    apply_delta: DeltaService
    store_output: StoreOutputService
    user_nudge: UserNudgeService
    reset_session: ResetSessionService
    record_read: RecordReadService
    digest: DigestService
    estimate_tokens: EstimateTokensService


def cap_for(n_lines: int) -> int:
    """Return the default retained-line cap for an output of ``n_lines``."""

    if n_lines >= 1000:
        return 90
    if n_lines >= 300:
        return 60
    return 30


class HookRuntime:
    """Route hook events through injected application services."""

    def __init__(self, services: HookServices, config: HookConfig | None = None):
        """Create a runtime from explicit services and optional configuration."""

        self.services = services
        self.config = config or HookConfig()

    @staticmethod
    def cwd(payload: dict) -> Path:
        """Resolve the working directory carried by a host payload."""

        raw = payload.get("cwd") or payload.get("cwd_path") or "."
        return Path(str(raw))

    @staticmethod
    def exit_code(response: dict) -> int | None:
        """Extract an integer exit code from supported host response fields."""

        for key in ("exit_code", "exitCode", "code"):
            value = response.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return None

    def run_post(self, payload: dict) -> HookResponse:
        """Process a post-tool event, replacing only beneficial Bash stdout."""

        tool = str(payload.get("tool_name") or "")
        if tool in {"Read", "Edit"} or tool not in self.config.filterable_tools:
            return 0, None

        response = payload.get("tool_response")
        if not isinstance(response, dict):
            return 0, None
        if response.get("isImage") or response.get("interrupted"):
            return 0, None
        if not isinstance(response.get("stdout"), str) or not isinstance(
            response.get("stderr"), str
        ):
            return 0, None
        if not isinstance(response.get("interrupted"), bool) or not isinstance(
            response.get("isImage"), bool
        ):
            return 0, None

        command = str((payload.get("tool_input") or {}).get("command", ""))
        replacement = dict(response)
        original = response["stdout"]
        n_lines = len(original.splitlines())
        min_lines = max(1, self.config.min_lines)
        keep_tail = max(0, self.config.keep_tail)

        if n_lines < min_lines:
            if not self.config.delta_enabled:
                return 0, None
            replacement["stdout"], _delta_meta = self.services.apply_delta(
                self.cwd(payload),
                command,
                original,
                original,
                session_id=payload.get("session_id"),
            )
            if replacement["stdout"] == original:
                return 0, None
        else:
            max_lines = self.config.max_lines
            if max_lines is None:
                max_lines = cap_for(n_lines)
            output_result = self.services.output_pipeline.process(
                original,
                command,
                exit_code=self.exit_code(response),
                policy=OutputPolicy(
                    max_lines=max(1, max_lines),
                    keep_tail=keep_tail,
                ),
            )
            replacement["stdout"] = output_result.text
            if self.config.delta_enabled:
                replacement["stdout"], _delta_meta = self.services.apply_delta(
                    self.cwd(payload),
                    command,
                    original,
                    replacement["stdout"],
                    session_id=payload.get("session_id"),
                )

        note = (
            "\n[token-saver: filtered output; original saved. "
            "Retrieve: token-saver output {id} --stream stdout --offset 1 --limit 80]\n"
        )
        candidate = replacement["stdout"] + note.format(id="0" * 32)
        if (
            self.services.estimate_tokens(original)
            - self.services.estimate_tokens(candidate)
            < self.config.min_net_tokens
        ):
            return 0, None
        if len(candidate.encode()) >= len(original.encode()):
            return 0, None

        output_id = self.services.store_output(response)
        replacement["stdout"] += note.format(id=output_id)
        return 0, {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "updatedToolOutput": replacement,
            }
        }

    def run_session_start(self, payload: dict) -> HookResponse:
        """Reset session-scoped state without injecting model context."""

        root = self.cwd(payload)
        source = str(payload.get("source") or "").lower()
        new_convo = source in {"", "startup", "clear", "compact"}
        self.services.reset_session(
            root,
            reads=new_convo,
            reminder=True,
            session_id=payload.get("session_id"),
        )
        return 0, None

    def run_user_prompt(self, payload: dict) -> HookResponse:
        """Return a policy nudge for a user prompt when the service provides one."""

        root = self.cwd(payload)
        prompt = str(payload.get("prompt") or payload.get("user_prompt") or "")
        note = self.services.user_nudge(root, prompt)
        return (0, {"systemMessage": note}) if note else (0, None)

    def run_post_read(self, payload: dict) -> None:
        """Record a verified full-file read while ignoring ranged reads."""

        tool_input = payload.get("tool_input") or {}
        if not isinstance(tool_input, dict):
            return
        if any(
            key in tool_input for key in ("offset", "limit", "start_line", "end_line")
        ):
            return
        raw = (
            tool_input.get("file_path")
            or tool_input.get("path")
            or tool_input.get("filePath")
        )
        if not raw:
            return

        path = Path(str(raw))
        if not path.is_absolute():
            path = self.cwd(payload) / path
        if not path.is_file():
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return

        response = payload.get("tool_response")
        info = response.get("file") if isinstance(response, dict) else None
        if not isinstance(info, dict) or info.get("content") != text:
            return

        self.services.record_read(
            self.cwd(payload),
            path,
            self.services.digest(text),
            session_id=payload.get("session_id"),
        )

    def run(self, payload: dict) -> HookResponse:
        """Route one normalized hook payload to the appropriate service."""

        if self.config.disabled:
            return 0, None

        event = payload.get("hook_event_name") or payload.get("hookEventName") or ""
        if event == "SessionStart":
            return self.run_session_start(payload)
        if event == "UserPromptSubmit":
            return self.run_user_prompt(payload)
        if event == "PreToolUse" or (
            not event
            and payload.get("tool_name") == "Read"
            and "tool_response" not in payload
        ):
            return self.services.guard(payload)
        if event == "PostToolUse" and payload.get("tool_name") == "Read":
            self.run_post_read(payload)
            return 0, None
        return self.run_post(payload)
