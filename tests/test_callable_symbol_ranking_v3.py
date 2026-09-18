import textwrap

from token_saver.lexical import symbol_terms, terms
from token_saver.pack import build_context_pack
from token_saver.repo_index import record_for_text


def test_symbol_scope_keeps_api_verbs_that_file_scope_treats_as_stopwords():
    assert "create" not in terms("create widget")
    assert "build" not in terms("build request")
    assert "add" not in terms("add child")
    assert {"create", "build", "add"} <= set(
        symbol_terms("create widget build request add child")
    )


def test_exact_leaf_create_beats_broad_sibling_signature(tmp_path):
    source = textwrap.dedent("""
        public class WidgetFactory {
            public Widget PrepareWidgetCreationPipeline(Widget value) {
                return NormalizeWidget(value);
            }

            public Widget Create() {
                return NewWidget();
            }
        }
    """)
    (tmp_path / "WidgetFactory.cs").write_text(source)

    pack = build_context_pack(
        tmp_path,
        "create widget factory",
        max_tokens=700,
        changed_boost=False,
    )

    assert any(
        identity.startswith("WidgetFactory.cs:WidgetFactory.Create@")
        for identity in pack.selected_symbol_identities
    )


def test_exact_leaf_build_beats_earlier_same_container_method(tmp_path):
    source = textwrap.dedent("""
        pub struct RequestBuilder;

        impl RequestBuilder {
            pub fn configure_request_transport(&self) -> Request {
                self.prepare()
            }

            pub fn build(&self) -> Request {
                self.finish()
            }
        }
    """)
    (tmp_path / "request.rs").write_text(source)

    pack = build_context_pack(
        tmp_path,
        "build request builder",
        max_tokens=700,
        changed_boost=False,
    )

    assert any(
        identity.startswith("request.rs:RequestBuilder.build@")
        for identity in pack.selected_symbol_identities
    )


def test_add_command_identifier_action_survives_symbol_scope(tmp_path):
    source = textwrap.dedent("""
        package cli

        type Command struct {
            children []*Command
        }

        func (c *Command) ConfigureChildren(children ...*Command) {
            c.children = children
        }

        func (c *Command) AddCommand(children ...*Command) {
            c.children = append(c.children, children...)
        }
    """)
    (tmp_path / "command.go").write_text(source)

    pack = build_context_pack(
        tmp_path,
        "add command child",
        max_tokens=700,
        changed_boost=False,
    )

    assert any(
        identity.startswith("command.go:Command.AddCommand@")
        for identity in pack.selected_symbol_identities
    )


def test_identity_line_uses_java_declaration_not_annotation_extent():
    source = textwrap.dedent("""        public class Handler {
            @Deprecated
            public void Run() {
                Execute();
            }
        }
    """)
    record = record_for_text("Handler.java", source)
    run = next(item for item in record.definitions or [] if item.name == "Run")

    assert run.start_line <= 3
    assert run.identity_line == 3
    assert run.qualified == "Handler.Run"


def test_identity_line_disambiguates_annotated_csharp_overloads(tmp_path):
    source = textwrap.dedent("""        public class Formatter {
            [Obsolete]
            public string Format(int value) {
                return value.ToString();
            }

            public string Format(string value) {
                return value.Trim();
            }
        }
    """)
    (tmp_path / "Formatter.cs").write_text(source)

    pack = build_context_pack(
        tmp_path,
        "Formatter Format string Trim",
        max_tokens=900,
        changed_boost=False,
    )

    assert "Formatter.cs:Formatter.Format@7" in set(pack.selected_symbol_identities)
