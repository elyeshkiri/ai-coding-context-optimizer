from pathlib import Path

from token_saver.pack import build_context_pack


def test_diagnostic_incremental_index_symbol_selection():
    root = Path(__file__).resolve().parents[1]
    pack = build_context_pack(
        root,
        "reuse unchanged repository index records",
        max_tokens=6000,
        changed_boost=False,
        feedback_boost=False,
        persist_index=False,
    )
    raise AssertionError({
        "files": pack.selected_files,
        "symbols": pack.selected_symbols,
        "qualified": pack.selected_symbol_identities,
    })
