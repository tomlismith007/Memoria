"""Policy-enforcing outbound HTTPS for user-configured public gateways."""

from __future__ import annotations

import http.client
import ipaddress
import json as jsonlib
import socket
import ssl
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urljoin, urlsplit, urlunsplit

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 3
_PUBLIC_SCHEME = "https"
_PUBLIC_PORT = 443


class SafeRequestError(ValueError):
    """The request violates the outbound network policy or response limits."""


@dataclass(frozen=True)
class SafeResponse:
    status: int
    headers: dict[str, str]
    text: str

    def json(self) -> Any:
        return jsonlib.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise SafeRequestError(f"HTTP {self.status}")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a validated IP while retaining hostname TLS identity."""

    def __init__(
        self,
        pinned_ip: str,
        hostname: str,
        port: int,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(pinned_ip, port=port, timeout=timeout, context=context)
        self._tls_hostname = hostname

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self.host, self.port), self.timeout, self.source_address
        )
        if self._tunnel_host:
            self._tunnel()
        self.sock = self._context.wrap_socket(
            self.sock, server_hostname=self._tls_hostname
        )


def _validate_url(url: str) -> tuple[str, int, str]:
    """Validate URL syntax and the public HTTPS/443 policy without DNS."""
    if not isinstance(url, str) or not url or any(ch.isspace() or ord(ch) < 32 for ch in url):
        raise SafeRequestError("Invalid URL")
    if "\\" in url:
        raise SafeRequestError("Invalid URL")

    try:
        parsed = urlsplit(url)
        port = parsed.port
        hostname = parsed.hostname
    except ValueError as exc:
        raise SafeRequestError("Invalid URL or port") from exc

    if parsed.scheme != _PUBLIC_SCHEME or not hostname:
        raise SafeRequestError("Only public HTTPS URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise SafeRequestError("URL userinfo is not allowed")
    if parsed.netloc.endswith(":"):
        raise SafeRequestError("Invalid URL port")
    if any(ch.isspace() or ord(ch) < 32 for ch in hostname):
        raise SafeRequestError("Invalid hostname")

    if port is None:
        port = _PUBLIC_PORT
    if port != _PUBLIC_PORT:
        raise SafeRequestError("Public HTTPS requests must use port 443")

    normalized_host = hostname.casefold().rstrip(".")
    if normalized_host == "localhost" or normalized_host.endswith(
        (".localhost", ".local", ".internal", ".lan", ".home")
    ):
        raise SafeRequestError("Local gateway hosts are not allowed")
    try:
        address = ipaddress.ip_address(hostname.split("%", 1)[0])
    except ValueError:
        pass
    else:
        if not _ip(address.compressed):
            raise SafeRequestError("Public gateway IP is required")
    return parsed.scheme, port, hostname


def _ip(raw_ip: str) -> bool:
    """Return whether an address is globally routable and not special-purpose."""
    try:
        address = ipaddress.ip_address(raw_ip.split("%", 1)[0])
    except ValueError as exc:
        raise SafeRequestError("DNS returned an invalid address") from exc
    return (
        address.is_global
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
        and not address.is_link_local
    )


def _resolve(hostname: str, port: int) -> tuple[str, int]:
    """Resolve every address, reject mixed/private DNS, and pin one address."""
    try:
        results = socket.getaddrinfo(
            hostname, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except OSError as exc:
        raise SafeRequestError("DNS resolution failed") from exc
    if not results:
        raise SafeRequestError("DNS resolution returned no addresses")

    addresses: list[tuple[int, str]] = []
    for family, socktype, proto, _canonname, sockaddr in results:
        if not sockaddr or not isinstance(sockaddr[0], str):
            raise SafeRequestError("Unsupported DNS result")
        if family not in {socket.AF_INET, socket.AF_INET6}:
            raise SafeRequestError("Unsupported DNS result")
        if socktype != socket.SOCK_STREAM or proto != socket.IPPROTO_TCP:
            raise SafeRequestError("Unsupported DNS result")
        address = sockaddr[0]
        if not _ip(address):
            raise SafeRequestError("DNS resolved to a non-public address")
        if (family, address) not in addresses:
            addresses.append((family, address))
    return addresses[0][1], port


def _host_header(hostname: str, port: int) -> str:
    try:
        hostname.encode("ascii")
        display = hostname
    except UnicodeEncodeError:
        display = hostname.encode("idna").decode("ascii")
    if ":" in display:
        display = f"[{display}]"
    return display if port == _PUBLIC_PORT else f"{display}:{port}"


def _validate_content_length(headers: http.client.HTTPMessage, max_bytes: int) -> None:
    values = headers.get_all("Content-Length", []) or []
    for value in values:
        try:
            length = int(value)
        except ValueError as exc:
            raise SafeRequestError("Invalid Content-Length") from exc
        if length < 0 or length > max_bytes:
            raise SafeRequestError("Response exceeds size limit")


def _validate_transfer_encoding(headers: http.client.HTTPMessage) -> None:
    encodings = headers.get_all("Transfer-Encoding", []) or []
    if any(encoding.strip().lower() not in {"", "chunked"} for encoding in encodings):
        raise SafeRequestError("Unsupported transfer encoding")


def _read_response(
    response: http.client.HTTPResponse, max_bytes: int
) -> SafeResponse:
    _validate_transfer_encoding(response.headers)
    encodings = response.headers.get_all("Content-Encoding", []) or []
    if any(encoding.strip().lower() not in {"", "identity"} for encoding in encodings):
        raise SafeRequestError("Compressed responses are not allowed")
    _validate_content_length(response.headers, max_bytes)

    body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise SafeRequestError("Response exceeds size limit")

    headers = {key.lower(): value for key, value in response.getheaders()}
    content_type = headers.get("content-type", "")
    charset = "utf-8"
    if "charset=" in content_type:
        candidate = content_type.split("charset=", 1)[1].split(";", 1)[0].strip().strip('"\'')
        if candidate:
            charset = candidate
    try:
        text = body.decode(charset, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    return SafeResponse(response.status, headers, text)


def _request_once(
    scheme: str,
    hostname: str,
    port: int,
    pinned_ip: str,
    path: str,
    method: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
    max_bytes: int,
) -> SafeResponse:
    if scheme != _PUBLIC_SCHEME or port != _PUBLIC_PORT:
        raise SafeRequestError("Only public HTTPS/443 requests are allowed")
    connection = _PinnedHTTPSConnection(
        pinned_ip,
        hostname,
        port,
        timeout,
        ssl.create_default_context(),
    )
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        try:
            return _read_response(response, max_bytes)
        finally:
            response.close()
    finally:
        connection.close()


def validate_public_https_url(url: str) -> None:
    """Validate a configured gateway URL without performing DNS resolution."""
    _validate_url(url)


def safe_request(
    url: str,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    json_body: Any = None,
    timeout: float = 10.0,
    max_bytes: int = 4 * 1024 * 1024,
) -> SafeResponse:
    """Perform a GET/POST against a public HTTPS gateway after DNS pinning."""
    method = method.upper()
    if method not in {"GET", "POST"}:
        raise SafeRequestError("Only GET and POST are supported")
    if timeout <= 0 or max_bytes <= 0:
        raise SafeRequestError("Timeout and max_bytes must be positive")

    body = None
    if json_body is not None:
        body = jsonlib.dumps(
            json_body, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    current_url = url
    current_method = method
    current_body = body
    current_headers = {
        str(key): str(value)
        for key, value in (headers or {}).items()
        if str(key).lower() not in {"host", "accept-encoding"}
    }
    current_headers["Accept-Encoding"] = "identity"
    if body is not None:
        current_headers.setdefault("Content-Type", "application/json")

    for redirect_count in range(MAX_REDIRECTS + 1):
        scheme, port, hostname = _validate_url(current_url)
        pinned_ip, _ = _resolve(hostname, port)
        parsed = urlsplit(current_url)
        path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        request_headers = dict(current_headers)
        request_headers["Host"] = _host_header(hostname, port)
        result = _request_once(
            scheme,
            hostname,
            port,
            pinned_ip,
            path,
            current_method,
            request_headers,
            current_body,
            timeout,
            max_bytes,
        )

        if result.status not in REDIRECT_STATUSES:
            return result
        location = result.headers.get("location")
        if not location or redirect_count >= MAX_REDIRECTS:
            if location and redirect_count >= MAX_REDIRECTS:
                raise SafeRequestError("Too many redirects")
            return result

        next_url = urljoin(current_url, location)
        next_scheme, next_port, next_hostname = _validate_url(next_url)
        if (next_scheme, next_port, next_hostname.casefold()) != (
            scheme,
            port,
            hostname.casefold(),
        ):
            raise SafeRequestError("Cross-origin redirects are not allowed")

        if result.status == 303 or (
            result.status in {301, 302} and current_method == "POST"
        ):
            current_method = "GET"
            current_body = None
            current_headers.pop("Content-Type", None)
        current_url = next_url

    raise SafeRequestError("Too many redirects")
