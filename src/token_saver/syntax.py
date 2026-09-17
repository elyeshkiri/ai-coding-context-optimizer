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
        if node.type == "pair":
            key = node.child_by_field_name("key")
            if key: name = source[key.start_byte:key.end_byte].decode().strip("\"'")
            is_function = value is not None and value.type in {"arrow_function", "function_expression"}
            is_object = value is not None and value.type == "object"
        accepted = bool(name) and (node.type in declarations or is_function)
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
            # type_alias_declaration has no "body" field -- its right-hand side
            # sits under "value" instead, so it previously went untruncated
            # into the signature no matter its shape (object type, intersection
            # with other types, etc.), double-counting every word in it at
            # both the 20x name-term weight (via signature) and the 1x
            # body-term weight the type already gets like any other symbol's
            # body. Truncate it the same way a function/class body is.
            if body is None and node.type == "type_alias_declaration" and value is not None:
                body = value
            head_end = body.start_byte if body else node.end_byte
            signature = " ".join(source[extent.start_byte:head_end].decode().split())
            if body: signature += " { … }" if body.type in {"statement_block", "class_body", "interface_body", "object_type", "mapped_type"} else " …"
            end_line = extent.end_point.row + (1 if extent.end_point.column else 0)
            found.append(Symbol(name, ".".join((*parents, name)), extent.start_point.row + 1,
                                max(extent.start_point.row + 1, end_line), extent.start_byte, extent.end_byte, signature))
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
