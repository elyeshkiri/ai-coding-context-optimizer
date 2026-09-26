"""Cross-platform Docker host arguments for benchmark helpers."""

from __future__ import annotations

import os


def docker_user_args() -> tuple[list[str], bool]:
    """Return Docker user arguments and whether the container should be sandbox-marked.

    POSIX hosts preserve the caller uid/gid. Windows has no uid/gid concept;
    Docker Desktop Linux containers therefore use their image/default user, which
    is commonly root, so callers using dangerous-skip-permissions should mark
    the throwaway container as sandboxed.
    """
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if not callable(getuid) or not callable(getgid):
        return [], True
    uid = int(getuid())
    gid = int(getgid())
    return ["--user", f"{uid}:{gid}"], uid == 0
