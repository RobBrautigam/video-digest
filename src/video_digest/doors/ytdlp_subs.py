"""Door 2: the caption file yt-dlp found (manual, then automatic), with the chapters from the same probe."""

from __future__ import annotations

from typing import Any, Callable

from video_digest import ytdlp
from video_digest.context import RunContext
from video_digest.models import DoorError, NoCaptions, Refused, Transcript
from video_digest.parse import parse_caption_file

NAME = "yt-dlp subtitles"


def _fetch_with_ytdlp(ctx: RunContext, url: str) -> bytes:
    yt_dlp = ytdlp._yt_dlp()
    try:
        with yt_dlp.YoutubeDL(ytdlp.base_opts(ctx)) as ydl:
            return ydl.urlopen(url).read()
    except Exception as e:
        raise ytdlp.map_error(e, "the page's own captions or speech") from e


def run(ctx: RunContext, fetch: Callable[[RunContext, str], bytes] | None = None) -> Transcript:
    if ctx.source.kind == "file":
        raise Refused("a local file has no site captions")
    if ctx.info is None:
        raise DoorError("no metadata (the probe failed); next door: the page's own captions or speech")
    picked = ytdlp.pick_caption(ctx.info, ctx.lang, ctx.original_language)
    if picked is None:
        manual = sorted((ctx.info.get("subtitles") or {}).keys())
        raise NoCaptions(f"no {ctx.lang or 'original-language'} caption track from yt-dlp "
                         f"(manual: {', '.join(manual) or 'none'}); next door: the page's captions or speech")
    key, entry, generated = picked
    ctx.polite()
    body = (fetch or _fetch_with_ytdlp)(ctx, entry["url"])
    try:
        lines = parse_caption_file(body.decode("utf-8", errors="replace"), entry.get("ext") or "vtt")
    except ValueError as e:
        raise DoorError(f"the {key} caption file did not parse ({e}); next door: speech") from e
    if not lines:
        raise NoCaptions(f"the {key} caption file was empty; next door: speech")
    lang = key[:-5] if key.endswith("-orig") else key
    if generated:
        ctx.original_language = ctx.original_language or lang
    return Transcript(lines=lines, door=NAME, language=lang, generated=generated,
                      track=f"{key} ({'automatic' if generated else 'manual'}, {entry.get('ext')})")


def info_summary(info: dict[str, Any] | None) -> dict[str, Any]:
    """What the run keeps from the probe in meta.json."""
    info = info or {}
    keys = ("id", "title", "uploader", "channel", "upload_date", "duration", "language", "license",
            "webpage_url", "extractor_key", "description")
    out = {k: info.get(k) for k in keys if info.get(k) is not None}
    if "description" in out and isinstance(out["description"], str):
        out["description"] = out["description"][:2000]
    out["caption_tracks"] = {
        "manual": sorted((info.get("subtitles") or {}).keys()),
        "automatic_original": sorted(k for k in (info.get("automatic_captions") or {}) if k.endswith("-orig")),
    }
    return out
