from pathlib import Path

from token_saver.pack import rank_files


def test_diagnostic_snippet_ranking():
    root = Path(__file__).resolve().parents[1]
    ranked = rank_files(
        root,
        "extract exact body named source symbol",
        changed_boost=False,
        feedback_boost=False,
        persist_index=False,
    )
    top = [(item.rel, round(item.score, 3), item.reasons) for item in ranked[:12]]
    raise AssertionError(top)
