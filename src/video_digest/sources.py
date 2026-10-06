"""Detect what a source is (a YouTube video, a Vimeo or Wistia video, another site, a local file)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be",
                 "www.youtube-nocookie.com", "youtube-nocookie.com"}
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_WISTIA_ID = re.compile(r"^[a-z0-9]{10}$")


@dataclass(frozen=True)
class Source:
    kind: str  # youtube | vimeo | wistia | site | file
    ref: str  # the URL as given, or the absolute file path
    id: str  # the video id, or the file stem

    @property
    def folder_name(self) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", self.id).strip("-") or "video"
        return f"{self.kind}-{safe}"


def youtube_id(url: str) -> str | None:
    """The 11-character id of ONE YouTube video, or None (a channel, a playlist, a search)."""
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        return None
    if host == "youtu.be":
        cand = u.path.strip("/").split("/")[0]
        return cand if _YT_ID.match(cand) else None
    if u.path == "/watch":
        cand = (parse_qs(u.query).get("v") or [""])[0]
        return cand if _YT_ID.match(cand) else None
    m = re.match(r"^/(?:shorts|live|embed|v)/([A-Za-z0-9_-]{11})(?:[/?]|$)", u.path)
    return m.group(1) if m else None


def vimeo_id(url: str) -> str | None:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if not (host == "vimeo.com" or host.endswith(".vimeo.com")):
        return None
    m = re.search(r"/(?:video/)?(\d{5,})(?:[/?#]|$)", u.path + "/")
    return m.group(1) if m else None


def wistia_id(url: str) -> str | None:
    if url.startswith("wistia:"):
        cand = url.split(":", 1)[1]
        return cand if _WISTIA_ID.match(cand) else None
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if not (host.endswith("wistia.com") or host.endswith("wistia.net") or host.endswith("wi.st")):
        return None
    m = re.search(r"/(?:medias|iframe|embed/iframe|embed/medias)/([a-z0-9]{10})", u.path)
    if m:
        return m.group(1)
    q = parse_qs(u.query).get("wvideo") or parse_qs(u.query).get("wmediaid")
    return q[0] if q and _WISTIA_ID.match(q[0]) else None


def detect(ref: str) -> Source:
    """Classify a URL or a path. A path that exists is a file; anything else must be an http(s) URL."""
    if ref.startswith("wistia:"):
        wid = wistia_id(ref)
        if wid:
            return Source("wistia", ref, wid)
        raise ValueError(f"not a Wistia id: {ref!r}")
    if not re.match(r"^https?://", ref, re.I):
        p = Path(ref).expanduser()
        if p.is_file():
            return Source("file", str(p.resolve()), p.stem)
        raise ValueError(f"not a file and not an http(s) URL: {ref!r}")
    if (yid := youtube_id(ref)):
        return Source("youtube", ref, yid)
    host = (urlparse(ref).hostname or "").lower()
    if host in YOUTUBE_HOSTS:
        raise ValueError("this YouTube address is not one video (a channel, a playlist or a search); "
                         "pass a single video's URL")
    if (vid := vimeo_id(ref)):
        return Source("vimeo", ref, vid)
    if (wid := wistia_id(ref)):
        return Source("wistia", ref, wid)
    tail = urlparse(ref).path.rstrip("/").split("/")[-1] or host
    return Source("site", ref, f"{host}-{tail}"[:80])
