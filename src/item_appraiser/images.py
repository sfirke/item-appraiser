"""Photo URL checks shared by the LLM appraisers.

Model APIs fetch photo URLs themselves, from the provider's servers, and fail the
whole request on one they can't load. So each photo is checked first and left
out of the request if it won't work.
"""

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request

from item_appraiser._version import __version__

IMAGE_CHECK_TIMEOUT_SECONDS = 10
USER_AGENT = f"item-appraiser/{__version__} (+https://github.com/sfirke/item-appraiser)"


def is_public_url(url: str) -> bool:
    """Whether `url` is http(s) on a host that resolves only to public addresses.

    The provider fetches photos from its own servers, so a localhost or
    private-network URL (a dev server, an internal bucket) can never work and would
    fail the request.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or None)
    except (OSError, UnicodeError, ValueError):
        return False
    return bool(addresses) and all(
        ipaddress.ip_address(address[4][0].split("%")[0]).is_global for address in addresses
    )


def _fetch_ok(url: str, method: str) -> bool:
    headers = {"User-Agent": USER_AGENT}
    if method == "GET":
        headers["Range"] = "bytes=0-0"  # just enough to confirm the file is there
    request = urllib.request.Request(url, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=IMAGE_CHECK_TIMEOUT_SECONDS) as response:
        return 200 <= response.status < 300


def image_is_reachable(url: str) -> bool:
    """Whether the provider will be able to load the photo at `url`.

    Checks that the URL is public, then sends a HEAD request, falling back to a
    one-byte GET for servers that don't allow HEAD.
    """
    if not is_public_url(url):
        return False
    try:
        return _fetch_ok(url, "HEAD")
    except urllib.error.HTTPError as e:
        if e.code not in (403, 405, 501):  # some servers and signed URLs refuse only HEAD
            return False
    except (OSError, ValueError):
        return False
    try:
        return _fetch_ok(url, "GET")
    except (OSError, ValueError):
        return False
