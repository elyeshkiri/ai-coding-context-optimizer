import pytest


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / ".ts-state"))
