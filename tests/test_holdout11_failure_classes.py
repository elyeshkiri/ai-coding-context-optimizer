import textwrap

from acco.pack import build_context_pack, rank_files
from acco.repo_index import record_for_text


def _line(source: str, needle: str) -> int:
    return next(
        i for i, line in enumerate(source.splitlines(), start=1)
        if needle in line
    )


def test_typescript_partial_parse_keeps_valid_interface_members():
    source = textwrap.dedent("""
        export interface Slice<State> {
          getSelectors(): State
          getSelectors<RootState>(selectState: (root: RootState) => State): State
          injectInto<NewPath extends string>(value: State): State
        }

        const unsupported = ;
    """)

    record = record_for_text("createSlice.ts", source)
    identities = {
        (d.qualified, d.identity_line)
        for d in record.definitions or []
    }

    assert (
        "Slice.getSelectors",
        _line(source, "getSelectors(): State"),
    ) in identities
    assert (
        "Slice.getSelectors",
        _line(source, "getSelectors<RootState>"),
    ) in identities
    assert (
        "Slice.injectInto",
        _line(source, "injectInto<NewPath"),
    ) in identities


def test_typescript_interface_overloads_resolve_container_and_generic_identity(tmp_path):
    source = textwrap.dedent("""
        export interface Slice<State> {
          getSelectors(): State
          getSelectors<RootState>(selectState: (root: RootState) => State): State
          injectInto<NewReducerPath extends string>(
            injectable: { inject(value: State): void },
            config?: { reducerPath?: NewReducerPath },
          ): State
        }

        function getSelectors(selectState?: unknown) {
          return selectState
        }
    """)
    (tmp_path / "createSlice.ts").write_text(source)

    local_pack = build_context_pack(
        tmp_path,
        "which Slice getSelectors overload takes no arguments and returns State",
        max_tokens=1800,
        changed_boost=False,
        persist_index=False,
    )
    local_line = _line(source, "getSelectors(): State")
    assert (
        f"createSlice.ts:Slice.getSelectors@{local_line}"
        in local_pack.selected_symbol_identities
    )

    root_pack = build_context_pack(
        tmp_path,
        "which generic Slice getSelectors<RootState> overload accepts selectState callback",
        max_tokens=1800,
        changed_boost=False,
        persist_index=False,
    )
    root_line = _line(source, "getSelectors<RootState>")
    assert (
        f"createSlice.ts:Slice.getSelectors@{root_line}"
        in root_pack.selected_symbol_identities
    )

    inject_pack = build_context_pack(
        tmp_path,
        "where is Slice injectInto<NewReducerPath> accepting injectable and optional config",
        max_tokens=1800,
        changed_boost=False,
        persist_index=False,
    )
    inject_line = _line(source, "injectInto<NewReducerPath")
    assert (
        f"createSlice.ts:Slice.injectInto@{inject_line}"
        in inject_pack.selected_symbol_identities
    )


def test_negative_overload_terms_are_not_positive_evidence(tmp_path):
    source = textwrap.dedent("""
        public final class EntityUtils {
          public static String toString(HttpEntity entity, Charset defaultCharset) {
            return "";
          }

          public static String toString(
              HttpEntity entity, Charset defaultCharset, int maxResultLength) {
            return "";
          }

          public static String toString(HttpEntity entity, String defaultCharset) {
            return "";
          }

          public static String toString(HttpEntity entity, int maxResultLength) {
            return "";
          }
        }
    """)
    (tmp_path / "EntityUtils.java").write_text(source)

    charset_pack = build_context_pack(
        tmp_path,
        "which EntityUtils toString overload accepts HttpEntity and Charset "
        "defaultCharset without maxResultLength",
        max_tokens=1800,
        changed_boost=False,
        persist_index=False,
    )
    charset_line = _line(
        source, "public static String toString(HttpEntity entity, Charset defaultCharset)"
    )
    assert (
        f"EntityUtils.java:EntityUtils.toString@{charset_line}"
        in charset_pack.selected_symbol_identities
    )

    max_pack = build_context_pack(
        tmp_path,
        "which EntityUtils toString overload accepts HttpEntity and int "
        "maxResultLength without defaultCharset",
        max_tokens=1800,
        changed_boost=False,
        persist_index=False,
    )
    max_line = _line(
        source, "public static String toString(HttpEntity entity, int maxResultLength)"
    )
    assert (
        f"EntityUtils.java:EntityUtils.toString@{max_line}"
        in max_pack.selected_symbol_identities
    )


def test_top_level_same_name_prefers_exported_signature_match(tmp_path):
    target = tmp_path / "packages" / "utils" / "src"
    target.mkdir(parents=True)
    target_source = textwrap.dedent("""
        export function isPrimitive(value: unknown): boolean {
          return value === null
        }
    """)
    (target / "helpers.ts").write_text(target_source)

    runtime = tmp_path / "packages" / "runtime" / "src"
    runtime.mkdir(parents=True)
    (runtime / "utils.ts").write_text(textwrap.dedent("""
        export function isPrimitive(v: any): boolean {
          return v == null
        }
    """))

    ui = tmp_path / "packages" / "ui" / "src"
    ui.mkdir(parents=True)
    (ui / "error.ts").write_text(textwrap.dedent("""
        function isPrimitive(value: unknown): boolean {
          return typeof value !== 'object'
        }
    """))

    ranked = rank_files(
        tmp_path,
        "where is top-level isPrimitive accepting unknown value",
        changed_boost=False,
    )
    assert ranked[0].rel == "packages/utils/src/helpers.ts"

    pack = build_context_pack(
        tmp_path,
        "where is top-level isPrimitive accepting unknown value",
        max_tokens=1600,
        changed_boost=False,
        persist_index=False,
    )
    line = _line(target_source, "export function isPrimitive")
    assert (
        f"packages/utils/src/helpers.ts:isPrimitive@{line}"
        in pack.selected_symbol_identities
    )


def test_explicit_go_receiver_member_beats_many_common_callsites(tmp_path):
    target = textwrap.dedent("""
        package redis

        import "time"

        type Client struct{}

        func (c *Client) WithTimeout(timeout time.Duration) *Client {
            return c
        }
    """)
    (tmp_path / "redis.go").write_text(target)

    for i in range(14):
        (tmp_path / f"worker_{i}.go").write_text(textwrap.dedent(f"""
            package redis

            import (
                "context"
                "time"
            )

            func worker{i}(ctx context.Context) {{
                child, cancel := context.WithTimeout(ctx, time.Second)
                defer cancel()
                _ = child
            }}
        """))

    ranked = rank_files(
        tmp_path,
        "where is Client WithTimeout accepting time.Duration and returning Client",
        changed_boost=False,
    )
    assert ranked[0].rel == "redis.go"

    pack = build_context_pack(
        tmp_path,
        "where is Client WithTimeout accepting time.Duration and returning Client",
        max_tokens=1600,
        changed_boost=False,
        persist_index=False,
    )
    line = _line(target, "func (c *Client) WithTimeout")
    assert f"redis.go:Client.WithTimeout@{line}" in pack.selected_symbol_identities
