from pathlib import Path

from acco.delta_context import apply_delta, extract_diagnostics


def _repo(root: Path):
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "auth.py").write_text(
        "def refresh_session(token):\n"
        "    return token\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_auth.py").write_text(
        "from src.auth import refresh_session\n\n"
        "def test_refresh():\n"
        "    assert refresh_session('x') == 'y'\n",
        encoding="utf-8",
    )
    return root


def _failure(message: str):
    return (
        "=========================== short test summary info ===========================\n"
        f"FAILED tests/test_auth.py::test_refresh - AssertionError: {message}\n"
        "======================= 1 failed, 20 passed in 0.2s =======================\n"
    )


def test_extract_pytest_diagnostic_identity():
    family, diagnostics = extract_diagnostics("pytest -q", _failure("expected y"))
    assert family == "pytest"
    assert diagnostics[0].identifier == "tests/test_auth.py::test_refresh"
    assert diagnostics[0].path == "tests/test_auth.py"


def test_delta_collapses_unchanged_failure(tmp_path, monkeypatch):
    root = _repo(tmp_path / "repo")
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    original = _failure("expected y")
    fallback = ("collection noise\n" * 100) + original

    first, meta1 = apply_delta(
        root, "pytest -q", original, fallback, session_id="session-1"
    )
    assert first == fallback
    assert meta1["used"] is False

    second, meta2 = apply_delta(
        root, "pytest -q", original, fallback, session_id="session-1"
    )
    assert meta2["used"] is True
    assert meta2["unchanged"] == 1
    assert "UNCHANGED tests/test_auth.py::test_refresh" in second
    assert len(second) < len(fallback)


def test_changed_failure_gets_symbol_and_graph_context(tmp_path, monkeypatch):
    root = _repo(tmp_path / "repo")
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    fallback = "noise\n" * 300

    apply_delta(
        root, "pytest", _failure("expected y"), fallback, session_id="session-2"
    )
    changed, meta = apply_delta(
        root, "pytest", _failure("expected z"), fallback, session_id="session-2"
    )

    assert meta["used"] is True
    assert meta["changed"] == 1
    assert "CHANGED tests/test_auth.py::test_refresh" in changed
    assert "source tests/test_auth.py" in changed
    assert "::test_refresh" in changed
    assert "src/auth.py" in changed


def test_clean_rerun_reports_resolved_failure(tmp_path, monkeypatch):
    root = _repo(tmp_path / "repo")
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    fallback = "noise\n" * 200

    apply_delta(
        root, "pytest -q", _failure("boom"), fallback, session_id="session-3"
    )
    clean = "======================= 21 passed in 0.2s =======================\n"
    rendered, meta = apply_delta(
        root, "pytest -q", clean, fallback, session_id="session-3"
    )

    assert meta["resolved"] == 1
    assert meta["used"] is True
    assert "RESOLVED tests/test_auth.py::test_refresh" in rendered
