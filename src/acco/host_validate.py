"""Validate that ACCO's host integration is installed and functional.

This command deliberately separates three facts that are often conflated:
configuration is present, the hook transport works locally, and a real host has
actually accepted replacement output. The first two can be tested locally; the
third is reported only when caller-supplied host debug evidence contains the
expected replacement marker.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from .hook import run_post
from .install import HOOK_COMMAND, settings_path, user_settings_path
from .output_store import retrieve

_OUTPUT_ID = re.compile(r"acco output ([0-9a-f]{32})")
_REQUIRED_EVENTS = {"PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit"}


def _version(executable: str) -> dict[str, Any]:
    """Handle version."""
    path = shutil.which(executable)
    if not path:
        return {"found": False, "path": None, "version": None}
    try:
        proc = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=5, check=False
        )
        version = (proc.stdout or proc.stderr).strip().splitlines()
        return {
            "found": True,
            "path": path,
            "version": version[0] if version else None,
            "returncode": proc.returncode,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "found": True,
            "path": path,
            "version": None,
            "error": type(exc).__name__,
        }


def _settings_status(path: Path) -> dict[str, Any]:
    """Handle settings status."""
    if not path.is_file():
        return {
            "path": str(path), "exists": False,
            "configured_events": [], "complete": False,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "path": str(path), "exists": True, "error": type(exc).__name__,
            "configured_events": [], "complete": False,
        }
    hooks = payload.get("hooks", {}) if isinstance(payload, dict) else {}
    configured: list[str] = []
    if isinstance(hooks, dict):
        for event, entries in hooks.items():
            if not isinstance(entries, list):
                continue
            found = False
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                for hook in entry.get("hooks", []):
                    if isinstance(hook, dict) and hook.get("command") == HOOK_COMMAND:
                        found = True
                        break
                if found:
                    break
            if found:
                configured.append(str(event))
    return {
        "path": str(path),
        "exists": True,
        "configured_events": sorted(configured),
        "complete": _REQUIRED_EVENTS.issubset(configured),
    }


def _transport_roundtrip() -> dict[str, Any]:
    # Distinct middle lines prove recovery uses stored original output, not the
    # compressed model-visible replacement.
    """Handle transport roundtrip."""
    original = "\n".join(
        f"progress-line-{number:04d}" for number in range(1, 501)
    ) + "\n"
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "printf progress"},
        "tool_response": {
            "stdout": original,
            "stderr": "",
            "interrupted": False,
            "isImage": False,
        },
    }
    code, response = run_post(payload)
    if code != 0 or not isinstance(response, dict):
        return {"ok": False, "reason": "hook did not produce replacement output"}
    replacement = response.get("hookSpecificOutput", {}).get("updatedToolOutput", {})
    stdout = replacement.get("stdout", "") if isinstance(replacement, dict) else ""
    match = _OUTPUT_ID.search(stdout) if isinstance(stdout, str) else None
    if not match:
        return {"ok": False, "reason": "replacement omitted recovery output id"}
    recovered = retrieve(match.group(1), "stdout", offset=250, limit=1)
    verified = recovered.strip() == "progress-line-0250"
    return {
        "ok": verified,
        "replacement_lines": len(stdout.splitlines()),
        "original_lines": 500,
        "recovery_verified": verified,
    }


def _host_evidence(path: Path | None) -> dict[str, Any]:
    """Handle host evidence."""
    if path is None:
        return {"provided": False, "accepted_replacement": None}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "provided": True, "accepted_replacement": False,
            "error": type(exc).__name__,
        }
    # Debug formats vary by host version, and a host's own debug-log
    # redaction can mangle prose inside the replacement -- observed live:
    # a real host's log sanitizer rewrote "filtered" to "[REDACTED]" in the
    # recovery note even though the replacement was genuinely accepted and
    # applied (confirmed by the host's own "replaced tool output" log line
    # alongside it). The recovery command's generated hex id is a stronger
    # signal than exact prose: nothing but ACCO produces it, and it
    # doesn't look like a credential, so generic secret-redaction leaves it
    # alone even when it rewrites the surrounding sentence.
    accepted = "updatedToolOutput" in text and bool(_OUTPUT_ID.search(text))
    return {
        "provided": True,
        "accepted_replacement": accepted,
        "path": str(path),
    }


def validate_host(
    root: Path,
    *,
    executable: str = "claude",
    live_evidence: Path | None = None,
) -> dict[str, Any]:
    """Validate host."""
    root = root.resolve()
    project = _settings_status(settings_path(root))
    user = _settings_status(user_settings_path())
    configured = bool(project.get("complete") or user.get("complete"))
    transport = _transport_roundtrip()
    host = _version(executable)
    evidence = _host_evidence(live_evidence.resolve() if live_evidence else None)
    return {
        "host": host,
        "project_settings": project,
        "user_settings": user,
        "configured": configured,
        "hook_transport": transport,
        "live_host_evidence": evidence,
        "ready": bool(configured and transport.get("ok")),
        "live_verified": evidence.get("accepted_replacement") is True,
    }
