"""Stable in-process SDK for embedding ACCO in custom Python agents."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .context_router import route_context
from .estimate import estimate_tokens
from .model_routing import route_task
from .output import OutputPolicy, OutputPipeline
from .provider_transform import transform_provider_request
from .recovery import DEFAULT_CAPACITY_BYTES, RecoveryCapacityError, RecoveryStore


@dataclass(frozen=True)
class AccoSdkConfig:
    """Configure one in-process ACCO SDK engine."""

    root: Path
    recovery_capacity_bytes: int = DEFAULT_CAPACITY_BYTES

    def validate(self) -> AccoSdkConfig:
        """Validate and normalize the SDK configuration."""
        root = Path(self.root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"SDK root must be an existing directory: {root}")
        if self.recovery_capacity_bytes <= 0:
            raise ValueError("recovery_capacity_bytes must be positive")
        return AccoSdkConfig(
            root=root,
            recovery_capacity_bytes=int(self.recovery_capacity_bytes),
        )


class AccoEngine:
    """Expose ACCO optimization primitives to framework-neutral Python agents."""

    def __init__(
        self,
        root: str | Path = ".",
        *,
        recovery_capacity_bytes: int = DEFAULT_CAPACITY_BYTES,
    ):
        """Create one project-scoped engine with shared exact-recovery storage."""
        config = AccoSdkConfig(
            Path(root),
            recovery_capacity_bytes=recovery_capacity_bytes,
        ).validate()
        self.root = config.root
        self.recovery_capacity_bytes = config.recovery_capacity_bytes
        self.recovery = RecoveryStore(
            self.root,
            capacity_bytes=self.recovery_capacity_bytes,
        )
        self.output_pipeline = OutputPipeline()

    def optimize_provider_request(
        self,
        provider: str,
        body: dict,
        *,
        request_path: str = "",
        compress_schemas: bool = True,
        compress_tool_results: bool = True,
        tool_result_min_tokens: int = 800,
        prefix_tracking: bool = True,
    ) -> dict[str, Any]:
        """Optimize one provider request while keeping exact recovery available."""
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider must be a nonempty string")
        result = transform_provider_request(
            self.root,
            provider.strip(),
            body,
            request_path=request_path,
            compress_schemas=compress_schemas,
            compress_tool_results=compress_tool_results,
            tool_result_min_tokens=tool_result_min_tokens,
            recovery_capacity_bytes=self.recovery_capacity_bytes,
            prefix_tracking=prefix_tracking,
        )
        return {
            "schema": 1,
            "body": result.body,
            "metadata": result.metadata(),
        }

    def optimize_context(
        self,
        text: str,
        *,
        query: str = "",
        command: str = "",
        max_lines: int = 120,
        min_reduction: float = 0.08,
    ) -> dict[str, Any]:
        """Compress arbitrary agent/tool context with exact-source recovery."""
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        result = route_context(
            text,
            query=query,
            recovery=self.recovery,
            command=command,
            max_lines=max_lines,
            min_reduction=min_reduction,
        )
        return {"schema": 1, **result.to_dict()}

    def optimize_output(
        self,
        text: str,
        *,
        command: str = "",
        exit_code: int | None = None,
        max_lines: int = 80,
        keep_tail: int = 20,
        min_reduction: float = 0.02,
        recoverable: bool = True,
    ) -> dict[str, Any]:
        """Optimize command output and optionally persist the exact original."""
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        if max_lines <= 0:
            raise ValueError("max_lines must be positive")
        if keep_tail < 0:
            raise ValueError("keep_tail must be nonnegative")
        if not 0 <= min_reduction < 1:
            raise ValueError("min_reduction must be in [0, 1)")
        result = self.output_pipeline.process(
            text,
            command,
            exit_code=exit_code,
            policy=OutputPolicy(
                max_lines=max_lines,
                keep_tail=keep_tail,
                min_reduction=min_reduction,
            ),
        )
        original_tokens = estimate_tokens(text)
        candidate = result.text
        recovery_handle = None
        if result.compressed and recoverable:
            try:
                recovery_handle = self.recovery.put(
                    text,
                    content_type="text/plain",
                    metadata={
                        "transform": "sdk-output",
                        "processor": result.processor,
                    },
                )
            except RecoveryCapacityError:
                candidate = text
                recovery_handle = None
        changed = candidate != text
        output_tokens = estimate_tokens(candidate)
        return {
            "schema": 1,
            "text": candidate,
            "processor": result.processor,
            "changed": changed,
            "compressed": changed,
            "failed": result.failed,
            "recovered_lines": list(result.recovered_lines) if changed else [],
            "original_tokens": original_tokens,
            "output_tokens": output_tokens if changed else original_tokens,
            "recovery_handle": recovery_handle,
        }

    def route_model(
        self,
        prompt: str,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        current_model: str | None = None,
        allowed_models: list[str] | tuple[str, ...] | None = None,
        min_savings: float = 0.05,
        conservative: bool = True,
        task_override: str | None = None,
        calibration: dict | None = None,
    ) -> dict[str, Any]:
        """Return ACCO's deterministic model-routing decision as JSON-safe data."""
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a nonempty string")
        return route_task(
            prompt,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            current_model=current_model,
            allowed_models=allowed_models,
            min_savings=min_savings,
            conservative=conservative,
            task_override=task_override,
            calibration=calibration,
        ).to_dict()

    def recover(self, handle: str) -> dict[str, Any]:
        """Recover exact stored bytes using a content-addressed recovery handle."""
        record = self.recovery.get(handle)
        try:
            text = record.payload.decode("utf-8")
            payload = text
            encoding = "utf-8"
        except UnicodeDecodeError:
            payload = base64.b64encode(record.payload).decode("ascii")
            encoding = "base64"
        return {
            "schema": 1,
            "handle": record.handle,
            "content_type": record.content_type,
            "encoding": encoding,
            "payload": payload,
            "size_bytes": record.size_bytes,
            "metadata": record.metadata,
            "created_at": record.created_at,
            "last_accessed_at": record.last_accessed_at,
            "access_count": record.access_count,
        }

    def middleware(self, provider: str) -> AccoMiddleware:
        """Create a provider-bound middleware facade for a custom agent."""
        return AccoMiddleware(self, provider=provider)


class AccoMiddleware:
    """Framework-neutral before-request/after-tool middleware facade."""

    def __init__(self, engine: AccoEngine, *, provider: str):
        """Bind middleware calls to one provider identity."""
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider must be a nonempty string")
        self.engine = engine
        self.provider = provider.strip()

    def before_request(self, body: dict, **options: Any) -> dict[str, Any]:
        """Optimize one provider-bound model request before it is sent."""
        return self.engine.optimize_provider_request(
            self.provider,
            body,
            **options,
        )

    def after_tool_result(
        self,
        text: str,
        *,
        query: str = "",
        command: str = "",
        max_lines: int = 120,
        min_reduction: float = 0.08,
    ) -> dict[str, Any]:
        """Optimize one tool result before adding it back to agent context."""
        return self.engine.optimize_context(
            text,
            query=query,
            command=command,
            max_lines=max_lines,
            min_reduction=min_reduction,
        )

    def route(self, prompt: str, **options: Any) -> dict[str, Any]:
        """Return a model route decision for an orchestrator-controlled turn."""
        return self.engine.route_model(prompt, **options)

    def recover(self, handle: str) -> dict[str, Any]:
        """Recover exact source bytes for a prior middleware transform."""
        return self.engine.recover(handle)
