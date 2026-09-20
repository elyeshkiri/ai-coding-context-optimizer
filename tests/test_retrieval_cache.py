"""Tests for content-fingerprinted persistent retrieval caching."""

from __future__ import annotations

from token_saver.repository_service import RepositoryContextService


def _repo(tmp_path):
    """Create a small source repository for cache tests."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "auth.py").write_text(
        "def refresh_session(token):\n    return rotate(token)\n",
        encoding="utf-8",
    )
    (root / "billing.py").write_text(
        "def invoice(customer):\n    return customer.total\n",
        encoding="utf-8",
    )
    return root


def _service(root):
    """Return a cache-enabled service with deterministic local retrieval."""
    return RepositoryContextService(
        root,
        persist_index=True,
        retrieval_cache_enabled=True,
        retrieval_cache_max_entries=8,
    )


def test_identical_fresh_service_query_hits_persistent_cache(tmp_path, monkeypatch):
    """A second process-like service should reuse an identical completed pack."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = _repo(tmp_path)

    first = _service(root).build_context(
        "refresh session token",
        max_tokens=600,
        changed_boost=False,
    )
    second = _service(root).build_context(
        "refresh session token",
        max_tokens=600,
        changed_boost=False,
    )

    assert first.cache_hit is False
    assert first.cache_key
    assert second.cache_hit is True
    assert second.cache_key == first.cache_key
    assert second.text == first.text
    assert second.selected_files == first.selected_files


def test_source_mutation_invalidates_cache_by_content_fingerprint(tmp_path, monkeypatch):
    """Changed indexed evidence must produce a new key and never stale cache reuse."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = _repo(tmp_path)

    first = _service(root).build_context(
        "refresh session token",
        max_tokens=600,
        changed_boost=False,
    )
    (root / "auth.py").write_text(
        "def refresh_session(token):\n    return rotate_v2(token)\n",
        encoding="utf-8",
    )
    second = _service(root).build_context(
        "refresh session token",
        max_tokens=600,
        changed_boost=False,
    )

    assert second.cache_hit is False
    assert second.cache_key != first.cache_key
    assert "rotate_v2" in second.text


def test_retrieval_configuration_is_part_of_cache_identity(tmp_path, monkeypatch):
    """Changing the bounded context contract must not reuse an incompatible pack."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = _repo(tmp_path)

    first = _service(root).build_context(
        "refresh session token",
        max_tokens=600,
        changed_boost=False,
    )
    changed_budget = _service(root).build_context(
        "refresh session token",
        max_tokens=350,
        changed_boost=False,
    )

    assert changed_budget.cache_hit is False
    assert changed_budget.cache_key != first.cache_key
    assert changed_budget.estimated_tokens <= 350


def test_cache_can_be_disabled_at_application_boundary(tmp_path, monkeypatch):
    """Explicit cache opt-out should leave repeated retrieval fully uncached."""
    monkeypatch.setenv("TOKEN_SAVER_STATE_DIR", str(tmp_path / "state"))
    root = _repo(tmp_path)

    service = RepositoryContextService(
        root,
        retrieval_cache_enabled=False,
    )
    first = service.build_context(
        "refresh session token",
        max_tokens=600,
        changed_boost=False,
    )
    second = RepositoryContextService(
        root,
        retrieval_cache_enabled=False,
    ).build_context(
        "refresh session token",
        max_tokens=600,
        changed_boost=False,
    )

    assert first.cache_key is None
    assert second.cache_hit is False
    assert second.cache_key is None
