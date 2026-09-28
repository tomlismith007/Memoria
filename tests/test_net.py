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
        "http://localhost/",
        "https://user:pass@example.com/",
        "https://example.com:bad/",
    ],
)
def test_rejects_non_public_protocol_port_and_userinfo(url):
    with pytest.raises(SafeRequestError):
        safe_request(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1", "fe80::1"])
def test_web_fetch_rejects_internal_ipv4_and_ipv6(address, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _dns([address]))
    with pytest.raises(SafeRequestError, match="non-public"):
        safe_request("https://internal.example/")


def test_public_gateway_validator_does_not_resolve_dns(monkeypatch):
    def unexpected_dns(*args, **kwargs):
        raise AssertionError("configuration validation must not perform DNS")

    monkeypatch.setattr(socket, "getaddrinfo", unexpected_dns)
    net.validate_public_https_url("https://gateway.example/v1")


def test_all_dns_results_must_be_public(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _dns(["93.184.216.34", "127.0.0.1"]))
    with pytest.raises(SafeRequestError, match="non-public"):
        safe_request("https://mixed.example/")


def test_redirects_are_same_origin_and_limited(monkeypatch):
    monkeypatch.setattr(net, "_resolve", lambda *args: ("93.184.216.34", args[1]))
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


def test_compressed_responses_decompressed_safely():
    import gzip
    import zlib

    class FakeResponse:
        def __init__(self, encoding, body):
            self.headers = net.http.client.HTTPMessage()
            self.headers["Content-Encoding"] = encoding
            self.body = body
            self.status = 200

        def getheaders(self):
            return [("Content-Encoding", self.headers["Content-Encoding"])]

        def read(self, size):
            return self.body[:size]

    gz_data = gzip.compress(b"hello gzip response")
    res = net._read_response(FakeResponse("gzip", gz_data), 1024)
    assert res.text == "hello gzip response"

    df_data = zlib.compress(b"hello deflate response")
    res = net._read_response(FakeResponse("deflate", df_data), 1024)
    assert res.text == "hello deflate response"

    # Zip bomb protection: decompressed size exceeds max_bytes
    bomb = gzip.compress(b"x" * 200)
    with pytest.raises(SafeRequestError, match="size limit"):
        net._read_response(FakeResponse("gzip", bomb), 50)

    # Unsupported encoding
    with pytest.raises(SafeRequestError, match="Unsupported content encoding"):
        net._read_response(FakeResponse("br", b"brotli data"), 1024)


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
    assert captured["headers"]["Accept-Encoding"] == "gzip, deflate, identity"
