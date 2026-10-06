"""What every door can read: the source, the language asked, the probe's metadata, and the network."""

from __future__ import annotations

import http.client
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from video_digest import __version__
from video_digest.models import DoorError, RateLimited
from video_digest.sources import Source

USER_AGENT = f"video-digest/{__version__} (+https://github.com/RobBrautigam/video-digest)"


def http_get(url: str, headers: Mapping[str, str] | None = None, timeout: float = 30.0) -> bytes:
    """A plain GET. A 429 is raised as RateLimited; other HTTP errors as DoorError with the code."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (http(s) only, checked by callers)
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimited(f"{urlparse(url).hostname} answered 429 (too many requests)") from e
        raise DoorError(f"HTTP {e.code} from {urlparse(url).hostname}") from e
    except urllib.error.URLError as e:
        raise DoorError(f"network error: {e.reason}") from e
    except (OSError, http.client.HTTPException) as e:  # a read timeout or a cut connection mid-body
        raise DoorError(f"network error: {type(e).__name__} from {urlparse(url).hostname}") from e


def _tag(code: str) -> str:
    return code.lower().replace("_", "-")


def lang_matches(code: str | None, want: str) -> bool:
    """'en-US' matches 'en' and 'en' matches 'en-US'; 'eng' does not (a prefix must end at a subtag)."""
    if not code:
        return False
    code, want = _tag(code), _tag(want)
    return code == want or code.startswith(want + "-") or want.startswith(code + "-")


def lang_closeness(code: str | None, want: str) -> int:
    """2 for the same tag, 1 for a match at a subtag, 0 for none: en-US wins over en when en-US is asked."""
    if not code or not lang_matches(code, want):
        return 0
    return 2 if _tag(code) == _tag(want) else 1


@dataclass
class RunContext:
    source: Source
    workdir: Path
    lang: str | None = None  # None: the video's original (spoken) language
    info: dict[str, Any] | None = None  # yt-dlp's metadata for a URL, ffprobe's for a file
    pace: float = 2.0  # seconds between two requests to the same site
    allow_paid: bool = False
    env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    fetch: Callable[..., bytes] = http_get
    sleep: Callable[[float], None] = time.sleep
    log: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr)
    original_language: str | None = None  # learned from a caption track or the probe
    _last_request: float = 0.0

    def polite(self) -> None:
        """Wait out the pacing gap since the last request this run made to the site."""
        gap = time.monotonic() - self._last_request
        if self._last_request and gap < self.pace:
            self.sleep(self.pace - gap)
        self._last_request = time.monotonic()
