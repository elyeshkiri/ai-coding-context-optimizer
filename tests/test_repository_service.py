"""Tests for the shared repository context application service."""

from __future__ import annotations

import textwrap

from acco.repo_index import build_index
from acco.repository_service import RepositoryContextService


def _repository(tmp_path):
    """Create a small connected repository used by service tests."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text(
        textwrap.dedent(
            """
            def refresh_session(token: str) -> str:
                return rotate_token(token)
            """
        ),
        encoding="utf-8",
    )
    (src / "api.py").write_text(
        textwrap.dedent(
            """
            from auth import refresh_session

            def handle_login(token: str) -> str:
                return refresh_session(token)
            """
        ),
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_auth.py").write_text(
        textwrap.dedent(
            """
            from auth import refresh_session

            def test_refresh_session():
                assert refresh_session("token")
            """
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_service_reuses_one_injected_index_across_repository_use_cases(
    tmp_path,
    monkeypatch,
):
    """Packing, browsing, symbols, and impact should share one injected index."""
    root = _repository(tmp_path)
    index = build_index(root, persist=False)

    def unexpected_rebuild(*args, **kwargs):
        """Fail if a service operation tries to rebuild the injected index."""
        raise AssertionError("injected repository index was rebuilt")

    monkeypatch.setattr(
        "acco.repository_service.build_index",
        unexpected_rebuild,
    )
    service = RepositoryContextService(
        root,
        index=index,
        persist_index=False,
    )

    symbols = service.find_symbols("refresh_session")
    assert symbols[0]["path"] == "src/auth.py"

    browser = service.browse(
        "refresh session token",
        max_files=3,
        changed_boost=False,
    )
    assert browser["files"][0]["path"] == "src/auth.py"

    pack = service.build_context(
        "refresh session token",
        max_tokens=700,
        changed_boost=False,
    )
    assert "src/auth.py" in pack.selected_files

    impact = service.impact("refresh_session").to_dict()
    assert impact["matched"][0]["path"] == "src/auth.py"
    assert any(item["path"] == "src/api.py" for item in impact["affected"])


def test_service_owns_index_refresh_policy(tmp_path, monkeypatch):
    """Index construction should use the service's gitignore and persistence policy."""
    root = _repository(tmp_path)
    original = build_index
    calls = []

    def tracked_build_index(path, *, use_gitignore=True, persist=True, **kwargs):
        """Capture index construction policy before delegating to the real builder."""
        calls.append((path, use_gitignore, persist))
        return original(
            path,
            use_gitignore=use_gitignore,
            persist=persist,
            **kwargs,
        )

    monkeypatch.setattr(
        "acco.repository_service.build_index",
        tracked_build_index,
    )
    service = RepositoryContextService(
        root,
        use_gitignore=False,
        persist_index=False,
    )

    index = service.get()

    assert index is service.get()
    assert calls == [(root.resolve(), False, False)]
    assert service.refreshed_at is not None
    assert service.status()["files"] == 3


def test_service_owns_typescript_semantic_enrichment(tmp_path, monkeypatch):
    """Compiler semantic enrichment should operate on the service's shared index."""
    root = _repository(tmp_path)
    index = build_index(root, persist=False)
    seen = []

    def enrich(shared_index, *, enabled=None, strict=False, timeout=20.0):
        """Capture semantic-enrichment inputs."""
        seen.append((shared_index, enabled, strict, timeout))
        return 4

    monkeypatch.setattr(
        "acco.repository_service.enrich_index_with_typescript",
        enrich,
    )
    service = RepositoryContextService(root, index=index)

    assert service.enrich_typescript(enabled=True, strict=True, timeout=3.0) == 4
    assert seen == [(index, True, True, 3.0)]


def test_service_records_feedback_without_exposing_storage_to_hosts(tmp_path):
    """Ranking feedback should be available through the application boundary."""
    root = _repository(tmp_path)
    service = RepositoryContextService(root, persist_index=False)

    scores = service.feedback("src/auth.py", useful=True)

    assert scores["src/auth.py"] > 0
