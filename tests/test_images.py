import socket
import urllib.error
from types import SimpleNamespace

import pytest

from item_appraiser import claude

PUBLIC_IP = "93.184.215.14"


def resolve_to(*ips):
    def getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0)) for ip in ips]

    return getaddrinfo


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(claude.socket, "getaddrinfo", resolve_to(PUBLIC_IP))


class FakeOpener:
    """Stands in for urlopen: maps a method to a status code or an HTTPError code."""

    def __init__(self, **outcomes):
        self.outcomes = outcomes
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request.get_method(), dict(request.header_items())))
        outcome = self.outcomes[request.get_method()]
        if outcome >= 400:
            raise urllib.error.HTTPError(request.full_url, outcome, "", {}, None)
        return SimpleNamespace(status=outcome)


def use_opener(monkeypatch, opener):
    class Context:
        def __init__(self, request, timeout):
            self.response = opener(request, timeout)

        def __enter__(self):
            return self.response

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(claude.urllib.request, "urlopen", Context)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:5000/static/uploads/items/a.jpg",
        "http://127.0.0.1/a.jpg",
        "http://10.0.0.5/a.jpg",
        "http://192.168.1.20/a.jpg",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/a.jpg",
        "ftp://example.com/a.jpg",
        "file:///etc/passwd",
        "not a url",
    ],
)
def test_local_private_and_non_http_urls_are_not_public(url):
    assert not claude.is_public_url(url)
    assert not claude.image_is_reachable(url)


def test_a_host_with_any_private_address_is_not_public(monkeypatch):
    monkeypatch.setattr(claude.socket, "getaddrinfo", resolve_to(PUBLIC_IP, "10.0.0.1"))
    assert not claude.is_public_url("https://example.com/a.jpg")


def test_unresolvable_host_is_not_public(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(claude.socket, "getaddrinfo", fail)
    assert not claude.is_public_url("https://nope.invalid/a.jpg")


def test_public_url_passes_on_a_successful_head(monkeypatch, public_dns):
    opener = FakeOpener(HEAD=200)
    use_opener(monkeypatch, opener)
    assert claude.image_is_reachable("https://cdn.example.com/a.jpg")
    method, headers = opener.calls[0]
    assert method == "HEAD"
    assert headers["User-agent"].startswith("item-appraiser/")


@pytest.mark.parametrize("head_status", [403, 405, 501])
def test_head_refusals_fall_back_to_a_one_byte_get(monkeypatch, public_dns, head_status):
    opener = FakeOpener(HEAD=head_status, GET=206)
    use_opener(monkeypatch, opener)
    assert claude.image_is_reachable("https://cdn.example.com/a.jpg")
    assert [method for method, _ in opener.calls] == ["HEAD", "GET"]
    assert opener.calls[1][1]["Range"] == "bytes=0-0"


def test_missing_image_fails_without_a_get(monkeypatch, public_dns):
    opener = FakeOpener(HEAD=404, GET=200)
    use_opener(monkeypatch, opener)
    assert not claude.image_is_reachable("https://cdn.example.com/a.jpg")
    assert len(opener.calls) == 1


def test_fallback_get_failure_fails(monkeypatch, public_dns):
    use_opener(monkeypatch, FakeOpener(HEAD=405, GET=404))
    assert not claude.image_is_reachable("https://cdn.example.com/a.jpg")


def test_network_errors_fail(monkeypatch, public_dns):
    def boom(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(claude.urllib.request, "urlopen", boom)
    assert not claude.image_is_reachable("https://cdn.example.com/a.jpg")
