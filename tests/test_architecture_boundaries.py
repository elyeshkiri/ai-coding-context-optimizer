"""Regression tests for the explicit architecture extension seams."""

from token_saver.command_registry import CommandRegistry, CommandSpec
from token_saver.output import OutputPipeline, ProcessorRegistry
from token_saver.output_processors import OutputPipeline as CompatibilityPipeline


def test_command_registry_extends_dispatch_without_entry_changes():
    """A new command should require registration, not a new dispatcher branch."""
    seen: list[list[str]] = []

    def handler(args: list[str]) -> int:
        """Capture command arguments for the registry test."""
        seen.append(args)
        return 7

    def fallback(args: list[str]) -> int:
        """Provide an unused fallback for the registry test."""
        return 9

    registry = CommandRegistry([CommandSpec("custom", handler)])
    assert registry.dispatch(["custom", "a", "b"], fallback) == 7
    assert seen == [["a", "b"]]


def test_command_registry_rejects_duplicate_names():
    """Duplicate command names must fail during composition rather than at runtime."""
    handler = lambda args: 0
    try:
        CommandRegistry(
            [CommandSpec("same", handler), CommandSpec("same", handler)]
        )
    except ValueError as exc:
        assert "duplicate command registration" in str(exc)
    else:
        raise AssertionError("duplicate command registration was accepted")


def test_output_pipeline_accepts_injected_processors_without_core_changes():
    """Custom processors should plug into the pipeline through the contract only."""
    class CustomProcessor:
        """Small custom processor used to exercise dependency inversion."""

        name = "custom"
        priority = 1
        handles_failure = True

        def matches(self, command: str) -> bool:
            """Match the synthetic custom command."""
            return command == "custom"

        def compress(
            self,
            command: str,
            text: str,
            *,
            failed: bool,
            max_lines: int,
            keep_tail: int,
        ) -> str:
            """Return a compact deterministic representation."""
            return "summary\n"

    class GenericProcessor(CustomProcessor):
        """Fallback processor required by the registry contract."""

        name = "generic"
        priority = 999

        def matches(self, command: str) -> bool:
            """Match every command as the fallback."""
            return True

    pipeline = OutputPipeline(
        ProcessorRegistry([CustomProcessor(), GenericProcessor()])
    )
    result = pipeline.process("noise\n" * 100, "custom")
    assert result.processor == "custom"
    assert result.text == "summary\n"


def test_output_processors_module_remains_a_compatibility_facade():
    """Existing callers should receive the same pipeline type through the old module."""
    assert CompatibilityPipeline is OutputPipeline
