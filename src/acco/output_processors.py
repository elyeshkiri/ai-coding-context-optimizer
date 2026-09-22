"""Compatibility facade for the composable :mod:`token_saver.output` package.

New code should depend on ``token_saver.output`` contracts or ``OutputPipeline``.
This module preserves the pre-1.4 public import surface for callers and plugins.
"""

from .output import (
    DEFAULT_REGISTRY,
    ERROR_HINTS,
    GenericProcessor,
    GitLogProcessor,
    JsTestProcessor,
    OutputPipeline,
    OutputPolicy,
    OutputProcessor,
    OutputResult,
    PackageInstallProcessor,
    ProcessorRegistry,
    PytestProcessor,
    detect_failure,
    explain_processor,
    filter_text,
    preprocess,
    process_output,
    recover_critical_lines,
)

__all__ = [
    "DEFAULT_REGISTRY",
    "ERROR_HINTS",
    "GenericProcessor",
    "GitLogProcessor",
    "JsTestProcessor",
    "OutputPipeline",
    "OutputPolicy",
    "OutputProcessor",
    "OutputResult",
    "PackageInstallProcessor",
    "ProcessorRegistry",
    "PytestProcessor",
    "detect_failure",
    "explain_processor",
    "filter_text",
    "preprocess",
    "process_output",
    "recover_critical_lines",
]
