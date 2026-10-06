"""yt-dlp, used three ways: the probe (title, length, chapters, tracks), its caption files, and media downloads."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from video_digest.context import RunContext, lang_closeness, lang_matches
from video_digest.models import Chapter, DoorError, DoorUnavailable, RateLimited

_BOT_WORDS = ("HTTP Error 429", "Too Many Requests", "Sign in to confirm", "not a bot", "rate-limit", "rate limit")


def _yt_dlp():
    try:
        import yt_dlp
    except ImportError as e:  # pragma: no cover - a declared dependency
        raise DoorUnavailable("yt-dlp is not installed (pip install yt-dlp)") from e
    return yt_dlp


class _Silent:
    """yt-dlp prints its errors to stderr even when quiet; the run reports them itself, once."""

    def debug(self, msg: str) -> None:
        pass

    info = warning = error = debug


JS_RUNTIMES = ("deno", "node", "bun")


def js_runtimes(which: Any = shutil.which) -> dict[str, dict[str, str]]:
    """Every JavaScript runtime on PATH. yt-dlp enables only deno by default, and YouTube's media now
    needs one to solve its challenge (with the yt-dlp-ejs package), or downloads answer 403."""
    found = {name: {} for name in JS_RUNTIMES if which(name)}
    return found or {"deno": {}}


def base_opts(ctx: RunContext) -> dict[str, Any]:
    """Quiet, one video, no retries against a refusal, and a pause between requests."""
    return {
        "logger": _Silent(),
        "js_runtimes": js_runtimes(),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "extractor_retries": 0,
        "retries": 1,
        "socket_timeout": 30,
        "sleep_interval_requests": max(0.0, min(ctx.pace, 5.0)),
        "sleep_interval_subtitles": max(0.0, min(ctx.pace, 5.0)),
    }


def map_error(exc: Exception, next_door: str) -> DoorError:
    text = str(exc)
    first = next((ln for ln in text.splitlines() if ln.strip()), "no message")[:240]
    if any(w.lower() in text.lower() for w in _BOT_WORDS):
        return RateLimited(f"the site refused yt-dlp ({first}); next door: {next_door}")
    if "HTTP Error 403" in text:
        return DoorError(f"the site refused the download (HTTP 403). On YouTube this usually means yt-dlp "
                         "could not solve its challenge: install deno or Node.js and the yt-dlp-ejs package "
                         f"(pip install 'yt-dlp[default]'); next door: {next_door}")
    return DoorError(f"yt-dlp: {first}; next door: {next_door}")


def probe(ctx: RunContext, ydl_factory: Any = None) -> dict[str, Any]:
    """The metadata, no download. Kept on the context so later doors reuse it."""
    factory = ydl_factory or _yt_dlp().YoutubeDL
    ctx.polite()
    try:
        with factory(base_opts(ctx)) as ydl:
            info = ydl.extract_info(ctx.source.ref, download=False)
            info = ydl.sanitize_info(info) if hasattr(ydl, "sanitize_info") else info
    except DoorError:
        raise
    except Exception as e:
        raise map_error(e, "the doors that need no metadata (the caption library, the page's own captions)") from e
    if info.get("_type") == "playlist":
        raise DoorError("this address is a playlist, not one video; pass a single video's URL")
    ctx.info = info
    if not ctx.original_language and info.get("language"):
        ctx.original_language = info["language"]
    return info


def chapters_from_info(info: dict[str, Any] | None) -> list[Chapter]:
    out: list[Chapter] = []
    for c in (info or {}).get("chapters") or []:
        try:
            out.append(Chapter(float(c.get("start_time") or 0), None if c.get("end_time") is None
                               else float(c["end_time"]), str(c.get("title") or "").strip() or "Untitled"))
        except (TypeError, ValueError):
            continue
    return sorted(out, key=lambda ch: ch.start)


def pick_audio_format(formats: list[dict[str, Any]]) -> str | None:
    """The original-language audio, never a dub: the trap is that a dubbed track is often the smallest.

    Audio-only formats rank by YouTube's language preference, then an "original" note, then the
    smallest bitrate; with no audio-only format, the smallest format that carries sound. A format whose
    codecs the site did not name (a direct file, the generic extractor) may carry sound: kept, ranked last.
    """
    def has_audio(f: dict[str, Any]) -> bool:
        return f.get("acodec") != "none"  # None: not named by the site, so maybe

    def known(f: dict[str, Any]) -> int:
        return int(f.get("acodec") is not None or f.get("vcodec") == "none")

    def is_original(f: dict[str, Any]) -> int:
        return int("original" in str(f.get("format_note") or "").lower())

    def lang_pref(f: dict[str, Any]) -> int:
        v = f.get("language_preference")
        return int(v) if isinstance(v, (int, float)) else -1

    def abr(f: dict[str, Any]) -> float:
        return float(f.get("abr") or f.get("tbr") or 1e9)

    usable = [f for f in formats if f.get("format_id") and has_audio(f)
              and "storyboard" not in str(f.get("format_note") or "").lower()
              and f.get("protocol") not in ("mhtml",)]
    audio_only = [f for f in usable if f.get("vcodec") == "none"
                  or (f.get("vcodec") is None and f.get("acodec") is not None)]
    if audio_only:
        best = max(audio_only, key=lambda f: (lang_pref(f), is_original(f), -abr(f)))
        return str(best["format_id"])
    if usable:
        best = min(usable, key=lambda f: (-known(f), -lang_pref(f), -is_original(f), f.get("height") or 1e9, abr(f)))
        return str(best["format_id"])
    return None


def pick_stills_format(formats: list[dict[str, Any]]) -> str:
    """The smallest picture at 360p or above it nearest, no sound needed."""
    video = [f for f in formats if (f.get("vcodec") or "none") != "none" and f.get("height")
             and "storyboard" not in str(f.get("format_note") or "").lower()]
    if not video:
        return "worst"
    at_or_over = [f for f in video if f["height"] >= 360]
    pool = at_or_over or video
    best = min(pool, key=lambda f: (f["height"], (f.get("acodec") or "none") != "none", f.get("tbr") or 1e9))
    return str(best["format_id"])


def download(ctx: RunContext, format_id: str, stem: str, ydl_factory: Any = None) -> Path:
    """Fetch one format into the work folder and return the file."""
    factory = ydl_factory or _yt_dlp().YoutubeDL
    opts = {**base_opts(ctx), "format": format_id, "outtmpl": str(ctx.workdir / f"{stem}.%(ext)s"),
            "overwrites": True}
    ctx.polite()
    try:
        with factory(opts) as ydl:
            ydl.download([ctx.source.ref])
    except Exception as e:
        raise map_error(e, "the next door in the order") from e
    files = sorted(p for p in ctx.workdir.glob(f"{stem}.*") if p.suffix not in (".part", ".ytdl"))
    if not files:
        raise DoorError(f"yt-dlp wrote no {stem} file")
    return files[0]


# --- caption files from the probe -----------------------------------------------------------------

_EXT_ORDER = ("json3", "vtt", "srt", "ttml", "srv3")


def _best_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_ext = {e.get("ext"): e for e in entries if e.get("url")}
    for ext in _EXT_ORDER:
        if ext in by_ext and ext in ("json3", "vtt", "srt"):
            return by_ext[ext]
    return None


def pick_caption(info: dict[str, Any], lang: str | None, original: str | None
                 ) -> tuple[str, dict[str, Any], bool] | None:
    """(language key, file entry, generated). Manual first, then automatic; never a machine translation.

    YouTube lists a machine translation into every language under automatic captions; the spoken
    track carries an "-orig" key. An automatic track counts only when it is that track or matches the
    original language.
    """
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    orig_keys = [k for k in auto if k.endswith("-orig")]
    spoken = (orig_keys[0][:-5] if orig_keys else None) or original or info.get("language")
    want = lang or spoken

    def find(tracks: dict[str, Any], match: str | None, auto_only_original: bool) -> tuple[str, dict] | None:
        items = list(tracks.items())
        if match:  # the exact tag first (en-US over en when en-US is asked); the sort keeps the site's order
            items.sort(key=lambda kv: -lang_closeness(kv[0][:-5] if kv[0].endswith("-orig") else kv[0], match))
        for key, entries in items:
            if key == "live_chat":
                continue
            base = key[:-5] if key.endswith("-orig") else key
            if match and not lang_matches(base, match):
                continue
            if auto_only_original and orig_keys and not key.endswith("-orig"):
                continue
            if auto_only_original and not orig_keys and spoken and not lang_matches(base, spoken.split("-")[0]):
                continue
            entry = _best_entry(entries or [])
            if entry:
                return key, entry
        return None

    if want:
        hit = find(manual, want, False)
        if hit:
            return hit[0], hit[1], False
    elif manual:
        hit = find(manual, None, False)
        if hit:
            return hit[0], hit[1], False
    hit = find(auto, want, True)
    if hit:
        return hit[0], hit[1], True
    return None
