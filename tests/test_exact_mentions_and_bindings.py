"""Exact identifier mentions in symbol selection, and module-level bindings.

Both came out of classifying external-holdout misses: a verbatim ``Get`` or
``should_bind_json`` in a request could lose to a longer name containing it,
and names bound by assignment (``current_app = LocalProxy(...)``,
``exports.etag = createETagGenerator(...)``) were missing from the index.
"""
from __future__ import annotations

import textwrap

import acco.packing.symbol_windows as symbol_windows
from acco.packing.contracts import RankedFile
from acco.packing.symbol_scoring import (
    _build_symbol_scope,
    _exact_mention_bonus,
    _query_code_mentions,
)
from acco.repo_index import _extract, build_index


def _ranked(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    index = build_index(tmp_path, persist=False)
    record = index.records[name]
    item = RankedFile(
        path=path, rel=name, text=text, outline=record.outline,
        score=10.0, reasons=["test"], term_hits=1, changed=False,
    )
    return item, index


def _selected_names(item, index, query: str) -> list[str]:
    _, labels, _ = symbol_windows._symbol_windows(item, index, set(), None, query)
    return [label.split(":", 1)[1].split("@", 1)[0] for label in labels]


def test_code_mentions_are_code_shaped_tokens_only():
    assert _query_code_mentions("where is the package-level Get function") == {"Get"}
    assert "get" in _query_code_mentions("how does lodash's get() resolve a path")
    assert "run" in _query_code_mentions("how does `run` work")
    assert "should_bind_json" in _query_code_mentions("where is should_bind_json")
    # Lowercase prose is not a reference, even when a symbol has that name.
    assert "option" not in _query_code_mentions("add a new command line option")


def test_exact_mention_beats_longer_name_that_contains_it(tmp_path):
    text = textwrap.dedent(
        """
        def should_bind_body_with_json(request, body, json):
            return bind(request, body, json)

        def should_bind_json(request):
            return bind(request)
        """
    )
    item, index = _ranked(tmp_path, "binding.py", text)

    selected = _selected_names(
        item, index, "where does should_bind_json bind a request body as json",
    )

    assert selected[0] == "should_bind_json"


def test_exact_mention_of_a_type_is_treated_as_context(tmp_path):
    """A named type is context; its matching member should keep the slot."""
    text = textwrap.dedent(
        """
        class BytesMut:
            def with_capacity(self, capacity):
                return allocate(capacity)

            def freeze(self):
                return self
        """
    )
    item, index = _ranked(tmp_path, "bytes_mut.py", text)

    selected = _selected_names(
        item, index, "how does BytesMut allocate with a requested capacity",
    )

    assert "with_capacity" in selected


def test_member_sharing_a_type_name_gets_no_exact_mention_credit(tmp_path):
    """`Group.Group` is ambiguous: "where does Group register" means the type."""
    text = textwrap.dedent(
        """
        class Group:
            def Group(self, prefix):
                return Group()

        def Print(value):
            return value
        """
    )
    item, index = _ranked(tmp_path, "group.py", text)
    query = "where does Group register middleware and Print a value"
    scope = _build_symbol_scope(
        item, index.records["group.py"], set(), None, query,
    )
    by_qualified = {d.qualified: d for d in scope.definitions}

    assert _exact_mention_bonus(scope, by_qualified["Group.Group"]) == 0.0
    assert _exact_mention_bonus(scope, by_qualified["Group"]) == 0.0
    assert _exact_mention_bonus(scope, by_qualified["Print"]) > 0.0


def test_python_module_level_call_bindings_are_definitions():
    text = textwrap.dedent(
        """
        current_app: AppProxy = LocalProxy(_lookup_app)
        request = LocalProxy(_lookup_request)
        _private = LocalProxy(_lookup_private)
        TIMEOUT = 30
        """
    )
    defs = {d.name: d for d in _extract(text, ".py", "globals.py")[4]}

    assert defs["current_app"].kind == "variable"
    assert defs["current_app"].calls == ["LocalProxy"]
    assert "request" in defs
    assert "_private" not in defs
    assert "TIMEOUT" not in defs


def test_commonjs_exports_are_indexed_but_aliases_are_not():
    text = textwrap.dedent(
        """
        var req = require('./request');
        exports.etag = createETagGenerator({ weak: false });
        exports.request = req;
        module.exports.response = res.proto;
        """
    )
    names = {d.name for d in _extract(text, ".js", "lib/utils.js")[4]}

    assert "etag" in names
    assert "request" not in names
    assert "response" not in names


def test_named_function_expression_exported_as_default_is_indexed():
    text = textwrap.dedent(
        """
        const supported = typeof process !== 'undefined';

        export default supported && function httpAdapter(config) {
          return wrap(async function dispatch(resolve) {
            resolve(config);
          });
        };
        """
    )
    defs = {d.name: d for d in _extract(text, ".js", "lib/http.js")[4]}

    assert defs["httpAdapter"].kind == "function"
    # Named inner callbacks remain implementation detail.
    assert "dispatch" not in defs
