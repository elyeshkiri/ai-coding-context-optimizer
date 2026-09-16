"""Private, recoverable command output. Never re-execute a command to page it."""
import json
import os
import re
import time
import uuid
from .state import state_dir

def store_output(response: dict) -> str:
    directory = state_dir() / "outputs"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_id = uuid.uuid4().hex
    path = directory / (output_id + ".json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(response, handle, ensure_ascii=False)
    return output_id

def retrieve(output_id: str, stream: str = "stdout", offset: int = 1, limit: int = 80) -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", output_id): raise ValueError("invalid output ID")
    if stream not in {"stdout", "stderr"}: raise ValueError("invalid stream")
    if offset < 1 or limit < 1 or limit > 2000: raise ValueError("offset >= 1 and limit 1..2000 required")
    data = json.loads((state_dir() / "outputs" / (output_id + ".json")).read_text(encoding="utf-8"))
    text = data.get(stream, "")
    lines = text.splitlines(keepends=True)
    return "".join(lines[offset - 1:offset - 1 + limit])

def prune(days: float = 7) -> int:
    if days < 0: raise ValueError("days must be nonnegative")
    count = 0
    for path in (state_dir() / "outputs").glob("*.json"):
        if path.stat().st_mtime < time.time() - days * 86400:
            path.unlink(); count += 1
    return count
