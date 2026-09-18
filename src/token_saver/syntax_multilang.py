"""Tree-sitter symbol extraction for Go, Rust, Java, and C#.

The JS/TS extractor lives in :mod:`token_saver.syntax`; this module keeps the
language-specific AST rules isolated so adding a grammar cannot destabilize the
existing JavaScript/TypeScript path.
"""
from __future__ import annotations

from functools import lru_cache

from .syntax import Symbol

STRUCTURED_EXTRA = {".go", ".rs", ".java", ".cs"}


@lru_cache(maxsize=4)
def _language(suffix: str):
    from tree_sitter import Language

    if suffix == ".go":
        import tree_sitter_go as grammar
    elif suffix == ".rs":
        import tree_sitter_rust as grammar
    elif suffix == ".java":
        import tree_sitter_java as grammar
    elif suffix == ".cs":
        import tree_sitter_c_sharp as grammar
    else:
        raise ValueError(f"unsupported structured language: {suffix}")
    return Language(grammar.language())


def _text(source: bytes, node) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _line_end(node) -> int:
    return node.end_point.row + (1 if node.end_point.column else 0)


def _first_descendant(node, node_type: str):
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type == node_type:
            return current
        stack.extend(reversed(current.named_children))
    return None


def _signature(source: bytes, extent, body=None) -> str:
    """Compact declaration signature without the implementation body."""
    if body is None:
        return " ".join(_text(source, extent).split())[:1000]

    head = _text(source, extent)[: max(0, body.start_byte - extent.start_byte)]
    body_text = _text(source, body)
    head = " ".join(head.split())

    # Some language nodes (notably Go's struct_type/interface_type) include the
    # type keyword together with the body. Preserve that keyword while still
    # dropping fields/method bodies.
    prefix = ""
    brace = body_text.find("{")
    if brace > 0:
        prefix = " ".join(body_text[:brace].split())

    if prefix:
        head = f"{head} {prefix}".strip()

    marker = " { … }" if "{" in body_text else " …"
    return (head + marker).strip()[:1000]


def _append(found: list[Symbol], source: bytes, *, name: str, node, body=None,
            parents=(), kind: str = "symbol", extent=None) -> None:
    extent = extent or node
    qualified = ".".join((*parents, name)) if parents else name
    found.append(Symbol(
        name=name,
        qualified=qualified,
        start=extent.start_point.row + 1,
        end=max(extent.start_point.row + 1, _line_end(extent)),
        start_byte=extent.start_byte,
        end_byte=extent.end_byte,
        signature=_signature(source, extent, body),
        kind=kind,
    ))


def _go_symbols(source: bytes, root) -> list[Symbol]:
    found: list[Symbol] = []

    def walk(node):
        if node.type == "function_declaration":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                _append(
                    found, source, name=_text(source, name_node), node=node,
                    body=node.child_by_field_name("body"), kind="function",
                )
        elif node.type == "method_declaration":
            name_node = node.child_by_field_name("name")
            receiver = node.child_by_field_name("receiver")
            owner_node = _first_descendant(receiver, "type_identifier") if receiver is not None else None
            if name_node is not None:
                owner = _text(source, owner_node) if owner_node is not None else None
                _append(
                    found, source, name=_text(source, name_node), node=node,
                    body=node.child_by_field_name("body"),
                    parents=(owner,) if owner else (), kind="method",
                )
        elif node.type == "type_spec":
            name_node = node.child_by_field_name("name")
            type_node = node.child_by_field_name("type")
            if name_node is not None:
                extent = node
                parent = node.parent
                if parent is not None and parent.type == "type_declaration":
                    specs = [c for c in parent.named_children if c.type == "type_spec"]
                    if len(specs) == 1:
                        extent = parent
                body = type_node if type_node is not None and type_node.type in {
                    "struct_type", "interface_type",
                } else None
                _append(
                    found, source, name=_text(source, name_node), node=node,
                    body=body, kind="type", extent=extent,
                )

        for child in node.named_children:
            walk(child)

    walk(root)
    return found


_RUST_CONTAINERS = {
    "struct_item": "type",
    "enum_item": "type",
    "union_item": "type",
    "trait_item": "trait",
}
_RUST_LEAF = {
    "type_item": "type",
    "associated_type": "type",
    "const_item": "constant",
    "static_item": "constant",
}


def _rust_impl_owner(source: bytes, node) -> str | None:
    target = node.child_by_field_name("type")
    if target is None:
        return None
    ident = _first_descendant(target, "type_identifier")
    if ident is not None:
        return _text(source, ident)
    # Primitive implementations (impl Foo for str) do not contain a
    # type_identifier. Keep the compact target text as the qualifier.
    raw = " ".join(_text(source, target).split())
    return raw if raw and len(raw) <= 120 else None


def _rust_symbols(source: bytes, root) -> list[Symbol]:
    found: list[Symbol] = []

    def walk(node, parents=()):
        if node.type == "impl_item":
            owner = _rust_impl_owner(source, node)
            next_parents = (owner,) if owner else parents
            for child in node.named_children:
                walk(child, next_parents)
            return

        if node.type in _RUST_CONTAINERS:
            name_node = node.child_by_field_name("name")
            next_parents = parents
            if name_node is not None:
                name = _text(source, name_node)
                _append(
                    found, source, name=name, node=node,
                    body=node.child_by_field_name("body"),
                    parents=parents, kind=_RUST_CONTAINERS[node.type],
                )
                next_parents = (*parents, name)
            for child in node.named_children:
                walk(child, next_parents)
            return

        if node.type in {"function_item", "function_signature_item"}:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                _append(
                    found, source, name=_text(source, name_node), node=node,
                    body=node.child_by_field_name("body"),
                    parents=parents,
                    kind="method" if parents else "function",
                )
        elif node.type in _RUST_LEAF:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                _append(
                    found, source, name=_text(source, name_node), node=node,
                    parents=parents, kind=_RUST_LEAF[node.type],
                )

        for child in node.named_children:
            walk(child, parents)

    walk(root)
    return found


_JAVA_CONTAINERS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "record",
    "annotation_type_declaration": "annotation",
}
_JAVA_MEMBERS = {
    "method_declaration": "method",
    "constructor_declaration": "constructor",
    "compact_constructor_declaration": "constructor",
    "annotation_type_element_declaration": "method",
}


def _java_symbols(source: bytes, root) -> list[Symbol]:
    found: list[Symbol] = []

    def walk(node, parents=()):
        if node.type in _JAVA_CONTAINERS:
            name_node = node.child_by_field_name("name")
            next_parents = parents
            if name_node is not None:
                name = _text(source, name_node)
                _append(
                    found, source, name=name, node=node,
                    body=node.child_by_field_name("body"),
                    parents=parents, kind=_JAVA_CONTAINERS[node.type],
                )
                next_parents = (*parents, name)
            for child in node.named_children:
                walk(child, next_parents)
            return

        if node.type in _JAVA_MEMBERS:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                _append(
                    found, source, name=_text(source, name_node), node=node,
                    body=node.child_by_field_name("body"),
                    parents=parents, kind=_JAVA_MEMBERS[node.type],
                )

        for child in node.named_children:
            walk(child, parents)

    walk(root)
    return found


_CSHARP_CONTAINERS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "struct_declaration": "struct",
    "enum_declaration": "enum",
    "record_declaration": "record",
}
_CSHARP_MEMBERS = {
    "method_declaration": "method",
    "constructor_declaration": "constructor",
    "property_declaration": "property",
    "event_declaration": "event",
    "delegate_declaration": "delegate",
}


def _csharp_symbols(source: bytes, root) -> list[Symbol]:
    found: list[Symbol] = []

    def walk(node, parents=()):
        if node.type in _CSHARP_CONTAINERS:
            name_node = node.child_by_field_name("name")
            next_parents = parents
            if name_node is not None:
                name = _text(source, name_node)
                _append(
                    found, source, name=name, node=node,
                    body=node.child_by_field_name("body"),
                    parents=parents, kind=_CSHARP_CONTAINERS[node.type],
                )
                next_parents = (*parents, name)
            for child in node.named_children:
                walk(child, next_parents)
            return

        if node.type in _CSHARP_MEMBERS:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                body = (
                    node.child_by_field_name("body")
                    or node.child_by_field_name("accessors")
                    or node.child_by_field_name("value")
                )
                _append(
                    found, source, name=_text(source, name_node), node=node,
                    body=body, parents=parents, kind=_CSHARP_MEMBERS[node.type],
                )

        for child in node.named_children:
            walk(child, parents)

    walk(root)
    return found


def symbols(text: str, suffix: str) -> list[Symbol]:
    """Return exact structural symbols for a supported non-JS language."""
    from tree_sitter import Parser

    suffix = suffix.lower()
    if suffix not in STRUCTURED_EXTRA:
        raise ValueError(f"unsupported structured language: {suffix}")

    source = text.encode("utf-8")
    tree = Parser(_language(suffix)).parse(source)
    if tree.root_node.has_error:
        raise ValueError("Source has syntax errors; use an explicit source range instead")

    if suffix == ".go":
        return _go_symbols(source, tree.root_node)
    if suffix == ".rs":
        return _rust_symbols(source, tree.root_node)
    if suffix == ".java":
        return _java_symbols(source, tree.root_node)
    return _csharp_symbols(source, tree.root_node)
