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

@lru_cache(maxsize=3)
def _language(suffix):
    from tree_sitter import Language
    if suffix in {".ts", ".tsx"}:
        import tree_sitter_typescript as grammar
        return Language(grammar.language_tsx() if suffix == ".tsx" else grammar.language_typescript())
    import tree_sitter_javascript as grammar
    return Language(grammar.language())

def symbols(text: str, suffix: str) -> list[Symbol]:
    from tree_sitter import Parser
    source = text.encode("utf-8")
    tree = Parser(_language(suffix)).parse(source)
    if tree.root_node.has_error:
        raise ValueError("Source has syntax errors; use an explicit source range instead")
    found = []
    declarations = {"function_declaration", "generator_function_declaration", "class_declaration",
                    "abstract_class_declaration", "interface_declaration", "type_alias_declaration",
                    "enum_declaration", "method_definition", "method_signature", "abstract_method_signature"}
    containers = {"class_declaration", "abstract_class_declaration", "interface_declaration", "enum_declaration"}
    def walk(node, parents=()):
        name_node = node.child_by_field_name("name")
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
            if key: name = source[key.start_byte:key.end_byte].decode().strip("\"'")
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
            found.append(Symbol(name, ".".join(qualifier), extent.start_point.row + 1,
                                max(extent.start_point.row + 1, end_line), extent.start_byte, extent.end_byte, signature))
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

def extract(text: str, suffix: str, name: str):
    matches = [s for s in symbols(text, suffix) if s.qualified == name or ("." not in name and s.name == name)]
    if not matches: return None
    if len(matches) != 1:
        raise ValueError("Ambiguous symbol; use a qualified name: " + ", ".join(s.qualified for s in matches))
    symbol = matches[0]
    body = text.encode()[symbol.start_byte:symbol.end_byte].decode()
    return f"# {symbol.qualified}  lines {symbol.start}-{symbol.end}\n{body}\n", symbol.start, symbol.end