"""Opt-in local HTTP reverse proxy for provider-request optimization."""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import sys
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from .provider_transform import ProviderTransformResult, transform_provider_request

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
_MAX_REQUEST_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class ProviderProxyConfig:
    """Configure one local provider proxy instance."""

    root: Path
    upstream: str
    provider: str = "generic"
    bind: str = "127.0.0.1"
    port: int = 8765
    compress_schemas: bool = True
    compress_tool_results: bool = True
    tool_result_min_tokens: int = 800
    timeout_seconds: float = 120.0
    allow_non_loopback: bool = False

    def validate(self) -> "ProviderProxyConfig":
        """Reject unsafe binding/upstream combinations before serving."""
        if not 1 <= int(self.port) <= 65535:
            raise ValueError("proxy port must be in 1..65535")
        try:
            bind_ip = ipaddress.ip_address(self.bind)
        except ValueError as exc:
            raise ValueError("proxy bind must be an IP address") from exc
        if not bind_ip.is_loopback and not self.allow_non_loopback:
            raise ValueError(
                "provider proxy binds to loopback by default; "
                "pass allow_non_loopback only behind your own access control"
            )
        parsed = urlparse(self.upstream)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("proxy upstream must be an absolute http(s) URL")
        if parsed.username or parsed.password:
            raise ValueError("proxy upstream URL must not contain credentials")
        if parsed.scheme == "http":
            host = parsed.hostname or ""
            try:
                local = ipaddress.ip_address(host).is_loopback
            except ValueError:
                local = host in {"localhost"}
            if not local:
                raise ValueError("plain HTTP upstream is allowed only for localhost")
        if self.timeout_seconds <= 0:
            raise ValueError("proxy timeout_seconds must be positive")
        return self


@dataclass(frozen=True)
class TransformedRequest:
    """Serialized provider request plus transformation metadata."""

    body: bytes
    metadata: dict


def transform_request_bytes(
    config: ProviderProxyConfig,
    raw: bytes,
    *,
    content_type: str,
) -> TransformedRequest:
    """Transform a JSON request body or pass unsupported payloads through."""
    if len(raw) > _MAX_REQUEST_BYTES:
        return TransformedRequest(
            raw,
            {"changed": False, "reason": "request exceeds transform limit"},
        )
    if "json" not in content_type.lower():
        return TransformedRequest(
            raw,
            {"changed": False, "reason": "non-json request"},
        )
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return TransformedRequest(
            raw,
            {"changed": False, "reason": "invalid json"},
        )
    if not isinstance(body, dict):
        return TransformedRequest(
            raw,
            {"changed": False, "reason": "json body is not an object"},
        )

    result: ProviderTransformResult = transform_provider_request(
        config.root,
        config.provider,
        body,
        compress_schemas=config.compress_schemas,
        compress_tool_results=config.compress_tool_results,
        tool_result_min_tokens=config.tool_result_min_tokens,
    )
    encoded = json.dumps(
        result.body,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return TransformedRequest(encoded, result.metadata())


def _upstream_url(base: str, path: str) -> str:
    """Join a request path to the configured upstream origin."""
    normalized = base.rstrip("/") + "/"
    return urljoin(normalized, path.lstrip("/"))


def _handler_factory(
    config: ProviderProxyConfig,
    *,
    opener: Callable = urlopen,
):
    """Build a request handler bound to one immutable proxy configuration."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "TokenSaverProviderProxy/1"

        def log_message(self, format: str, *args) -> None:
            """Keep access logs terse and free of headers/request content."""
            print(
                f"token-saver proxy: {self.address_string()} "
                + format % args,
                file=sys.stderr,
            )

        def _proxy(self) -> None:
            length_header = self.headers.get("Content-Length")
            if self.command in {"POST", "PUT", "PATCH"} and length_header is None:
                self.send_error(411, "Content-Length required")
                return
            try:
                length = int(length_header or 0)
            except ValueError:
                self.send_error(400, "invalid Content-Length")
                return
            if length < 0 or length > _MAX_REQUEST_BYTES:
                self.send_error(413, "request body too large")
                return
            raw = self.rfile.read(length) if length else b""
            transformed = transform_request_bytes(
                config,
                raw,
                content_type=self.headers.get("Content-Type", ""),
            ) if raw else TransformedRequest(raw, {"changed": False})

            target = _upstream_url(config.upstream, self.path)
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in _HOP_BY_HOP
                and key.lower() not in {"host", "content-length"}
            }
            if transformed.body:
                headers["Content-Length"] = str(len(transformed.body))
            request = Request(
                target,
                data=transformed.body if raw else None,
                headers=headers,
                method=self.command,
            )
            try:
                response = opener(request, timeout=config.timeout_seconds)
            except HTTPError as exc:
                response = exc
            except OSError as exc:
                self.send_error(502, f"upstream unavailable: {exc}")
                return

            self.send_response(response.status)
            for key, value in response.headers.items():
                lowered = key.lower()
                if lowered in _HOP_BY_HOP or lowered == "content-length":
                    continue
                self.send_header(key, value)
            self.end_headers()
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
            response.close()

            meta = transformed.metadata
            if meta.get("changed"):
                print(
                    "token-saver proxy transform: "
                    f"{meta.get('original_tokens', 0)} -> "
                    f"{meta.get('output_tokens', 0)} estimated tokens; "
                    f"recoveries={len(meta.get('recovery_handles', []))}",
                    file=sys.stderr,
                )

        do_POST = _proxy
        do_PUT = _proxy
        do_PATCH = _proxy
        do_GET = _proxy
        do_DELETE = _proxy
        do_OPTIONS = _proxy

    return Handler


def run_provider_proxy(config: ProviderProxyConfig) -> None:
    """Run the local provider proxy until interrupted."""
    config = config.validate()
    server = ThreadingHTTPServer(
        (config.bind, config.port),
        _handler_factory(config),
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
