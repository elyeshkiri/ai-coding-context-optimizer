"""Unified setup, detection, doctor, and uninstall for coding-agent integrations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Callable

from .config import update_json
from .install import HOOK_COMMAND, install as install_claude_hooks
from .install import settings_path as claude_settings_path
from .install import uninstall as uninstall_claude_hooks
from .repository_service import RepositoryContextService
from .runtime_config import CONFIG_NAME, find_project_config, settings_for
from .sessions import transcript_paths

HOSTS = ("claude", "cursor", "codex")
CODEX_START = "# >>> token-saver managed >>>"
CODEX_END = "# <<< token-saver managed <<<"

DEFAULT_CONFIG = """version = 1

[hooks]
guard = true
read_max_lines = 220
reread = false
delta = false
min_lines = 40
keep_tail = 15
allow = []
"""


@dataclass(frozen=True)
class HostStatus:
    """Installation/configuration state for one supported host."""

    name: str
    detected: bool
    configured: bool
    executable: str | None
    config_paths: tuple[str, ...]
    details: tuple[str, ...] = ()


def _atomic_write(path: Path, text: str) -> None:
    """Atomically replace one UTF-8 text file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _mcp_entry(root: Path) -> dict:
    """Return the project-scoped MCP server definition."""
    return {"command": "token-saver", "args": ["serve", str(root.resolve())]}


def _merge_mcp(root: Path) -> Callable[[dict], dict]:
    """Return a JSON mutator that owns only the Token Saver MCP entry."""
    def mutate(current: dict) -> dict:
        updated = dict(current)
        servers = dict(updated.get("mcpServers", {}))
        servers["token-saver"] = _mcp_entry(root)
        updated["mcpServers"] = servers
        return updated

    return mutate


def _remove_mcp(current: dict) -> dict:
    """Remove only the Token Saver MCP entry from a JSON config."""
    updated = dict(current)
    servers = updated.get("mcpServers")
    if not isinstance(servers, dict):
        return updated
    servers = dict(servers)
    servers.pop("token-saver", None)
    if servers:
        updated["mcpServers"] = servers
    else:
        updated.pop("mcpServers", None)
    return updated


def _json_mcp_configured(path: Path) -> bool:
    """Return whether a JSON config contains Token Saver MCP."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    servers = payload.get("mcpServers") if isinstance(payload, dict) else None
    return isinstance(servers, dict) and "token-saver" in servers


def claude_mcp_path(root: Path) -> Path:
    """Return Claude Code project MCP configuration path."""
    return root / ".mcp.json"


def cursor_mcp_path(root: Path) -> Path:
    """Return Cursor project MCP configuration path."""
    return root / ".cursor" / "mcp.json"


def codex_config_path(home: Path | None = None) -> Path:
    """Return Codex user configuration path."""
    return (home or Path.home()) / ".codex" / "config.toml"


def _codex_block() -> str:
    """Return the managed Codex MCP configuration block."""
    return (
        f"{CODEX_START}\n"
        "[mcp_servers.token-saver]\n"
        'command = "token-saver"\n'
        'args = ["serve", "."]\n'
        f"{CODEX_END}\n"
    )


def _strip_codex_block(text: str) -> str:
    """Remove the Token Saver managed block while preserving all other TOML."""
    start = text.find(CODEX_START)
    if start < 0:
        return text
    end = text.find(CODEX_END, start)
    if end < 0:
        raise ValueError("Codex Token Saver managed block is incomplete")
    end += len(CODEX_END)
    while end < len(text) and text[end] in "\r\n":
        end += 1
    return (text[:start].rstrip() + "\n" + text[end:].lstrip()).lstrip("\n")


def _install_codex(path: Path) -> None:
    """Install or refresh the marked Codex MCP block."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    unmanaged = "[mcp_servers.token-saver]" in existing and CODEX_START not in existing
    if unmanaged:
        raise ValueError(
            f"Refusing to replace unmanaged Token Saver Codex config: {path}"
        )
    cleaned = _strip_codex_block(existing).rstrip()
    text = (cleaned + "\n\n" if cleaned else "") + _codex_block()
    _atomic_write(path, text)


def _uninstall_codex(path: Path) -> None:
    """Remove the marked Codex MCP block only."""
    if not path.exists():
        return
    existing = path.read_text(encoding="utf-8")
    cleaned = _strip_codex_block(existing)
    if cleaned == existing:
        return
    _atomic_write(path, cleaned)


def _claude_hooks_configured(root: Path) -> bool:
    """Return whether project Claude settings contain Token Saver hooks."""
    path = claude_settings_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    hooks = payload.get("hooks") if isinstance(payload, dict) else None
    if not isinstance(hooks, dict):
        return False
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for command in entry.get("hooks", []):
                if isinstance(command, dict) and command.get("command") == HOOK_COMMAND:
                    return True
    return False


def detect_hosts(
    root: Path,
    *,
    home: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> list[HostStatus]:
    """Detect supported hosts and whether Token Saver is already configured."""
    root = root.resolve()
    home = home or Path.home()
    executable = {name: which(name) for name in HOSTS}
    claude_paths = (claude_settings_path(root), claude_mcp_path(root))
    cursor_path = cursor_mcp_path(root)
    codex_path = codex_config_path(home)
    codex_text = codex_path.read_text(encoding="utf-8") if codex_path.exists() else ""
    return [
        HostStatus(
            "claude",
            bool(executable["claude"] or (home / ".claude").exists()),
            _claude_hooks_configured(root) and _json_mcp_configured(claude_paths[1]),
            executable["claude"],
            tuple(str(path) for path in claude_paths),
            ("hooks", "mcp"),
        ),
        HostStatus(
            "cursor",
            bool(executable["cursor"] or (home / ".cursor").exists() or (root / ".cursor").exists()),
            _json_mcp_configured(cursor_path),
            executable["cursor"],
            (str(cursor_path),),
            ("mcp",),
        ),
        HostStatus(
            "codex",
            bool(executable["codex"] or (home / ".codex").exists()),
            CODEX_START in codex_text and CODEX_END in codex_text,
            executable["codex"],
            (str(codex_path),),
            ("mcp",),
        ),
    ]


def write_default_config(root: Path) -> Path:
    """Create project configuration if it does not already exist."""
    path = root.resolve() / CONFIG_NAME
    if not path.exists():
        _atomic_write(path, DEFAULT_CONFIG)
    return path


def setup_integrations(
    root: Path,
    hosts: tuple[str, ...] | None = None,
    *,
    home: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> dict:
    """Configure detected or explicitly requested hosts idempotently."""
    root = root.resolve()
    home = home or Path.home()
    detected = detect_hosts(root, home=home, which=which)
    if hosts:
        requested = HOSTS if "all" in hosts else tuple(dict.fromkeys(hosts))
    else:
        requested = tuple(item.name for item in detected if item.detected)
    unknown = sorted(set(requested) - set(HOSTS))
    if unknown:
        raise ValueError(f"Unsupported host(s): {', '.join(unknown)}")

    changed: list[str] = []
    config_path = write_default_config(root)
    if "claude" in requested:
        install_claude_hooks(root, templates=True)
        update_json(claude_mcp_path(root), _merge_mcp(root))
        changed.append("claude")
    if "cursor" in requested:
        update_json(cursor_mcp_path(root), _merge_mcp(root))
        changed.append("cursor")
    if "codex" in requested:
        _install_codex(codex_config_path(home))
        changed.append("codex")

    return {
        "root": str(root),
        "config": str(config_path),
        "requested_hosts": list(requested),
        "configured_hosts": changed,
        "detected": [asdict(item) for item in detect_hosts(root, home=home, which=which)],
    }


def uninstall_integrations(
    root: Path,
    hosts: tuple[str, ...] | None = None,
    *,
    home: Path | None = None,
    remove_config: bool = False,
) -> dict:
    """Remove only Token Saver-owned integration entries."""
    root = root.resolve()
    home = home or Path.home()
    requested = HOSTS if not hosts or "all" in hosts else tuple(dict.fromkeys(hosts))
    unknown = sorted(set(requested) - set(HOSTS))
    if unknown:
        raise ValueError(f"Unsupported host(s): {\', \'.join(unknown)}")
    removed: list[str] = []
    if "claude" in requested:
        uninstall_claude_hooks(root)
        path = claude_mcp_path(root)
        if path.exists():
            update_json(path, _remove_mcp)
        removed.append("claude")
    if "cursor" in requested:
        path = cursor_mcp_path(root)
        if path.exists():
            update_json(path, _remove_mcp)
        removed.append("cursor")
    if "codex" in requested:
        _uninstall_codex(codex_config_path(home))
        removed.append("codex")
    config = root / CONFIG_NAME
    if remove_config and config.exists():
        config.unlink()
    return {"root": str(root), "removed_hosts": removed, "config_removed": remove_config}


def _version() -> str:
    """Return installed package version with a source-checkout fallback."""
    try:
        return metadata.version("claude-token-saver")
    except metadata.PackageNotFoundError:
        from . import __version__

        return __version__


def doctor_report(
    root: Path,
    *,
    home: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
    index: bool = True,
) -> dict:
    """Build a consolidated health report for installation and integrations."""
    root = root.resolve()
    home = home or Path.home()
    config_path = find_project_config(root)
    config_error = None
    try:
        runtime = asdict(settings_for(root))
    except ValueError as exc:
        runtime = None
        config_error = str(exc)
    index_status = None
    index_error = None
    if index:
        try:
            index_status = RepositoryContextService(root).status()
        except (OSError, ValueError) as exc:
            index_error = str(exc)
    hosts = detect_hosts(root, home=home, which=which)
    transcripts = len(transcript_paths(root))
    executable = which("token-saver")
    ready_hosts = [item.name for item in hosts if item.configured]
    detected_hosts = [item.name for item in hosts if item.detected]
    ready = bool(executable and ready_hosts and not config_error and not index_error)
    return {
        "ready": ready,
        "version": _version(),
        "token_saver_executable": executable,
        "root": str(root),
        "config_path": str(config_path) if config_path else None,
        "config_error": config_error,
        "runtime": runtime,
        "detected_hosts": detected_hosts,
        "configured_hosts": ready_hosts,
        "hosts": [asdict(item) for item in hosts],
        "index": index_status,
        "index_error": index_error,
        "claude_transcripts": transcripts,
    }
