import textwrap

from token_saver.pack import build_context_pack
from token_saver.repo_index import record_for_text


def _line(source: str, needle: str) -> int:
    return next(
        i for i, line in enumerate(source.splitlines(), start=1)
        if needle in line
    )


def _extension_fixture() -> str:
    return textwrap.dedent("""
        namespace Demo;

        public static partial class RestRequestExtensions {
            // extension(Fake ignored) { public Fake Nope() {} }
            private const string Sample = "extension(Fake ignored) { }";

            extension(RestRequest request) {
                public RestRequest AddBody(object obj, ContentType? contentType = null) {
                    return request;
                }

                public RestRequest AddStringBody(string body, DataFormat dataFormat) {
                    return request;
                }

                public RestRequest AddStringBody(string body, ContentType contentType)
                    => request;

                public RestRequest AddJsonBody<T>(
                    T obj,
                    ContentType? contentType = null
                ) where T : class {
                    return request;
                }
            }
        }
    """)


def test_csharp14_extension_block_methods_are_structural_symbols():
    source = _extension_fixture()
    record = record_for_text("RestRequestExtensions.cs", source)
    definitions = record.definitions or []

    methods = [d for d in definitions if d.kind == "method"]
    by_identity = {
        (d.qualified, d.identity_line): d
        for d in methods
    }

    expected = {
        ("RestRequestExtensions.AddBody", _line(source, "public RestRequest AddBody")),
        (
            "RestRequestExtensions.AddStringBody",
            _line(source, "public RestRequest AddStringBody(string body, DataFormat"),
        ),
        (
            "RestRequestExtensions.AddStringBody",
            _line(source, "public RestRequest AddStringBody(string body, ContentType"),
        ),
        ("RestRequestExtensions.AddJsonBody", _line(source, "public RestRequest AddJsonBody<T>")),
    }
    assert expected <= set(by_identity)

    for key in expected:
        symbol = by_identity[key]
        assert "extension(RestRequest request)" in symbol.signature

    assert not any(d.name == "Nope" for d in definitions)


def test_csharp14_extension_block_overloads_resolve_exact_identity(tmp_path):
    source = _extension_fixture()
    path = tmp_path / "RestRequestExtensions.cs"
    path.write_text(source)

    data_format = build_context_pack(
        tmp_path,
        "which RestRequestExtensions AddStringBody overload accepts string body and DataFormat",
        max_tokens=1800,
        changed_boost=False,
        persist_index=False,
    )
    data_format_line = _line(
        source, "public RestRequest AddStringBody(string body, DataFormat"
    )
    assert (
        f"RestRequestExtensions.cs:RestRequestExtensions.AddStringBody@{data_format_line}"
        in data_format.selected_symbol_identities
    )

    content_type = build_context_pack(
        tmp_path,
        "which RestRequestExtensions AddStringBody overload accepts string body and ContentType",
        max_tokens=1800,
        changed_boost=False,
        persist_index=False,
    )
    content_type_line = _line(
        source, "public RestRequest AddStringBody(string body, ContentType"
    )
    assert (
        f"RestRequestExtensions.cs:RestRequestExtensions.AddStringBody@{content_type_line}"
        in content_type.selected_symbol_identities
    )

    generic = build_context_pack(
        tmp_path,
        "which generic RestRequestExtensions AddJsonBody<T> overload accepts a T object and optional ContentType where T is a class",
        max_tokens=1800,
        changed_boost=False,
        persist_index=False,
    )
    generic_line = _line(source, "public RestRequest AddJsonBody<T>")
    assert (
        f"RestRequestExtensions.cs:RestRequestExtensions.AddJsonBody@{generic_line}"
        in generic.selected_symbol_identities
    )


def test_csharp14_extension_receiver_terms_are_available_for_ranking(tmp_path):
    source = textwrap.dedent("""
        public static class RequestExtensions {
            extension(RestRequest request) {
                public RestRequest AddValue(string value) => request;
            }
        }

        public static class ResponseExtensions {
            extension(RestResponse response) {
                public RestResponse AddValue(string value) => response;
            }
        }
    """)
    (tmp_path / "Extensions.cs").write_text(source)

    pack = build_context_pack(
        tmp_path,
        "where is RequestExtensions AddValue on RestRequest",
        max_tokens=1600,
        changed_boost=False,
        persist_index=False,
    )

    line = _line(source, "public RestRequest AddValue")
    assert (
        f"Extensions.cs:RequestExtensions.AddValue@{line}"
        in pack.selected_symbol_identities
    )
