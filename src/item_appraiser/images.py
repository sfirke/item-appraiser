"""Photo URL checks shared by the LLM appraisers."""

import urllib.error
import urllib.request


def image_is_reachable(url: str) -> bool:
    """Model APIs fetch photo URLs themselves and fail the whole request on a dead one."""
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False
