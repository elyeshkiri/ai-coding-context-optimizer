import textwrap

from acco.estimate import estimate_tokens
from acco.pack import build_context_pack, rank_files
from acco.pack_cli import main as pack_main
from acco.packing.contracts import RankedFile
from acco.packing.symbol_windows import _file_section
from acco.repo_index import build_index


def _write_repo(root):
    src = root / "src"
    src.mkdir()
    (src / "auth.py").write_text(textwrap.dedent("""
        class SessionManager:
            def refresh_session(self, refresh_token: str) -> str:
                account = self.lookup_refresh_token(refresh_token)
                return self.rotate_session(account)

            def revoke_session(self, session_id: str) -> None:
                self.store.delete(session_id)
    """))
    (src / "billing.py").write_text(textwrap.dedent("""
        class InvoiceService:
            def create_invoice(self, customer_id: str) -> bytes:
                subtotal = self.calculate_subtotal(customer_id)
                return self.render_pdf(subtotal)
    """))
    (src / "cache.py").write_text(textwrap.dedent("""
        class Cache:
            def get(self, key: str):
                return self.redis.get(key)
    """))
    return root


def test_rank_files_prefers_task_relevance(tmp_path):
    root = _write_repo(tmp_path)
    ranked = rank_files(root, "refresh authentication session token", changed_boost=False)
    assert ranked[0].rel == "src/auth.py"
    assert ranked[0].term_hits > ranked[-1].term_hits


def test_context_pack_contains_exact_source_window(tmp_path):
    root = _write_repo(tmp_path)
    pack = build_context_pack(
        root,
        "rotate refresh session",
        max_tokens=1200,
        changed_boost=False,
    )
    assert "## src/auth.py" in pack.text
    assert "### exact source windows" in pack.text
    assert "return self.rotate_session(account)" in pack.text
    assert "|" in pack.text, "source windows should carry exact line gutters"


def test_structural_windows_precede_semantic_ranges_without_explicit_target(tmp_path):
    """Tight fitting should encounter parser-backed source before embedding ranges."""
    root = tmp_path
    source = textwrap.dedent(
        """
        def target_behavior(record):
            return record.authoritative_value

        def helper_one():
            return 1

        def helper_two():
            return 2

        def semantic_distractor(record):
            return record.related_but_secondary_value
        """
    )
    path = root / "target.py"
    path.write_text(source, encoding="utf-8")
    index = build_index(root, persist=False)
    record = index.records["target.py"]
    item = RankedFile(
        path=path,
        rel="target.py",
        text=source,
        outline=record.outline,
        score=10.0,
        reasons=["term-hits:2"],
        term_hits=2,
        semantic_ranges=[(10, 11)],
    )

    section, labels, _identities, _redactions = _file_section(
        item,
        {"target", "behavior"},
        1,
        index,
        symbol_query_text="target behavior",
    )

    assert labels
    assert "def target_behavior" in section
    assert "def semantic_distractor" in section
    assert section.index("def target_behavior") < section.index(
        "def semantic_distractor"
    )


def test_context_pack_respects_hard_token_budget(tmp_path):
    root = _write_repo(tmp_path)
    for n in range(8):
        (root / "src" / f"worker_{n}.py").write_text(
            f"def process_refresh_session_{n}(payload):\n" +
            "\n".join(f"    step_{i}(payload)" for i in range(120)) + "\n"
        )
    pack = build_context_pack(
        root,
        "refresh session worker",
        max_tokens=240,
        max_files=20,
        changed_boost=False,
    )
    assert pack.estimated_tokens <= 240
    assert estimate_tokens(pack.text) <= 240


def test_context_pack_does_not_let_one_large_file_monopolize_the_budget(tmp_path):
    # Found via the second, larger frozen external holdout (click/pydantic/
    # requests/...): a single large, top-ranked file (typically a sprawling
    # test file matching the query's vocabulary broadly) could consume
    # nearly the entire budget by itself, leaving a smaller but genuinely
    # relevant file -- sometimes the *actual* correct answer -- with zero
    # room, even though it ranked a clear, un-ambiguous #2. Real numbers:
    # tests/test_validators.py alone used 5993 of pydantic's 6000-token
    # budget, starving out functional_validators.py entirely.
    src = tmp_path / "src"
    src.mkdir()
    lines = []
    for n in range(400):
        lines.append(f"def validate_schema_configuration_settings_request_{n}(value):")
        lines.append(f"    # validate schema configuration settings request number {n}")
        lines.append(f"    return value + {n}")
        lines.append("")
    (src / "big_consumer.py").write_text("\n".join(lines))
    (src / "target_provider.py").write_text(textwrap.dedent("""
        def process_configuration_settings(request):
            # validate schema for the configuration settings request
            return request.settings
    """))

    pack = build_context_pack(
        tmp_path,
        "validate schema for configuration settings request",
        max_tokens=1500,
        changed_boost=False,
    )

    assert "src/target_provider.py" in pack.selected_files


def test_symbol_window_matches_acronym_prefixed_class_name(tmp_path):
    # Found via the second frozen external holdout (psf/requests):
    # HTTPBasicAuth's own name previously tokenized as one fused word
    # ("httpbasic") rather than ["http", "basic", "auth"] (see
    # test_lexical.py), so it scored 0 against a query naming exactly what
    # it does -- two unrelated helper functions that merely mention
    # "basic"/"http" in prose comments won the symbol-window competition
    # instead, even though the class is the obviously correct answer.
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text(textwrap.dedent("""
        def _basic_auth_str(username, password):
            # Encode a basic auth Authorization header value for HTTP requests.
            # Basic authentication combines username and password with base64.
            credentials = f"{username}:{password}"
            return "Basic " + credentials


        def handle_http_error(response):
            # Handle an HTTP error response for basic authentication retries.
            if response.status_code == 401:
                return True
            return False


        class HTTPBasicAuth:
            def __init__(self, username, password):
                self.username = username
                self.password = password
    """))

    pack = build_context_pack(
        tmp_path,
        "where is HTTP basic authentication implemented",
        max_tokens=800,
        changed_boost=False,
    )

    assert any(label.startswith("src/auth.py:HTTPBasicAuth@") for label in pack.selected_symbols)


def test_rank_files_prefers_implementation_over_test_file_for_how_does_x_work(tmp_path):
    # Found via the second frozen external holdout (pallets/click): a test
    # file that exercises a feature extensively legitimately shares a lot
    # of vocabulary with a query about that feature, and its sheer term
    # volume can outscore the terser implementation even though
    # file_priority() already correctly tags test/doc/fixture directories
    # as low-value -- that signal was only a flat +0.3-vs-+1.2 additive
    # bonus, dwarfed by BM25 scores routinely in the tens of points.
    src = tmp_path / "src"
    src.mkdir()
    (src / "parser.py").write_text(textwrap.dedent("""
        class OptionParser:
            def parse_args(self, args):
                # Parse raw command line arguments into option and positional values.
                return args
    """))
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    lines = ["import pytest", "", "def test_parse_args_option_and_positional_values():"]
    for n in range(60):
        lines.append(f"    # parse raw command line arguments into option and positional values case {n}")
        lines.append(f'    assert parse_args(["--opt{n}", "pos{n}"]) == ["opt{n}", "pos{n}"]')
    (tests_dir / "test_parser.py").write_text("\n".join(lines))

    ranked = rank_files(
        tmp_path,
        "how does the parser parse raw command line arguments into option and positional values",
        changed_boost=False,
    )

    assert ranked[0].rel == "src/parser.py"


def test_changed_file_gets_bonus(tmp_path, monkeypatch):
    root = _write_repo(tmp_path)
    monkeypatch.setattr("acco.pack._changed_files", lambda _root: {"src/billing.py"})
    ranked = rank_files(root, "invoice customer", changed_boost=True)
    billing = next(item for item in ranked if item.rel == "src/billing.py")
    assert billing.changed is True
    assert "changed" in billing.reasons


def test_empty_query_falls_back_to_structural_priority(tmp_path):
    root = _write_repo(tmp_path)
    pack = build_context_pack(root, "", max_tokens=800, changed_boost=False)
    assert pack.selected_files
    assert pack.estimated_tokens <= 800


def test_pack_cli_outputs_pack_and_explanation(tmp_path, capsys):
    root = _write_repo(tmp_path)
    assert pack_main([
        str(root), "--query", "refresh session", "--max-tokens", "700", "--explain"
    ]) == 0
    captured = capsys.readouterr()
    assert "ACCO CONTEXT PACK" in captured.out
    assert "src/auth.py" in captured.out
    assert "ACCO RELEVANCE" in captured.err


def test_pack_cli_rejects_nonpositive_budget(tmp_path, capsys):
    _write_repo(tmp_path)
    assert pack_main([str(tmp_path), "--max-tokens", "0"]) == 2
    assert "max_tokens must be positive" in capsys.readouterr().err


def test_symbol_ranking_prefers_query_relevant_caller_graph_over_dense_helper(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text(textwrap.dedent("""
        class DigestAuth:
            def build(self, request):
                return request

        def parse_challenge(challenge):
            # Dense lexical distractor: digest authentication outgoing request
            # challenge header request authentication digest outgoing request.
            authentication = challenge
            outgoing_request = authentication
            digest_header = outgoing_request
            return digest_header
    """))
    (src / "client.py").write_text(textwrap.dedent("""
        from auth import DigestAuth

        def send_digest_request(request):
            return DigestAuth().build(request)
    """))

    pack = build_context_pack(
        tmp_path,
        "digest authentication for outgoing requests",
        max_tokens=1400,
        changed_boost=False,
    )

    assert any(label.startswith("src/auth.py:DigestAuth@") for label in pack.selected_symbols)


def test_symbol_window_prefers_class_over_its_own_denser_matching_method(tmp_path):
    # Distinct from test_symbol_ranking_prefers_query_relevant_caller_graph_over_dense_helper
    # above: that test's distractor is a *top-level* function reached via
    # caller-graph evidence. This is the real-world shape that exposed the
    # bug (encode/httpx's DigestAuth): the outranking symbol is DigestAuth's
    # *own nested method* -- no caller-graph signal applies since nothing
    # calls it from another file -- so the fix has to come from within-file
    # symbol-window selection crediting a matching parent with its matching
    # children, not from cross-file ranking.
    src = tmp_path / "src"
    src.mkdir()
    # Type-annotated params (as the real httpx signatures have) are what
    # actually give the methods their extra name-term matches over the bare
    # `class DigestAuth:` signature -- a body-length argument alone doesn't
    # reproduce the real failure; this fixture is tuned to the same score
    # proportions observed against the real file (roughly 23 vs 42-43).
    (src / "auth.py").write_text(textwrap.dedent("""
        class HttpRequest:
            pass

        class HttpResponse:
            pass

        class DigestAuth:
            def __init__(self, username, password):
                self.username = username
                self.password = password

            def auth_flow(self, request: HttpRequest):
                yield request

            def parse_challenge(self, request: HttpRequest, response: HttpResponse, header: str) -> dict:
                # Dense body mirroring digest auth challenge parsing: digest realm
                # nonce opaque qop algorithm header field value scheme fields digest
                # request response header dict try except keyerror malformed raise
                scheme, _, fields = header.partition(" ")
                assert scheme.lower() == "digest"
                header_dict = {}
                for field in fields.split(","):
                    key, value = field.strip().split("=", 1)
                    header_dict[key] = value
                return {"request": request, "response": response, "digest": header_dict}
    """))

    pack = build_context_pack(
        tmp_path,
        "implement digest authentication for outgoing http requests",
        max_tokens=1400,
        changed_boost=False,
    )

    assert any(label.startswith("src/auth.py:DigestAuth@") for label in pack.selected_symbols)


def test_symbol_window_uses_tight_window_for_credited_child_in_large_container(tmp_path):
    # Regression for a real bug found on the real, live httpx-redirects
    # holdout task (not a synthetic what-if): the parent-credit label
    # mechanism assumed a boosted parent's *entire* window would render,
    # so the credited child's source would always "already be there." For
    # a genuinely large container (httpx's Client spans ~1400 lines),
    # under real cross-file budget competition the window gets clipped
    # long before reaching the credited child's line -- the label then
    # pointed at a line that was never actually rendered. A later,
    # stricter check (visible-source-only labeling) correctly caught and
    # dropped this stale label, exposing the underlying bug. Fixed by
    # rendering a tight window around the credited child instead of the
    # container's full span once the container is large enough that
    # rendering it whole risks this -- plus a couple of lines at the
    # container's own declaration, so *its* label's line survives too
    # (a second regression found while fixing the first: substituting
    # only the child's window dropped the parent's own line as well).
    src = tmp_path / "src"
    src.mkdir()
    lines = [
        "def distractor_function(request, redirects):",
        "    # follow redirects rebuild new request location for the",
        "    return redirects",
        "",
        "class BigClient:",
        "    def __init__(self):",
        "        self.state = 0",
    ]
    for n in range(250):
        lines.append(f"    def unrelated_helper_{n}(self, value):")
        lines.append(f"        # filler method number {n} to pad the class body")
        lines.append(f"        return value + {n}")
    lines.append("    def send_handling_redirects(self, request):")
    lines.append("        # follow redirects and rebuild the request for the new location")
    lines.append("        return request")
    (src / "client.py").write_text("\n".join(lines))

    pack = build_context_pack(
        tmp_path,
        "follow redirects and rebuild the request for the new location",
        max_tokens=1200,
        changed_boost=False,
    )

    assert any(label.startswith("src/client.py:BigClient@") for label in pack.selected_symbols)
    assert any(
        label.startswith("src/client.py:send_handling_redirects@")
        for label in pack.selected_symbols
    )


def test_symbol_window_credits_shared_method_name_when_two_classes_both_win_slots(tmp_path):
    # Regression for a real bug the parent-credit fix above introduced,
    # found by re-running the frozen external holdout after landing it
    # (encode/httpx's Client/AsyncClient both contain their own
    # send_handling_redirects and both independently out-score it for the
    # file's two window slots, pushing that name out of selected_symbols
    # even though the rendered windows still contain its source). Fixed by
    # also crediting the child whose score earned a parent its slot, since
    # the parent's window already contains that child's code.
    src = tmp_path / "src"
    src.mkdir()
    (src / "client.py").write_text(textwrap.dedent("""
        class HttpRequest:
            pass

        class HttpResponse:
            pass

        class SyncClient:
            def __init__(self, base_url: str):
                self.base_url = base_url

            def send_handling_redirects(self, request: HttpRequest, history: list) -> HttpResponse:
                # Follow HTTP redirects: rebuild the outgoing request for the new
                # location found in the response, tracking redirect history.
                response = self._send_single_request(request)
                while response.is_redirect:
                    location = response.headers["location"]
                    request = self._build_redirect_request(request, location)
                    history.append(response)
                    response = self._send_single_request(request)
                return response

            def _send_single_request(self, request: HttpRequest) -> HttpResponse:
                return HttpResponse()

            def _build_redirect_request(self, request: HttpRequest, location: str) -> HttpRequest:
                return HttpRequest()


        class AsyncClient:
            def __init__(self, base_url: str):
                self.base_url = base_url

            async def send_handling_redirects(self, request: HttpRequest, history: list) -> HttpResponse:
                # Follow HTTP redirects: rebuild the outgoing request for the new
                # location found in the response, tracking redirect history.
                response = await self._send_single_request(request)
                while response.is_redirect:
                    location = response.headers["location"]
                    request = self._build_redirect_request(request, location)
                    history.append(response)
                    response = await self._send_single_request(request)
                return response

            async def _send_single_request(self, request: HttpRequest) -> HttpResponse:
                return HttpResponse()

            def _build_redirect_request(self, request: HttpRequest, location: str) -> HttpRequest:
                return HttpRequest()
    """))

    pack = build_context_pack(
        tmp_path,
        "follow HTTP redirects and rebuild the request for the new location",
        max_tokens=1400,
        changed_boost=False,
    )

    assert any(label.startswith("src/client.py:send_handling_redirects@") for label in pack.selected_symbols)


def test_symbol_window_boosts_prototype_constructor_over_its_own_methods(tmp_path):
    # Generalizes the parent-credit boost above from Python's kind=="class"
    # (ast.ClassDef) to any symbol with recorded children, so a pre-ES6
    # constructor-function/prototype-method "class" -- the shape
    # expressjs/express's entire response.js/request.js is written in --
    # gets the same fair treatment a real class does. Found as a
    # regression while fixing the assignment-expression extraction gap
    # (see test_member_assignment_function_is_indexed_with_prototype_owner_as_parent
    # in test_v1.py): once View.prototype.lookup/render became visible to
    # extraction at all, they immediately began outscoring and displacing
    # View itself, the same failure shape DigestAuth hit, just newly
    # exposed for JS/TS's prototype pattern rather than fixed for it.
    src = tmp_path / "src"
    src.mkdir()
    (src / "view.js").write_text(textwrap.dedent("""
        function View(name, options) {
            this.name = name;
            this.root = options.root;
        }

        View.prototype.lookup = function lookup(name) {
            // Look up a view template file by name and resolve the file path.
            return this.root + '/' + name;
        }

        View.prototype.render = function render(options, callback) {
            // Render a view template using the configured template engine and
            // resolve the view lookup path before invoking the engine.
            var engine = this.engine;
            engine.render(this.path, options, callback);
        }
    """), encoding="utf-8")

    pack = build_context_pack(
        tmp_path,
        "how does the view resolve a template lookup path and render it",
        max_tokens=1400,
        changed_boost=False,
    )

    assert any(label.startswith("src/view.js:View@") for label in pack.selected_symbols)


def test_symbol_window_does_not_boost_function_nested_in_another_function(tmp_path):
    # The parent-credit boost above is deliberately restricted to class
    # parents (SymbolRecord.kind == "class"): a class groups multiple
    # members that can each be independently the right, narrower answer, but
    # a function nested inside another function is just an implementation
    # detail of that one function, not a set of candidate answers. Found via
    # the frozen external holdout (colinhacks/zod): a top-level distractor
    # function whose own body already includes its nested helper's text (so
    # its own score already reflects the helper) got boosted a *second* time
    # by that same helper's score, pushing the file's actually correct,
    # unrelated top-level function out of the results entirely.
    src = tmp_path / "src"
    src.mkdir()
    (src / "errors.ts").write_text(textwrap.dedent("""
        export function distractor(value: any) {
            function convertNestedTreeFieldLevelMessages(value: any) {
                return value;
            }
            return convertNestedTreeFieldLevelMessages(value);
        }

        export function treeifyError(error: any) {
            // convert a validation error into a nested tree
            return error;
        }
    """), encoding="utf-8")

    pack = build_context_pack(
        tmp_path,
        "convert a validation error into a nested tree of field level messages",
        max_tokens=1400,
        changed_boost=False,
    )

    assert any(label.startswith("src/errors.ts:treeifyError@") for label in pack.selected_symbols)


def test_semantic_graph_boost_recovers_terse_dependency_file(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "regexes.ts").write_text(
        "export const email = /^[^@]+@[^@]+$/;\n",
        encoding="utf-8",
    )
    (src / "schemas.ts").write_text(textwrap.dedent("""
        import * as regexes from "./regexes";
        export function validateEmail(value: string) {
            return regexes.email.test(value);
        }
    """), encoding="utf-8")
    for n in range(8):
        (src / f"email_docs_{n}.ts").write_text(
            "// validate email string schema request address\n"
            f"export function describeEmail{n}() {{ return 'email validation schema'; }}\n",
            encoding="utf-8",
        )

    ranked = rank_files(
        tmp_path,
        "validate email string schema request",
        changed_boost=False,
        seed_limit=6,
    )

    assert "src/regexes.ts" in {item.rel for item in ranked[:3]}


def test_symbol_window_matches_connection_to_connect_identifier(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "exceptions.py").write_text(textwrap.dedent("""
        class ConnectionError(Exception):
            pass

        class Timeout(Exception):
            pass

        class ReadTimeout(Exception):
            pass

        class ConnectTimeout(Exception):
            pass
    """))

    pack = build_context_pack(
        tmp_path,
        "what exception is raised when a connection attempt times out",
        max_tokens=900,
        changed_boost=False,
    )

    assert any(label.startswith("src/exceptions.py:ConnectTimeout@") for label in pack.selected_symbols)


def test_symbol_window_matches_equality_to_equal_identifier(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "equal.js").write_text(textwrap.dedent("""
        function compareDeepValues(left, right) {
          return left === right;
        }

        function compareObjectProperties(left, right) {
          return Object.keys(left).length === Object.keys(right).length;
        }

        function isEqual(value, other) {
          return baseIsEqual(value, other);
        }
    """), encoding="utf-8")

    pack = build_context_pack(
        tmp_path,
        "perform a deep equality comparison between two values",
        max_tokens=900,
        changed_boost=False,
    )

    assert any(label.startswith("src/equal.js:isEqual@") for label in pack.selected_symbols)


def test_symbol_window_matches_first_to_start_identifier(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "week.ts").write_text(textwrap.dedent("""
        export function getWeek(date: Date) {
          return 1;
        }

        export function getWeekYear(date: Date) {
          return date.getFullYear();
        }

        export function startOfWeek(date: Date) {
          return date;
        }
    """), encoding="utf-8")

    pack = build_context_pack(
        tmp_path,
        "get the first day of the week for a date",
        max_tokens=900,
        changed_boost=False,
    )

    assert any(label.startswith("src/week.ts:startOfWeek@") for label in pack.selected_symbols)


def test_symbol_window_matches_completion_to_complete_identifier(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "completion.py").write_text(textwrap.dedent("""
        def completion_arguments(shell):
            return [shell]

        def render_completion_script(shell):
            return shell

        class ShellComplete:
            pass
    """))

    pack = build_context_pack(
        tmp_path,
        "where is shell tab completion implemented",
        max_tokens=900,
        changed_boost=False,
    )

    assert any(label.startswith("src/completion.py:ShellComplete@") for label in pack.selected_symbols)


def test_tight_budget_keeps_exact_symbol_source_before_large_outline(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    lines = []
    for n in range(80):
        lines.extend([
            f"def helper_{n}(value):",
            f"    return value + {n}",
            "",
        ])
    lines.extend([
        "def target_refresh_session(token):",
        "    return rotate_token(token)",
        "",
    ])
    (src / "large_service.py").write_text("\n".join(lines), encoding="utf-8")

    pack = build_context_pack(
        tmp_path,
        "refresh session rotate token",
        max_tokens=500,
        changed_boost=False,
    )

    assert "return rotate_token(token)" in pack.text
    assert any(
        label.startswith("src/large_service.py:target_refresh_session@")
        for label in pack.selected_symbols
    )


def test_tight_budget_preserves_symbol_score_order_not_source_line_order(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "timeouts.py").write_text(textwrap.dedent("""
        def timeout_helper(value):
            # Generic timeout handling.
            return value

        def unrelated_middle_1(value):
            return value

        def unrelated_middle_2(value):
            return value

        def connect_request_timeout(request):
            # Handle a connection attempt timing out for this request.
            return request
    """))

    pack = build_context_pack(
        tmp_path,
        "connection attempt timeout request",
        max_tokens=170,
        changed_boost=False,
    )

    assert "def connect_request_timeout(request):" in pack.text
    assert any(
        label.startswith("src/timeouts.py:connect_request_timeout@")
        for label in pack.selected_symbols
    )
