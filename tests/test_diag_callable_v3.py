import textwrap

from token_saver.pack import build_context_pack


def test_diag_shared_parent_credit(tmp_path):
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
    raise AssertionError({
        "selected_symbols": pack.selected_symbols,
        "identities": pack.selected_symbol_identities,
        "text": pack.text[:3500],
    })
