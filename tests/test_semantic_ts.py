import pytest

from token_saver.repo_index import build_index
from token_saver.semantic_ts import (
    enrich_index_with_typescript,
    extract_module_refs,
    resolve_module_path,
    resolve_typescript_edges,
)


def test_extracts_named_import_alias_call():
    refs = extract_module_refs(
        'import { refreshSession as refresh } from "./session";\n'
        'refresh();\n'
    )
    assert {
        "module": "./session",
        "symbol": "refreshSession",
        "local": "refresh",
        "kind": "semantic-call",
    } in refs


def test_extracts_namespace_call():
    refs = extract_module_refs(
        'import * as sessions from "./session";\n'
        'sessions.refreshSession();\n'
    )
    assert {
        "module": "./session",
        "symbol": "refreshSession",
        "local": "sessions.refreshSession",
        "kind": "semantic-call",
    } in refs


def test_extracts_named_reexport():
    refs = extract_module_refs(
        'export { refreshSession as refresh } from "./session";\n'
    )
    assert {
        "module": "./session",
        "symbol": "refreshSession",
        "local": "refresh",
        "kind": "reexport",
    } in refs


def test_resolve_relative_module_path():
    known = {"src/controller.ts", "src/session.ts", "src/deep/index.ts"}
    assert resolve_module_path("src/controller.ts", "./session", known) == "src/session.ts"
    assert resolve_module_path("src/controller.ts", "./deep", known) == "src/deep/index.ts"
    assert resolve_module_path("src/controller.ts", "react", known) is None


def test_repository_graph_prefers_alias_resolved_semantic_edge(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "session.ts").write_text(
        "export function refreshSession() { return true; }\n"
    )
    (src / "controller.ts").write_text(
        'import { refreshSession as refresh } from "./session";\n'
        "export function handle() { return refresh(); }\n"
    )

    index = build_index(tmp_path, persist=False)
    assert ("src/session.ts", "semantic-call") in index.neighbors("src/controller.ts")


def test_repository_graph_tracks_reexport_module(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "session.ts").write_text(
        "export function refreshSession() { return true; }\n"
    )
    (src / "index.ts").write_text(
        'export { refreshSession as refresh } from "./session";\n'
    )

    index = build_index(tmp_path, persist=False)
    assert ("src/session.ts", "reexport") in index.neighbors("src/index.ts")


def test_typescript_compiler_resolver_falls_back_without_node(tmp_path, monkeypatch):
    monkeypatch.setattr("token_saver.semantic_ts.shutil.which", lambda _name: None)
    assert resolve_typescript_edges(tmp_path) == {}
    with pytest.raises(RuntimeError, match="Node.js"):
        resolve_typescript_edges(tmp_path, strict=True)


def test_compiler_edges_enrich_existing_index_without_replacing_it(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "service.ts").write_text(
        "export function runService() { return true; }\n"
    )
    # Deliberately avoid a lexical relative import so this edge can only come
    # from the mocked compiler resolution layer.
    (src / "controller.ts").write_text(
        'import { runService } from "@app/service";\n'
        "export function handle() { return runService(); }\n"
    )
    index = build_index(tmp_path, persist=False)
    monkeypatch.setattr(
        "token_saver.semantic_ts.resolve_typescript_edges",
        lambda _root, **_kwargs: {"src/controller.ts": ["src/service.ts"]},
    )

    added = enrich_index_with_typescript(index, enabled=True)

    assert added == 1
    assert ("src/service.ts", "semantic-call") in index.neighbors("src/controller.ts")
