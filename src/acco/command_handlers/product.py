"""CLI adapters for ACCO's beginner-facing product UX."""

from __future__ import annotations

from ..product_ux import (
    advanced_main as _advanced_main,
    bootstrap_main as _bootstrap_main,
    demo_main as _demo_main,
    savings_main as _savings_main,
    start_main as _start_main,
    status_main as _status_main,
    update_main as _update_main,
)


def bootstrap_main(argv: list[str]) -> int:
    """Persistently install ACCO and run safe project setup."""
    return _bootstrap_main(argv)


def start_main(argv: list[str]) -> int:
    """Launch the detected or selected coding agent through ACCO."""
    return _start_main(argv)


def status_main(argv: list[str]) -> int:
    """Show simplified ACCO project health and efficiency telemetry."""
    return _status_main(argv)


def demo_main(argv: list[str]) -> int:
    """Run the provider-free local repository-context demonstration."""
    return _demo_main(argv)


def savings_main(argv: list[str]) -> int:
    """Summarize locally observed ACCO context-reduction evidence."""
    return _savings_main(argv)


def update_main(argv: list[str]) -> int:
    """Inspect or apply ACCO's package-manager-aware upgrade."""
    return _update_main(argv)


def advanced_main(argv: list[str]) -> int:
    """List the complete expert ACCO command surface."""
    return _advanced_main(argv)
