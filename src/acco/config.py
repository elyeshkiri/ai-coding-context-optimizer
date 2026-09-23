"""Validated, atomic configuration edits; never replace unreadable settings."""
import json
import os
import tempfile
from .state import _locked

def update_json(path, mutate):
    """Update json."""
    with _locked(path):
        current = {}
        if path.exists():
            try: current = json.loads(path.read_text(encoding="utf-8"))
            except ValueError as exc: raise ValueError(f"Refusing to overwrite invalid JSON: {path}") from exc
            if not isinstance(current, dict): raise ValueError(f"Expected JSON object: {path}")
        updated = mutate(current)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(updated, handle, indent=2); handle.write("\n")
                handle.flush(); os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    return path
