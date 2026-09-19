
from token_saver.mapstat import map_freshness


def test_missing_map_is_fresh(tmp_path):
    fresh, reason = map_freshness(tmp_path)
    assert fresh
    assert "optional" in reason


def test_stale_map(tmp_path):
    src = tmp_path / "app.py"
    src.write_text("def foo():\n    return 1\n")
    cmap = tmp_path / "CODEMAP.md"
    cmap.write_text("# old\n")
    # map older than source
    import os
    os.utime(cmap, (src.stat().st_mtime - 10, src.stat().st_mtime - 10))
    fresh, reason = map_freshness(tmp_path)
    assert not fresh
    assert "app.py" in reason
