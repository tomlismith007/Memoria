"""Security and transport tests for the unified outbound client."""

import socket

import pytest

import memoria.net as net
from memoria.net import SafeRequestError, SafeResponse, safe_request


def _dns(addresses):
    def resolve(host, port, **kwargs):
        results = []
        for address in addresses:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            results.append(
                (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))
            )
        return results

    return resolve


def _response(status=200, headers=None, text="ok"):
    return SafeResponse(status, headers or {}, text)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "https://example.com:8443/",
        "http://example.com/",
        "https://user:pass@example.com/",
        "https://example.com:bad/",
    ],
)
def test_rejects_invalid_protocol_port_and_userinfo(url):
    with pytest.raises(SafeRequestError):
        safe_request(url, allow_ollama=True)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1", "fe80::1"])
def test_web_fetch_rejects_internal_ipv4_and_ipv6(address, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _dns([address]))
    with pytest.raises(SafeRequestError, match="non-public"):
        safe_request("https://internal.example/")


def test_ollama_context_is_exact_host_and_port(monkeypatch):
    seen = []
    monkeypatch.setattr(socket, "getaddrinfo", _dns(["127.0.0.1"]))
    monkeypatch.setattr(
        net,
        "_request_once",
        lambda *args, **kwargs: seen.append((args, kwargs)) or _response(text='{"ok":true}'),
    )

    assert safe_request("http://localhost:11434/api", allow_ollama=True).json() == {"ok": True}
    assert seen[0][0][1] == "localhost"
    assert seen[0][0][3] == "127.0.0.1"

    for url in ("http://localhost/", "http://127.0.0.1:11435/", "https://localhost:11434/"):
        with pytest.raises(SafeRequestError):
            safe_request(url, allow_ollama=True)

    monkeypatch.setattr(socket, "getaddrinfo", _dns(["127.0.0.1", "93.184.216.34"]))
    with pytest.raises(SafeRequestError, match="non-public"):
        safe_request("http://localhost:11434/api", allow_ollama=True)

    monkeypatch.setattr(socket, "getaddrinfo", _dns(["127.0.0.1"]))
    with pytest.raises(SafeRequestError, match="HTTP"):
        safe_request("http://localhost:11434/api")


def test_all_dns_results_must_be_public(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _dns(["93.184.216.34", "127.0.0.1"]))
    with pytest.raises(SafeRequestError, match="non-public"):
        safe_request("https://mixed.example/")


def test_redirects_are_same_origin_and_limited(monkeypatch):
    monkeypatch.setattr(net, "_resolve_and_validate", lambda *args: ("93.184.216.34", args[1]))
    responses = iter(
        [
            _response(302, {"location": "/next"}),
            _response(307, {"location": "final"}),
            _response(200, text="done"),
        ]
    )
    monkeypatch.setattr(net, "_request_once", lambda *args, **kwargs: next(responses))

    assert safe_request("https://example.com/start").text == "done"

    monkeypatch.setattr(
        net,
        "_request_once",
        lambda *args, **kwargs: _response(302, {"location": "https://other.example/"}),
    )
    with pytest.raises(SafeRequestError, match="Cross-origin"):
        safe_request("https://example.com/start")

    monkeypatch.setattr(
        net,
        "_request_once",
        lambda *args, **kwargs: _response(302, {"location": "/again"}),
    )
    with pytest.raises(SafeRequestError, match="Too many"):
        safe_request("https://example.com/start")


def test_content_length_and_streamed_body_limits(monkeypatch):
    class Response:
        def __init__(self, headers, body):
            self.headers = net.http.client.HTTPMessage()
            for key, value in headers:
                self.headers[key] = value
            self.body = body

        def read(self, size):
            return self.body[:size]

    with pytest.raises(SafeRequestError, match="size limit"):
        net._read_response(Response([("Content-Length", "11")], b"x" * 11), 10)
    with pytest.raises(SafeRequestError, match="size limit"):
        net._read_response(Response([], b"x" * 11), 10)


def test_compressed_response_is_rejected():
    class Response:
        headers = net.http.client.HTTPMessage()
        headers["Content-Encoding"] = "gzip"

        def read(self, size):
            raise AssertionError("compressed body must not be read")

    net.http.client.HTTPMessage.__setitem__(Response.headers, "Content-Encoding", "gzip")
    with pytest.raises(SafeRequestError, match="Compressed"):
        net._read_response(Response(), 10)


def test_connection_uses_pinned_ip_but_original_host_and_sni(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _dns(["93.184.216.34"]))
    captured = {}

    class FakeConnection:
        def __init__(self, host, hostname, port, timeout, context):
            captured.update(host=host, tls_hostname=hostname, port=port)
            self.host = host

        def request(self, method, path, body=None, headers=None):
            captured.update(method=method, path=path, body=body, headers=headers)

        def getresponse(self):
            class Response:
                status = 200
                headers = net.http.client.HTTPMessage()

                def getheaders(self):
                    return []

                def read(self, size):
                    return b"ok"

                def close(self):
                    pass

            return Response()

        def close(self):
            pass

    monkeypatch.setattr(net, "_PinnedHTTPSConnection", FakeConnection)
    assert safe_request("https://example.com/path?q=1", json_body={"x": 1}).text == "ok"
    assert captured["host"] == "93.184.216.34"
    assert captured["tls_hostname"] == "example.com"
    assert captured["headers"]["Host"] == "example.com"
    assert captured["path"] == "/path?q=1"
    assert captured["headers"]["Accept-Encoding"] == "identity"
