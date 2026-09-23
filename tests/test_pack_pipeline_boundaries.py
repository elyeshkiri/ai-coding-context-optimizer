"""Architecture and parity tests for the extracted context-packing stages."""

from __future__ import annotations

import inspect
import textwrap

import acco.pack as pack_facade
from acco.packing.contracts import ContextPack, RankedFile
from acco.packing.ranking import rank_files as ranking_stage
from acco.packing.render import _fit_section as render_fit_section
from acco.packing.symbols import _file_section as symbol_file_section
from acco.repo_index import build_index


def _repo(tmp_path):
    """Create a small repository with deterministic ranking evidence."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text(
        textwrap.dedent(
            """
            class SessionManager:
                def refresh_session(self, token):
                    return self.rotate_session(token)
            """
        ),
        encoding="utf-8",
    )
    (src / "billing.py").write_text(
        textwrap.dedent(
            """
            class InvoiceService:
                def create_invoice(self, account):
                    return account
            """
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_pack_facade_preserves_contract_and_stage_imports():
    """Historical pack imports should resolve to the extracted stage objects."""
    assert pack_facade.ContextPack is ContextPack
    assert pack_facade.RankedFile is RankedFile
    assert pack_facade._file_section is symbol_file_section
    assert pack_facade._fit_section is render_fit_section


def test_pack_facade_is_final_orchestration_not_algorithm_monolith():
    """The compatibility module should keep assembly but not stage implementations."""
    source = inspect.getsource(pack_facade)
    assert "def build_context_pack(" in source
    assert "def rank_files(" in source
    assert "def _score_symbol(" not in source
    assert "def _bm25_score(" not in source
    assert "class _SymbolScope" not in source
    assert len(source.splitlines()) < 450


def test_facade_ranking_matches_extracted_stage_exactly(tmp_path):
    """Extraction must not alter ordered scores, reasons, or retrieval evidence."""
    root = _repo(tmp_path)
    index = build_index(root, persist=False)

    facade = pack_facade.rank_files(
        root,
        "refresh authentication session token",
        changed_boost=False,
        index=index,
    )
    extracted = ranking_stage(
        root,
        "refresh authentication session token",
        changed_boost=False,
        index=index,
        changed_files=set(),
    )

    assert [
        (item.rel, item.score, item.reasons, item.term_hits, item.changed)
        for item in facade
    ] == [
        (item.rel, item.score, item.reasons, item.term_hits, item.changed)
        for item in extracted
    ]


def test_changed_file_monkeypatch_seam_survives_extraction(tmp_path, monkeypatch):
    """Existing callers patching acco.pack._changed_files must still work."""
    root = _repo(tmp_path)
    monkeypatch.setattr(
        pack_facade,
        "_changed_files",
        lambda _root: {"src/billing.py"},
    )

    ranked = pack_facade.rank_files(
        root,
        "invoice account",
        changed_boost=True,
    )

    billing = next(item for item in ranked if item.rel == "src/billing.py")
    assert billing.changed is True
    assert "changed" in billing.reasons
