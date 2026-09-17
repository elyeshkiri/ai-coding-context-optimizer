"""Index-backed task-aware context packing facade.

The implementation lives in ``indexed_pack_core``.  At query time its index
builder is replaced with the stat-cached refresher so warm packs do not reopen
unchanged repository source files.  Keeping this indirection also leaves the
core implementation independently regression-testable.
"""
from __future__ import annotations

from . import indexed_pack_core as _core
from .fast_index import build_query_index

# Functions defined in indexed_pack_core resolve globals from that module at
# call time. Rebinding its builder makes every public indexed rank/pack path use
# the warm stat cache without duplicating the packer implementation.
_core.build_index = build_query_index

ContextPack = _core.ContextPack
RankedFile = _core.RankedFile
rank_files_indexed = _core.rank_files_indexed
build_context_pack_indexed = _core.build_context_pack_indexed

__all__ = [
    "ContextPack",
    "RankedFile",
    "rank_files_indexed",
    "build_context_pack_indexed",
]
