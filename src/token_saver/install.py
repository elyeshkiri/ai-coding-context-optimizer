"""Write Claude Code hooks so filter + read-guard fire without being remembered."""

from __future__ import annotations

from pathlib import Path

HOOK_COMMAND = "token-saver hook"
HOOK_TIMEOUT = 10

PRE_MATCHER = "Read|Bash"
POST_MATCHER = "Bash|Read|Edit|Write"
SESSION_MATCHER = "startup|resume|clear|compact"
PROMPT_MATCHER = "*"
HOOK_MATCHERS = {
    "PreToolUse": PRE_MATCHER,
    "PostToolUse": POST_MATCHER,
    "SessionStart": SESSION_MATCHER,
    "UserPromptSubmit": "",
    "Stop": "",
    "StopFailure": "",
}


def hook_block(matcher: str) -> dict:
    """Handle hook block."""
    block: dict = {
        "hooks": [
            {"type": "command", "command": HOOK_COMMAND, "timeout": HOOK_TIMEOUT}
        ],
    }
    if matcher:
        block["matcher"] = matcher
    return block


def merge_hooks(existing: dict) -> dict:
    """Replace only our hook entries; preserve all unrelated hooks and matchers."""
    from copy import deepcopy
    out = deepcopy(existing)
    hooks = out.setdefault("hooks", {})
    events = HOOK_MATCHERS
    for event in events:
        entries = []
        for entry in hooks.get(event, []):
            others = [h for h in entry.get("hooks", []) if h.get("command") != HOOK_COMMAND]
            if others:
                entry["hooks"] = others
                entries.append(entry)
        if event in events:
            entries.append(hook_block(events[event]))
        if entries or event in hooks:
            hooks[event] = entries
    return out


def remove_hooks(existing: dict) -> dict:
    """Remove only Token Saver hook commands while preserving unrelated hooks."""
    from copy import deepcopy

    out = deepcopy(existing)
    hooks = out.get("hooks")
    if not isinstance(hooks, dict):
        return out
    for event, event_entries in list(hooks.items()):
        if not isinstance(event_entries, list):
            continue
        kept = []
        for entry in event_entries:
            if not isinstance(entry, dict):
                kept.append(entry)
                continue
            commands = entry.get("hooks")
            if not isinstance(commands, list):
                kept.append(entry)
                continue
            remaining = [
                command
                for command in commands
                if not isinstance(command, dict)
                or command.get("command") != HOOK_COMMAND
            ]
            if remaining:
                updated = dict(entry)
                updated["hooks"] = remaining
                kept.append(updated)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if not hooks:
        out.pop("hooks", None)
    return out


def settings_path(root: Path) -> Path:
    """Handle settings path."""
    return root / ".claude" / "settings.json"


def user_settings_path() -> Path:
    """Handle user settings path."""
    return Path.home() / ".claude" / "settings.json"


def install(root: Path, user: bool = False, templates: bool = False) -> Path:
    """Install the requested value."""
    path = user_settings_path() if user else settings_path(root)
    from .config import update_json
    update_json(path, merge_hooks)
    if templates and not user:
        from .policy import write_skill
        write_skill(root)
    return path


def uninstall(root: Path, user: bool = False) -> Path:
    """Remove Token Saver hooks without touching unrelated Claude settings."""
    path = user_settings_path() if user else settings_path(root)
    if not path.exists():
        return path
    from .config import update_json

    update_json(path, remove_hooks)
    return path
