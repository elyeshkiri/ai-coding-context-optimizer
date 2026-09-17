import textwrap

from token_saver.estimate import estimate_tokens
from token_saver.pack import build_context_pack, rank_files
from token_saver.pack_cli import main as pack_main


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


def test_changed_file_gets_bonus(tmp_path, monkeypatch):
    root = _write_repo(tmp_path)
    monkeypatch.setattr("token_saver.pack._changed_files", lambda _root: {"src/billing.py"})
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
    assert "TOKEN-SAVER CONTEXT PACK" in captured.out
    assert "src/auth.py" in captured.out
    assert "TOKEN-SAVER RELEVANCE" in captured.err


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
