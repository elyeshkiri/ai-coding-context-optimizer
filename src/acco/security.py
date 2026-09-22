"""Local safety policy for source discovery and context emission."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519",
    "credentials.json", "service-account.json", ".npmrc", ".pypirc",
}
# Committed-by-convention templates that document variable names, not real
# values -- real secrets are still caught by the ".env" prefix check below
# and by redact_secrets() as a backstop if one slips into a template anyway.
ENV_TEMPLATE_NAMES = {
    ".env.example", ".env.sample", ".env.template", ".env.dist",
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore"}
GENERATED_PARTS = {
    "node_modules", "vendor", "dist", "build", "coverage", ".next",
    ".nuxt", ".venv", "venv", "__pycache__",
}
SECRET_PATTERNS = (
    ("private-key", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.S
    )),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("github-token", re.compile(r"\bgh[opusr]_[A-Za-z0-9_]{30,}\b")),
    ("generic-secret", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"][^'\"\n]{8,}['\"]"
    )),
)


@dataclass(frozen=True)
class PathDecision:
    """Represent path decision state and behavior."""
    allowed: bool
    reason: str = "allowed"


def inspect_path(root: Path, path: Path) -> PathDecision:
    """Reject paths likely to expose secrets or escape the repository root."""
    try:
        resolved_root = root.resolve()
        resolved = path.resolve()
        resolved.relative_to(resolved_root)
    except (OSError, ValueError):
        return PathDecision(False, "outside-root")
    if path.is_symlink():
        return PathDecision(False, "symlink")
    rel = path.relative_to(root).as_posix()
    parts = set(Path(rel).parts)
    name = path.name.lower()
    if parts & GENERATED_PARTS:
        return PathDecision(False, "generated-or-vendor")
    if name in ENV_TEMPLATE_NAMES:
        return PathDecision(True)
    if name.startswith(".env") or name in SENSITIVE_NAMES or path.suffix.lower() in SENSITIVE_SUFFIXES:
        return PathDecision(False, "sensitive-path")
    return PathDecision(True)


def redact_secrets(text: str) -> tuple[str, list[str]]:
    """Redact high-confidence inline secrets and return their policy labels."""
    labels: list[str] = []
    out = text
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(out):
            labels.append(label)
            out = pattern.sub(f"[REDACTED:{label}]", out)
    return out, labels
