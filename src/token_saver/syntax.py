"""Syntax-aware JS/TS symbols and exact byte spans, using maintained grammars."""
from dataclasses import dataclass
from functools import lru_cache

JS_TS = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}

@dataclass
class Symbol:
    name: str
    qualified: str
    start: int
    end: int
    start_byte: int
    end_byte: int
    signature: str
    kind: str = "symbol"
    calls: tuple[str, ...] = ()
    identity_line: int | None = None

@lru_cache(maxsize=3)
def _language(suffix):
    from tree_sitter import Language
    if suffix in {".ts", ".tsx"}:
        import tree_sitter_typescript as grammar
        return Language(grammar.language_tsx() if suffix == ".tsx" else grammar.language_typescript())
    import tree_sitter_javascript as grammar
    return Language(grammar.language())

def _symbols_js_ts(text: str, suffix: str) -> list[Symbol]:
    from tree_sitter import Parser
    source = text.encode("utf-8")
    tree = Parser(_language(suffix)).parse(source)
    if tree.root_node.has_error:
        raise ValueError("Source has syntax errors; use an explicit source range instead")
    found = []
    declarations = {"function_declaration", "generator_function_declaration", "function_signature",
                    "class_declaration", "abstract_class_declaration", "interface_declaration",
                    "type_alias_declaration", "enum_declaration", "method_definition",
                    "method_signature", "abstract_method_signature"}
    containers = {"class_declaration", "abstract_class_declaration", "interface_declaration", "enum_declaration"}
    def walk(node, parents=()):
        name_node = node.child_by_field_name("name")
        identity_node = name_node
        name = source[name_node.start_byte:name_node.end_byte].decode() if name_node else None
        value = node.child_by_field_name("value")
        is_variable = node.type in {"variable_declarator", "public_field_definition", "field_definition"}
        is_object = is_variable and value is not None and value.type == "object"
        is_function = is_variable and value is not None and value.type in {"arrow_function", "function_expression", "generator_function"}
        is_exported_variable = False
        if node.type == "variable_declarator" and node.parent is not None:
            declaration = node.parent
            is_exported_variable = bool(
                declaration.type in {"lexical_declaration", "variable_declaration"}
                and declaration.parent is not None
                and declaration.parent.type == "export_statement"
            )
        if node.type == "pair":
            key = node.child_by_field_name("key")
            if key:
                name = source[key.start_byte:key.end_byte].decode().strip("\"'")
                identity_node = key
            is_function = value is not None and value.type in {"arrow_function", "function_expression"}
            is_object = value is not None and value.type == "object"
        # `res.cookie = function (...) {...}` / `exports.foo = () => {...}`:
        # the common CommonJS/prototype-assignment pattern for defining a
        # method or export, distinct from `const x = function(){}` (a
        # variable_declarator) -- tree-sitter gives this its own node type
        # with "left"/"right" fields, not "name"/"value", so it was
        # previously invisible to symbol extraction entirely. Left
        # unhandled, an entire public API surface written this way (as
        # express's response.js/request.js are, near-universally) never
        # appears in the index at all.
        prototype_owner = None
        if node.type == "assignment_expression":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left is not None and left.type == "member_expression":
                prop = left.child_by_field_name("property")
                if prop is not None:
                    name = source[prop.start_byte:prop.end_byte].decode()
                    identity_node = prop
                # `View.prototype.lookup = function () {...}`: the classic
                # pre-ES6 constructor-function pattern, where `View` and its
                # prototype methods are siblings in the AST rather than
                # lexically nested the way an ES6 class's methods are --
                # without this, `View` (a real, separately-extracted
                # function_declaration) never gets to know these are its
                # own members, and its thin constructor body can be
                # outranked and displaced by one of them the same way a
                # dense method can outrank its containing class.
                obj = left.child_by_field_name("object")
                if obj is not None and obj.type == "member_expression":
                    obj_prop = obj.child_by_field_name("property")
                    obj_base = obj.child_by_field_name("object")
                    if (
                        obj_prop is not None and obj_base is not None
                        and obj_base.type == "identifier"
                        and source[obj_prop.start_byte:obj_prop.end_byte].decode() == "prototype"
                    ):
                        prototype_owner = source[obj_base.start_byte:obj_base.end_byte].decode()
            value = right
            is_function = right is not None and right.type in {"arrow_function", "function_expression", "generator_function"}
        # Exported constants are public API symbols too, even when their value
        # is data (regex/schema/config) rather than a function. Local variables
        # remain excluded so implementation temporaries do not flood the index.
        accepted = bool(name) and (node.type in declarations or is_function or is_exported_variable)
        next_parents = parents
        if accepted:
            extent = node
            # Include export/decorators, but never include sibling declarators.
            if node.parent and node.parent.type == "export_statement": extent = node.parent
            if node.type == "variable_declarator" and node.parent.type in {"lexical_declaration", "variable_declaration"}:
                if len([c for c in node.parent.named_children if c.type == "variable_declarator"]) == 1:
                    extent = node.parent
                    if extent.parent and extent.parent.type == "export_statement": extent = extent.parent
            body = (value if is_function else node).child_by_field_name("body")
            # Exported data variables have no function/class body. Treat their
            # value as the signature boundary so a huge regex/object literal is
            # shown in the exact source window but does not get double-counted
            # as high-weight signature vocabulary.
            if is_exported_variable and not is_function and value is not None:
                body = value
            # type_alias_declaration has no "body" field -- its right-hand side
            # sits under "value" instead, so truncate it like other bodies.
            if body is None and node.type == "type_alias_declaration" and value is not None:
                body = value
            head_end = body.start_byte if body else node.end_byte
            signature = " ".join(source[extent.start_byte:head_end].decode().split())
            if body: signature += " { … }" if body.type in {"statement_block", "class_body", "interface_body", "object_type", "mapped_type"} else " …"
            end_line = extent.end_point.row + (1 if extent.end_point.column else 0)
            qualifier = (*parents, prototype_owner, name) if prototype_owner else (*parents, name)
            identity_line = (
                identity_node.start_point.row + 1
                if identity_node is not None else extent.start_point.row + 1
            )
            if node.type in {"class_declaration", "abstract_class_declaration"}:
                kind = "class"
            elif node.type == "interface_declaration":
                kind = "interface"
            elif node.type == "enum_declaration":
                kind = "enum"
            elif node.type == "type_alias_declaration":
                kind = "type"
            elif node.type in {"method_definition", "method_signature", "abstract_method_signature"}:
                kind = "constructor" if name == "constructor" else "method"
            elif node.type in {"function_declaration", "generator_function_declaration", "function_signature"}:
                kind = "function"
            elif is_function:
                kind = "method" if parents or prototype_owner else "function"
            else:
                kind = "variable"
            found.append(Symbol(
                name, ".".join(qualifier), extent.start_point.row + 1,
                max(extent.start_point.row + 1, end_line),
                extent.start_byte, extent.end_byte, signature,
                kind=kind, identity_line=identity_line,
            ))
            # Only a genuine container (class/interface/enum) prefixes its
            # descendants' qualified names -- an ordinary function or method
            # does not, even though it may itself contain a nested helper
            # function. A class groups multiple members that can each
            # independently be the right, narrower answer to a query; a
            # function's nested helper is just an implementation detail of
            # that one function, not a sibling candidate answer. Without
            # this distinction, pack.py's parent-credit symbol-window boost
            # (which trusts a "parent" link as evidence of that grouping
            # relationship) would apply to both alike.
            if node.type in containers:
                next_parents = (*parents, name)
        elif is_object and name:
            next_parents = (*parents, name)
        for child in node.named_children:
            walk(child, next_parents)
    walk(tree.root_node)
    return found


STRUCTURED_EXTRA = {".go", ".rs", ".java", ".cs"}


@lru_cache(maxsize=4)
def _extra_language(suffix: str):
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


def _rightmost_identifier(source: bytes, node) -> str | None:
    if node is None:
        return None
    if node.type in {
        "identifier", "field_identifier", "type_identifier",
        "scoped_identifier", "namespace_identifier",
    }:
        raw = _text(source, node).strip()
        if "::" in raw:
            return raw.rsplit("::", 1)[-1]
        if "." in raw:
            return raw.rsplit(".", 1)[-1]
        return raw
    for field in ("method", "name", "field", "property", "function", "type"):
        child = node.child_by_field_name(field)
        value = _rightmost_identifier(source, child) if child is not None else None
        if value:
            return value
    for child in reversed(node.named_children):
        value = _rightmost_identifier(source, child)
        if value:
            return value
    return None


def _structured_call_sites(source: bytes, root, suffix: str) -> list[tuple[int, str]]:
    sites: list[tuple[int, str]] = []
    call_types = {
        ".go": {"call_expression"},
        ".rs": {"call_expression", "method_call_expression"},
        ".java": {"method_invocation", "object_creation_expression"},
        ".cs": {"invocation_expression", "object_creation_expression"},
    }[suffix]
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in call_types:
            target = None
            if node.type == "method_invocation":
                target = node.child_by_field_name("name")
            elif node.type == "method_call_expression":
                target = node.child_by_field_name("method") or node.child_by_field_name("name")
            elif node.type == "object_creation_expression":
                target = node.child_by_field_name("type")
            else:
                target = node.child_by_field_name("function") or node.child_by_field_name("name")
            name = _rightmost_identifier(source, target or node)
            if name and name not in {"if", "for", "while", "match", "switch", "return"}:
                sites.append((node.start_byte, name))
        stack.extend(reversed(node.named_children))
    return sites


def _attach_structured_calls(source: bytes, root, suffix: str, found: list[Symbol]) -> list[Symbol]:
    sites = _structured_call_sites(source, root, suffix)
    callable_kinds = {"function", "method", "constructor"}
    for symbol in found:
        if symbol.kind not in callable_kinds:
            continue
        symbol.calls = tuple(sorted({
            name for position, name in sites
            if symbol.start_byte <= position < symbol.end_byte
        }))
    return found


def structured_imports(text: str, suffix: str) -> set[str]:
    """Return parser-backed import/use targets for non-JS structured languages."""
    from tree_sitter import Parser

    suffix = suffix.lower()
    if suffix not in STRUCTURED_EXTRA:
        return set()
    source = text.encode("utf-8")
    tree = Parser(_extra_language(suffix)).parse(source)
    if tree.root_node.has_error:
        return set()
    node_types = {
        ".go": {"import_spec"},
        ".rs": {"use_declaration"},
        ".java": {"import_declaration"},
        ".cs": {"using_directive"},
    }[suffix]
    out: set[str] = set()
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in node_types:
            raw = " ".join(_text(source, node).split()).strip()
            if suffix == ".go":
                path = node.child_by_field_name("path")
                raw = _text(source, path).strip("\"`") if path is not None else raw
            elif suffix == ".rs":
                raw = raw.removeprefix("use ").removesuffix(";").replace("::", ".")
                raw = raw.split(" as ", 1)[0].strip()
            elif suffix == ".java":
                raw = raw.removeprefix("import ").removesuffix(";").strip()
                raw = raw.removeprefix("static ").strip()
            else:
                raw = raw.removeprefix("global ").removeprefix("using ").removesuffix(";").strip()
                if "=" in raw:
                    raw = raw.split("=", 1)[1].strip()
            if raw:
                out.add(raw)
        stack.extend(reversed(node.named_children))
    return out

def _append(found: list[Symbol], source: bytes, *, name: str, node, body=None,
            parents=(), kind: str = "symbol", extent=None) -> None:
    extent = extent or node
    qualified = ".".join((*parents, name)) if parents else name
    name_node = node.child_by_field_name("name")
    identity_line = (
        name_node.start_point.row + 1
        if name_node is not None else node.start_point.row + 1
    )
    found.append(Symbol(
        name=name,
        qualified=qualified,
        start=extent.start_point.row + 1,
        end=max(extent.start_point.row + 1, _line_end(extent)),
        start_byte=extent.start_byte,
        end_byte=extent.end_byte,
        signature=_signature(source, extent, body),
        kind=kind,
        identity_line=identity_line,
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


def _symbols_extra(text: str, suffix: str) -> list[Symbol]:
    """Return exact structural symbols for a supported non-JS language."""
    from tree_sitter import Parser

    suffix = suffix.lower()
    if suffix not in STRUCTURED_EXTRA:
        raise ValueError(f"unsupported structured language: {suffix}")

    source = text.encode("utf-8")
    tree = Parser(_extra_language(suffix)).parse(source)

    if suffix == ".go":
        found = _go_symbols(source, tree.root_node)
    elif suffix == ".rs":
        found = _rust_symbols(source, tree.root_node)
    elif suffix == ".java":
        found = _java_symbols(source, tree.root_node)
    else:
        found = _csharp_symbols(source, tree.root_node)

    # Error recovery still provides exact declaration nodes around unsupported
    # or newer syntax. Discarding the whole tree on one ERROR node degraded
    # large real-world C# files to the generic regex fallback and erased their
    # methods. Keep recovered symbols; fall back only when nothing structural
    # survived.
    if tree.root_node.has_error and not found:
        raise ValueError("Source has syntax errors; use an explicit source range instead")
    return _attach_structured_calls(source, tree.root_node, suffix, found)

def symbols(text: str, suffix: str) -> list[Symbol]:
    """Return exact structural symbols for any parser-backed language."""
    suffix = suffix.lower()
    try:
        if suffix in JS_TS:
            return _symbols_js_ts(text, suffix)
        if suffix in STRUCTURED_EXTRA:
            return _symbols_extra(text, suffix)
    except RecursionError as exc:
        # The per-language tree walkers are recursive, and generated code
        # (a 3000-term chained expression, a deeply nested data literal) can
        # be far deeper than Python's recursion limit. Report it as the same
        # "cannot parse structurally" ValueError callers already degrade on,
        # instead of letting one file abort indexing for the whole repository.
        raise ValueError("Source is too deeply nested for structural parsing") from exc
    raise ValueError(f"unsupported structured language: {suffix}")

def extract(text: str, suffix: str, name: str):
    matches = [s for s in symbols(text, suffix) if s.qualified == name or ("." not in name and s.name == name)]
    if not matches: return None
    if len(matches) != 1:
        raise ValueError("Ambiguous symbol; use a qualified name: " + ", ".join(s.qualified for s in matches))
    symbol = matches[0]
    body = text.encode()[symbol.start_byte:symbol.end_byte].decode()
    return f"# {symbol.qualified}  lines {symbol.start}-{symbol.end}\n{body}\n", symbol.start, symbol.end