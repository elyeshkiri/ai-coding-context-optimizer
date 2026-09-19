"""Write Claude Code hooks so filter + read-guard fire without being remembered."""

from __future__ import annotations

from pathlib import Path

HOOK_COMMAND = "token-saver hook"
HOOK_TIMEOUT = 10

PRE_MATCHER = "Read|Bash"
POST_MATCHER = "Bash|Read"
SESSION_MATCHER = "startup|resume|clear|compact"
PROMPT_MATCHER = "*"


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
    events = {"PreToolUse": PRE_MATCHER, "PostToolUse": POST_MATCHER,
              "SessionStart": SESSION_MATCHER, "UserPromptSubmit": ""}
    for event in (*events, "Stop"):
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
