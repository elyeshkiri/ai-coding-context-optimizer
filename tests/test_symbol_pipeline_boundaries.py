"""Boundary tests for symbol scoring and source-window rendering stages."""

from __future__ import annotations

import inspect
import textwrap

import acco.pack as pack_facade
import acco.packing.symbol_scoring as symbol_scoring
import acco.packing.symbol_windows as symbol_windows
import acco.packing.symbols as symbols_facade
from acco.packing.contracts import RankedFile
from acco.repo_index import build_index


def _symbol_fixture(tmp_path):
    """Create one file with competing symbols and return its indexed ranked item."""
    src = tmp_path / "session.py"
    text = textwrap.dedent(
        """
        class SessionManager:
            def create_session(self, user):
                return user

            def refresh_session(self, token):
                return rotate_token(token)
        """
    )
    src.write_text(text, encoding="utf-8")
    index = build_index(tmp_path, persist=False)
    record = index.records["session.py"]
    item = RankedFile(
        path=src,
        rel="session.py",
        text=text,
        outline=record.outline,
        score=10.0,
        reasons=["test"],
        term_hits=1,
        changed=False,
    )
    return item, index


def test_symbols_module_is_only_a_compatibility_facade():
    """Legacy symbol imports should point at the two extracted implementation stages."""
    source = inspect.getsource(symbols_facade)
    assert "\ndef " not in source
    assert "\nclass " not in source
    assert symbols_facade._score_symbol is symbol_scoring._score_symbol
    assert symbols_facade._file_section is symbol_windows._file_section


def test_pack_facade_bypasses_symbols_compatibility_module():
    """Pack orchestration should depend directly on scoring and rendering stages."""
    assert pack_facade._score_symbol is symbol_scoring._score_symbol
    assert pack_facade._file_section is symbol_windows._file_section
    source = inspect.getsource(pack_facade)
    assert "from .packing.symbols import" not in source


def test_symbol_scoring_does_not_own_source_rendering():
    """Scoring policy must remain independent from source-window formatting."""
    source = inspect.getsource(symbol_scoring)
    assert "redact_secrets" not in source
    assert "RepositoryIndex" not in source
    assert "def _source_window(" not in source
    assert "def _file_section(" not in source


def test_symbol_windows_delegates_relevance_to_scoring_stage():
    """Window rendering should consume scoring helpers rather than redefine policy."""
    source = inspect.getsource(symbol_windows)
    assert "from .symbol_scoring import" in source
    assert "def _lexical_symbol_score(" not in source
    assert "def _apply_overload_dimensions(" not in source
    assert "def _score_symbol(" not in source


def test_extracted_windows_select_expected_symbol_and_source(tmp_path):
    """The split should preserve selected labels and exact implementation evidence."""
    item, index = _symbol_fixture(tmp_path)

    windows, labels, identities = symbol_windows._symbol_windows(
        item,
        index,
        {"refresh", "session", "token"},
        None,
        "refresh session token",
    )
    section, section_labels, section_identities, redactions = (
        symbol_windows._file_section(
            item,
            {"refresh", "session", "token"},
            2,
            index,
            symbol_query_text="refresh session token",
        )
    )

    assert windows
    assert any(label.startswith("session.py:refresh_session@") for label in labels)
    assert any(
        identity.startswith("session.py:SessionManager.refresh_session@")
        for identity in identities
    )
    assert "def refresh_session(self, token):" in section
    # The section may append a lower-priority backfill symbol after the
    # primary selection, but never reorders or drops it.
    assert section_labels[:len(labels)] == labels
    assert section_identities[:len(identities)] == identities
    assert redactions == []


def test_duplicate_child_slot_backfills_after_outline(tmp_path):
    """A slot that only repeats a container's rendered child gets backfilled.

    The backfill is lowest priority: it is rendered after the outline, so
    section fitting clips it before any primary, lexical, or outline evidence.
    """
    text = textwrap.dedent(
        """
        class Scheduler:
            def next_request(self):
                return self.queue.pop()

        class Queue:
            def push(self, request):
                self.items.append(request)

        def schedule_request(scheduler, request):
            return scheduler.queue_request(request)
        """
    )
    path = tmp_path / "scheduler.py"
    path.write_text(text, encoding="utf-8")
    index = build_index(tmp_path, persist=False)
    record = index.records["scheduler.py"]
    item = RankedFile(
        path=path, rel="scheduler.py", text=text, outline=record.outline,
        score=10.0, reasons=["test"], term_hits=1, changed=False,
    )
    query = "which scheduler returns the next request"

    _, labels, _ = symbol_windows._symbol_windows(item, index, set(), None, query)
    section, section_labels, _, _ = symbol_windows._file_section(
        item, set(), 2, index, symbol_query_text=query,
    )

    assert section_labels[:len(labels)] == labels
    extra = section_labels[len(labels):]
    assert extra, "expected a backfilled symbol"
    assert section.index("### outline") < section.index("### additional source windows")
