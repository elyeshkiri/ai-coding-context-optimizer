"""Host-specific MCP configuration adapters.

These adapters keep host formats out of the integration lifecycle service. Each
mutation owns only the acco server entry and either preserves unrelated
configuration or fails closed when the host format cannot be mutated safely.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from .config import update_json

ACCO_SERVER = "acco"
HERMES_START = "  # >>> acco managed >>>"
HERMES_END = "  # <<< acco managed <<<"



def _atomic_write(path: Path, text: str) -> None:
    """Atomically replace one UTF-8 host configuration file."""
    path.parent.mkdir(parents=True, exist_ok=True)
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
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def stdio_entry(root: Path) -> dict[str, Any]:
    """Return the common stdio server definition used by JSON MCP hosts."""
    return {
        "command": "acco",
        "args": ["serve", str(root.resolve())],
    }


def _nested_json_mutator(
    *,
    path_keys: tuple[str, ...],
    entry: dict[str, Any],
) -> Callable[[dict], dict]:
    """Build a mutator that owns one nested ACCO server entry."""
    def mutate(current: dict) -> dict:
        updated = dict(current)
        cursor = updated
        for key in path_keys[:-1]:
            child = cursor.get(key)
            if child is None:
                child = {}
            if not isinstance(child, dict):
                raise ValueError(f"Expected JSON object at {'.'.join(path_keys[:-1])}")
            child = dict(child)
            cursor[key] = child
            cursor = child
        leaf = path_keys[-1]
        servers = cursor.get(leaf)
        if servers is None:
            servers = {}
        if not isinstance(servers, dict):
            raise ValueError(f"Expected JSON object at {'.'.join(path_keys)}")
        servers = dict(servers)
        servers[ACCO_SERVER] = entry
        cursor[leaf] = servers
        return updated

    return mutate


def _nested_json_remove(path_keys: tuple[str, ...]) -> Callable[[dict], dict]:
    """Build a mutator that removes only ACCO from a nested server map."""
    def mutate(current: dict) -> dict:
        updated = dict(current)
        cursor = updated
        parents: list[tuple[dict, str]] = []
        for key in path_keys[:-1]:
            child = cursor.get(key)
            if not isinstance(child, dict):
                return updated
            child = dict(child)
            cursor[key] = child
            parents.append((cursor, key))
            cursor = child
        leaf = path_keys[-1]
        servers = cursor.get(leaf)
        if not isinstance(servers, dict):
            return updated
        servers = dict(servers)
        servers.pop(ACCO_SERVER, None)
        if servers:
            cursor[leaf] = servers
        else:
            cursor.pop(leaf, None)
        for parent, key in reversed(parents):
            child = parent.get(key)
            if isinstance(child, dict) and not child:
                parent.pop(key, None)
        return updated

    return mutate


def _nested_json_configured(path: Path, path_keys: tuple[str, ...]) -> bool:
    """Return whether one strict-JSON host config contains ACCO MCP."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    cursor: object = payload
    for key in path_keys:
        if not isinstance(cursor, dict):
            return False
        cursor = cursor.get(key)
    return isinstance(cursor, dict) and ACCO_SERVER in cursor


def opencode_mcp_path(root: Path) -> Path:
    """Return ACCO's project-local OpenCode configuration path."""
    return root.resolve() / ".opencode" / "opencode.json"


def opencode_jsonc_path(root: Path) -> Path:
    """Return the sibling OpenCode JSONC path that can create precedence ambiguity."""
    return root.resolve() / ".opencode" / "opencode.jsonc"


def opencode_configured(root: Path) -> bool:
    """Return whether ACCO is configured in the managed OpenCode JSON layer."""
    return _nested_json_configured(opencode_mcp_path(root), ("mcp", "servers"))


def validate_opencode_manageable(root: Path) -> None:
    """Refuse ambiguous sibling OpenCode project config ownership."""
    path = opencode_mcp_path(root)
    sibling = opencode_jsonc_path(root)
    if sibling.exists() and not path.exists():
        raise ValueError(
            "Refusing to create .opencode/opencode.json beside existing "
            ".opencode/opencode.jsonc; configure ACCO in one OpenCode "
            "project config to avoid ambiguous precedence."
        )


def install_opencode(root: Path) -> None:
    """Install the project-local OpenCode MCP entry without touching root config."""
    path = opencode_mcp_path(root)
    validate_opencode_manageable(root)
    entry = {
        "type": "local",
        "command": ["acco", "serve", str(root.resolve())],
    }
    update_json(
        path,
        _nested_json_mutator(path_keys=("mcp", "servers"), entry=entry),
    )


def uninstall_opencode(root: Path) -> None:
    """Remove only the ACCO OpenCode MCP entry."""
    path = opencode_mcp_path(root)
    if path.exists():
        update_json(path, _nested_json_remove(("mcp", "servers")))


def copilot_mcp_path(root: Path) -> Path:
    """Return VS Code/Copilot workspace MCP configuration path."""
    return root.resolve() / ".vscode" / "mcp.json"


def copilot_cli_config_path(home: Path | None = None) -> Path:
    """Return GitHub Copilot CLI's user MCP registry path."""
    override = os.environ.get("COPILOT_HOME", "").strip()
    base = Path(override).expanduser() if override else (home or Path.home()) / ".copilot"
    return base / "mcp-config.json"


def _copilot_cli_entry(home: Path | None = None) -> dict[str, Any] | None:
    """Return the configured Copilot CLI ACCO entry when readable."""
    path = copilot_cli_config_path(home)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    servers = payload.get("mcpServers") if isinstance(payload, dict) else None
    entry = servers.get(ACCO_SERVER) if isinstance(servers, dict) else None
    return entry if isinstance(entry, dict) else None


def copilot_cli_configured(home: Path | None = None) -> bool:
    """Return whether Copilot CLI contains ACCO's managed dynamic entry."""
    entry = _copilot_cli_entry(home)
    if not entry:
        return False
    return (
        entry.get("command") == "acco"
        and entry.get("args") == ["serve", "."]
    )


def validate_copilot_cli_manageable(home: Path | None = None) -> None:
    """Refuse to replace a user-owned Copilot CLI server with the same name."""
    path = copilot_cli_config_path(home)
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"Refusing invalid Copilot CLI MCP JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    servers = payload.get("mcpServers")
    if not isinstance(servers, dict) or ACCO_SERVER not in servers:
        return
    if not copilot_cli_configured(home):
        raise ValueError(
            f"Refusing to replace unmanaged Copilot CLI ACCO config: {path}"
        )


def copilot_vscode_configured(root: Path) -> bool:
    """Return whether VS Code/Copilot workspace MCP contains ACCO."""
    return _nested_json_configured(copilot_mcp_path(root), ("servers",))


def copilot_configured(
    root: Path,
    *,
    home: Path | None = None,
    cli_required: bool = False,
    vscode_required: bool = False,
) -> bool:
    """Return whether all installed Copilot surfaces requested by detection are ready."""
    checks = []
    if cli_required:
        checks.append(copilot_cli_configured(home))
    if vscode_required:
        checks.append(copilot_vscode_configured(root))
    if checks:
        return all(checks)
    return copilot_cli_configured(home) or copilot_vscode_configured(root)


def install_copilot_vscode(root: Path) -> None:
    """Install ACCO into VS Code's workspace MCP server map."""
    update_json(
        copilot_mcp_path(root),
        _nested_json_mutator(
            path_keys=("servers",),
            entry=stdio_entry(root),
        ),
    )


def uninstall_copilot_vscode(root: Path) -> None:
    """Remove only the ACCO VS Code/Copilot MCP entry."""
    path = copilot_mcp_path(root)
    if path.exists():
        update_json(path, _nested_json_remove(("servers",)))


def install_copilot_cli(
    *,
    home: Path | None = None,
    runner: RunCommand,
) -> None:
    """Install the dynamic ACCO server through Copilot CLI's native registry."""
    validate_copilot_cli_manageable(home)
    if copilot_cli_configured(home):
        return
    runner([
        "copilot",
        "mcp",
        "add",
        "--tools",
        "*",
        ACCO_SERVER,
        "--",
        "acco",
        "serve",
        ".",
    ])


def uninstall_copilot_cli(
    *,
    home: Path | None = None,
    runner: RunCommand,
) -> None:
    """Remove only ACCO's owned Copilot CLI user-level MCP entry."""
    validate_copilot_cli_manageable(home)
    if copilot_cli_configured(home):
        runner(["copilot", "mcp", "remove", ACCO_SERVER])


def antigravity_mcp_path(root: Path) -> Path:
    """Return Antigravity workspace-local MCP profile path."""
    return root.resolve() / ".agents" / "mcp_config.json"


def antigravity_global_mcp_path(home: Path | None = None) -> Path:
    """Return Antigravity's documented global MCP profile path."""
    return (home or Path.home()) / ".gemini" / "config" / "mcp_config.json"


def antigravity_configured(root: Path) -> bool:
    """Return whether the workspace-local Antigravity profile contains ACCO."""
    return _nested_json_configured(antigravity_mcp_path(root), ("mcpServers",))


def install_antigravity(root: Path) -> None:
    """Install ACCO into Antigravity's workspace-local MCP profile."""
    update_json(
        antigravity_mcp_path(root),
        _nested_json_mutator(
            path_keys=("mcpServers",),
            entry=stdio_entry(root),
        ),
    )


def uninstall_antigravity(root: Path) -> None:
    """Remove only the ACCO Antigravity MCP entry."""
    path = antigravity_mcp_path(root)
    if path.exists():
        update_json(path, _nested_json_remove(("mcpServers",)))


def hermes_config_path(home: Path | None = None) -> Path:
    """Return Hermes Agent's user configuration path."""
    return (home or Path.home()) / ".hermes" / "config.yaml"


def _strip_hermes_block(text: str) -> str:
    """Remove ACCO's marked Hermes YAML block."""
    start = text.find(HERMES_START)
    if start < 0:
        return text
    end = text.find(HERMES_END, start)
    if end < 0:
        raise ValueError("Hermes ACCO managed block is incomplete")
    end += len(HERMES_END)
    while end < len(text) and text[end] in "\r\n":
        end += 1
    return text[:start] + text[end:]


def _hermes_unmanaged_entry(text: str) -> bool:
    """Detect an existing unowned acco entry under top-level mcp_servers."""
    if HERMES_START in text:
        return False
    lines = text.splitlines()
    in_mcp = False
    for line in lines:
        if re.match(r"^mcp_servers:\s*(?:#.*)?$", line):
            in_mcp = True
            continue
        if in_mcp and line and not line.startswith((" ", "\t", "#")):
            in_mcp = False
        if in_mcp and re.match(r"^\s{2}acco:\s*(?:#.*)?$", line):
            return True
    return False


def validate_hermes_manageable(path: Path) -> None:
    """Fail closed for malformed or user-owned Hermes ACCO entries."""
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if (HERMES_START in text) != (HERMES_END in text):
        raise ValueError("Hermes ACCO managed block is incomplete")
    if _hermes_unmanaged_entry(text):
        raise ValueError(
            f"Refusing to replace unmanaged Hermes ACCO config: {path}"
        )
    all_roots = [
        line for line in text.splitlines()
        if re.match(r"^mcp_servers\s*:", line)
    ]
    roots = [
        line for line in all_roots
        if re.match(r"^mcp_servers:\s*(?:#.*)?$", line)
    ]
    if len(all_roots) > 1:
        raise ValueError(f"Refusing ambiguous duplicate mcp_servers keys: {path}")
    if all_roots and not roots:
        raise ValueError(
            f"Refusing unsupported inline/complex mcp_servers YAML shape: {path}"
        )


def _hermes_entry(root: Path) -> str:
    """Render the managed Hermes YAML entry with a JSON-compatible quoted path."""
    target = json.dumps(str(root.resolve()))
    return (
        f"{HERMES_START}\n"
        "  acco:\n"
        '    command: "acco"\n'
        "    args:\n"
        '      - "serve"\n'
        f"      - {target}\n"
        "    enabled: true\n"
        f"{HERMES_END}\n"
    )


def install_hermes(root: Path, home: Path | None = None) -> None:
    """Install a conservative managed block in Hermes config.yaml."""
    path = hermes_config_path(home)
    validate_hermes_manageable(path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    text = _strip_hermes_block(text)
    entry = _hermes_entry(root)
    lines = text.splitlines(keepends=True)
    root_indexes = [
        index for index, line in enumerate(lines)
        if re.match(r"^mcp_servers:\s*(?:#.*)?(?:\r?\n)?$", line)
    ]
    if root_indexes:
        index = root_indexes[0] + 1
        if not lines[index - 1].endswith(("\n", "\r")):
            lines[index - 1] += "\n"
        lines.insert(index, entry)
        rendered = "".join(lines)
    else:
        base = text.rstrip()
        rendered = (base + "\n\n" if base else "") + "mcp_servers:\n" + entry
    _atomic_write(path, rendered)


def uninstall_hermes(home: Path | None = None) -> None:
    """Remove only ACCO's managed Hermes YAML block."""
    path = hermes_config_path(home)
    if not path.exists():
        return
    validate_hermes_manageable(path)
    text = path.read_text(encoding="utf-8")
    cleaned = _strip_hermes_block(text)
    if cleaned != text:
        _atomic_write(path, cleaned)


def hermes_configured(home: Path | None = None) -> bool:
    """Return whether Hermes contains ACCO's complete managed block."""
    path = hermes_config_path(home)
    if not path.exists():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return HERMES_START in text and HERMES_END in text


def openclaw_config_path(home: Path | None = None) -> Path:
    """Return OpenClaw's active/default JSON5 configuration path."""
    override = os.environ.get("OPENCLAW_CONFIG_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return (home or Path.home()) / ".openclaw" / "openclaw.json"


def openclaw_configured(home: Path | None = None) -> bool:
    """Detect a ACCO MCP entry in JSON or ordinary JSON5-shaped config."""
    path = openclaw_config_path(home)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        payload = json.loads(text)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        mcp = payload.get("mcp")
        servers = mcp.get("servers") if isinstance(mcp, dict) else None
        if isinstance(servers, dict) and ACCO_SERVER in servers:
            return True
    return bool(
        re.search(
            r"(?s)['\"]?mcp['\"]?\s*:\s*\{.*?"
            r"['\"]?servers['\"]?\s*:\s*\{.*?"
            r"['\"]?acco['\"]?\s*:\s*\{.*?"
            r"['\"]?command['\"]?\s*:\s*['\"]acco['\"]",
            text,
        )
    )


RunCommand = Callable[[list[str]], subprocess.CompletedProcess]


def run_command(argv: list[str]) -> subprocess.CompletedProcess:
    """Run a host-native config command and normalize failures for the CLI."""
    try:
        return subprocess.run(
            argv,
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise ValueError(
            f"Host configuration command failed: {' '.join(argv[:3])}: {detail}"
        ) from exc


def install_openclaw(
    root: Path,
    *,
    runner: RunCommand = run_command,
) -> None:
    """Install ACCO with OpenClaw's native validated MCP registry command."""
    payload = json.dumps(stdio_entry(root), separators=(",", ":"))
    runner(["openclaw", "mcp", "set", ACCO_SERVER, payload])


def uninstall_openclaw(
    home: Path | None = None,
    *,
    runner: RunCommand = run_command,
) -> None:
    """Remove ACCO from OpenClaw through the native registry command."""
    if not openclaw_configured(home):
        return
    runner(["openclaw", "mcp", "unset", ACCO_SERVER])
