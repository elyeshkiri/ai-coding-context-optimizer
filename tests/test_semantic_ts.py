from token_saver.repo_index import build_index
from token_saver.semantic_ts import extract_module_refs, resolve_module_path


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
