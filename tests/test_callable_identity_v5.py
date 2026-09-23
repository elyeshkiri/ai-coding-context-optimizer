import textwrap

from acco.pack import build_context_pack, _query_member_hints
from acco.repo_index import record_for_text


def _line(source: str, needle: str) -> int:
    return next(
        i for i, line in enumerate(source.splitlines(), start=1)
        if needle in line
    )


def test_member_hints_accept_lowercase_members():
    assert ("stringutils", "split") in _query_member_hints(
        "which StringUtils split overload accepts a String"
    )
    assert ("selectquerybuilder", "select") in _query_member_hints(
        "which SelectQueryBuilder select overload accepts an array"
    )
    assert ("sender", "send") in _query_member_hints(
        "where does Sender send a value"
    )


def test_typescript_symbols_keep_callable_kinds():
    source = textwrap.dedent("""
        export class Client {
          run(value: string): void;
          run(value: string): void {}
        }
        export function createClient(): Client { return new Client(); }
    """)
    record = record_for_text("api.ts", source)
    by_line = {(d.name, d.identity_line): d for d in record.definitions or []}

    method_lines = [
        line for (name, line), d in by_line.items()
        if name == "run" and d.qualified == "Client.run"
    ]
    assert len(method_lines) == 2
    assert all(by_line[("run", line)].kind == "method" for line in method_lines)
    create = next(d for d in record.definitions or [] if d.name == "createClient")
    assert create.kind == "function"


def _typescript_overload_fixture() -> str:
    return textwrap.dedent("""
        export class SelectQueryBuilder {
          select(): this;
          select(
            selection: (qb: SelectQueryBuilder) => SelectQueryBuilder,
            selectionAliasName?: string,
          ): this;
          select(selection: string, selectionAliasName?: string): this;
          select(selection: string[]): this;
          select(
            selection?: string | string[] | ((qb: SelectQueryBuilder) => SelectQueryBuilder),
            selectionAliasName?: string,
          ): this {
            return this;
          }
        }
    """)


def test_typescript_overload_array_and_zero_arg_identity(tmp_path):
    source = _typescript_overload_fixture()
    path = tmp_path / "SelectQueryBuilder.ts"
    path.write_text(source)

    array_pack = build_context_pack(
        tmp_path,
        "which SelectQueryBuilder select overload accepts an array of string selections",
        max_tokens=2200,
        changed_boost=False,
        persist_index=False,
    )
    array_line = _line(source, "select(selection: string[]): this;")
    assert (
        f"SelectQueryBuilder.ts:SelectQueryBuilder.select@{array_line}"
        in array_pack.selected_symbol_identities
    )

    empty_pack = build_context_pack(
        tmp_path,
        "which SelectQueryBuilder select overload takes no arguments",
        max_tokens=2200,
        changed_boost=False,
        persist_index=False,
    )
    empty_line = _line(source, "select(): this;")
    assert (
        f"SelectQueryBuilder.ts:SelectQueryBuilder.select@{empty_line}"
        in empty_pack.selected_symbol_identities
    )


def test_typescript_query_can_prefer_overload_declaration_or_implementation(tmp_path):
    source = _typescript_overload_fixture()
    (tmp_path / "SelectQueryBuilder.ts").write_text(source)

    declaration = build_context_pack(
        tmp_path,
        "which SelectQueryBuilder select overload accepts a string selection plus optional alias",
        max_tokens=2200,
        changed_boost=False,
        persist_index=False,
    )
    declaration_line = _line(
        source, "select(selection: string, selectionAliasName?: string): this;"
    )
    assert (
        f"SelectQueryBuilder.ts:SelectQueryBuilder.select@{declaration_line}"
        in declaration.selected_symbol_identities
    )

    implementation = build_context_pack(
        tmp_path,
        "where is the SelectQueryBuilder select implementation accepting optional string, "
        "string array, or callback union",
        max_tokens=2200,
        changed_boost=False,
        persist_index=False,
    )
    implementation_line = _line(source, "selection?: string | string[]")
    # Identity is the method-name line, one line above the union parameter.
    implementation_line -= 1
    assert (
        f"SelectQueryBuilder.ts:SelectQueryBuilder.select@{implementation_line}"
        in implementation.selected_symbol_identities
    )


def test_package_level_typescript_function_beats_same_named_class_method(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    class_source = textwrap.dedent("""
        export class ClassTransformer {
          instanceToPlain<T>(object: T): object;
          instanceToPlain<T>(object: T[]): object[];
          instanceToPlain<T>(object: T | T[]): object | object[] { return object; }
        }
    """)
    index_source = textwrap.dedent("""
        export function instanceToPlain<T>(object: T): object;
        export function instanceToPlain<T>(object: T[]): object[];
        export function instanceToPlain<T>(object: T | T[]): object | object[] {
          return object;
        }
    """)
    (src / "ClassTransformer.ts").write_text(class_source)
    (src / "index.ts").write_text(index_source)

    pack = build_context_pack(
        tmp_path,
        "which package-level instanceToPlain overload in src/index.ts accepts one object T rather than an array",
        max_tokens=2200,
        changed_boost=False,
        persist_index=False,
    )

    line = _line(index_source, "export function instanceToPlain<T>(object: T): object;")
    assert f"src/index.ts:instanceToPlain@{line}" in pack.selected_symbol_identities


def test_java_dense_overloads_use_parameter_shape_and_negative_terms(tmp_path):
    source = textwrap.dedent("""
        public class StringUtils {
          public static String[] split(String str) { return null; }
          public static String[] split(String str, char separatorChar) { return null; }
          public static String[] split(String str, String separatorChars) { return null; }
          public static String[] split(String str, String separatorChars, int max) { return null; }
          public static String substring(String str, int start) { return str; }
          public static String substring(String str, int start, int end) { return str; }
        }
    """)
    (tmp_path / "StringUtils.java").write_text(source)

    split_pack = build_context_pack(
        tmp_path,
        "which StringUtils split overload accepts only a String input and splits on whitespace",
        max_tokens=1800,
        changed_boost=False,
        persist_index=False,
    )
    split_line = _line(source, "split(String str)")
    assert (
        f"StringUtils.java:StringUtils.split@{split_line}"
        in split_pack.selected_symbol_identities
    )

    substring_pack = build_context_pack(
        tmp_path,
        "which StringUtils substring overload accepts String and start index without an end index",
        max_tokens=1800,
        changed_boost=False,
        persist_index=False,
    )
    substring_line = _line(source, "substring(String str, int start)")
    assert (
        f"StringUtils.java:StringUtils.substring@{substring_line}"
        in substring_pack.selected_symbol_identities
    )


def test_rust_lowercase_member_hint_disambiguates_receiver(tmp_path):
    source = textwrap.dedent("""
        pub struct Sender<T> { value: T }
        impl<T> Sender<T> {
            pub async fn send(&self, value: T) -> Result<(), ()> { Ok(()) }
        }

        pub struct Permit<T> { value: T }
        impl<T> Permit<T> {
            pub fn send(self, value: T) {}
        }

        pub struct OwnedPermit<T> { value: T }
        impl<T> OwnedPermit<T> {
            pub fn send(self, value: T) -> Sender<T> { Sender { value } }
        }
    """)
    (tmp_path / "bounded.rs").write_text(source)

    pack = build_context_pack(
        tmp_path,
        "where does Sender send asynchronously send a T and return Result",
        max_tokens=1800,
        changed_boost=False,
        persist_index=False,
    )

    line = _line(source, "pub async fn send")
    assert f"bounded.rs:Sender.send@{line}" in pack.selected_symbol_identities


def test_go_package_level_scope_beats_same_named_receivers(tmp_path):
    (tmp_path / "entry.go").write_text(textwrap.dedent("""
        package p
        type Entry struct{}
        func (entry *Entry) Print(args ...any) {}
    """))
    (tmp_path / "logger.go").write_text(textwrap.dedent("""
        package p
        type Logger struct{}
        func (logger *Logger) Print(args ...any) {}
    """))
    exported = textwrap.dedent("""
        package p
        func Print(args ...any) {}
    """)
    (tmp_path / "exported.go").write_text(exported)

    pack = build_context_pack(
        tmp_path,
        "where is the package-level Print function that forwards args through the standard logger",
        max_tokens=1600,
        changed_boost=False,
        persist_index=False,
    )

    line = _line(exported, "func Print")
    assert f"exported.go:Print@{line}" in pack.selected_symbol_identities
