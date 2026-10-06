"""Door 3 for Vimeo and Wistia: the caption file the player itself loads, read without yt-dlp."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

from video_digest.context import RunContext, lang_matches
from video_digest.models import DoorError, NoCaptions, Refused, Transcript
from video_digest.parse import parse_vtt

NAME = "page captions"

WISTIA_MEDIA = "https://fast.wistia.com/embed/medias/{id}.json"
WISTIA_CAPTIONS = "https://fast.wistia.com/embed/captions/{id}.vtt?language={lang}"
VIMEO_CONFIG = "https://player.vimeo.com/video/{id}/config"


def _pick(tracks: list[dict[str, Any]], lang: str | None, lang_key: str) -> dict[str, Any] | None:
    if not tracks:
        return None
    if lang:
        for t in tracks:
            code = str(t.get(lang_key) or "")
            # Wistia uses three-letter codes (eng); Vimeo two-letter (en, en-US)
            if lang_matches(code, lang) or (len(code) == 3 and code[:2] == lang[:2].lower()):
                return t
        return None
    return tracks[0]


def _json(ctx: RunContext, url: str) -> dict[str, Any]:
    ctx.polite()
    body = ctx.fetch(url, {"Referer": ctx.source.ref if ctx.source.ref.startswith("http") else "https://example.com/"})
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise DoorError(f"the player answered something that is not JSON ({url}); next door: speech") from e


def wistia(ctx: RunContext) -> Transcript:
    media = _json(ctx, WISTIA_MEDIA.format(id=ctx.source.id)).get("media") or {}
    tracks = [c for c in media.get("captions") or [] if c.get("language")]
    track = _pick(tracks, ctx.lang, "language")
    if track is None:
        raise NoCaptions(f"the Wistia player lists no {ctx.lang or ''} captions "
                         f"(has: {', '.join(c['language'] for c in tracks) or 'none'}); next door: speech")
    ctx.polite()
    vtt = ctx.fetch(WISTIA_CAPTIONS.format(id=ctx.source.id, lang=track["language"])).decode("utf-8", "replace")
    lines = parse_vtt(vtt)
    if not lines:
        raise NoCaptions("the Wistia caption file was empty; next door: speech")
    return Transcript(lines=lines, door=NAME, language=track["language"], generated=None,
                      track=f"wistia captions {track['language']}")


def vimeo(ctx: RunContext) -> Transcript:
    config = _json(ctx, VIMEO_CONFIG.format(id=ctx.source.id))
    tracks = [t for t in (config.get("request") or {}).get("text_tracks") or [] if t.get("url")]
    track = _pick(tracks, ctx.lang, "lang")
    if track is None:
        raise NoCaptions(f"the Vimeo player lists no {ctx.lang or ''} text tracks "
                         f"(has: {', '.join(str(t.get('lang')) for t in tracks) or 'none'}); next door: speech")
    ctx.polite()
    vtt = ctx.fetch(urljoin("https://vimeo.com", track["url"])).decode("utf-8", "replace")
    lines = parse_vtt(vtt)
    if not lines:
        raise NoCaptions("the Vimeo text track was empty; next door: speech")
    generated = "auto" in str(track.get("kind") or "").lower() or "auto" in str(track.get("label") or "").lower()
    return Transcript(lines=lines, door=NAME, language=str(track.get("lang")), generated=generated,
                      track=f"vimeo text track {track.get('lang')} ({track.get('kind') or 'captions'})")


def run(ctx: RunContext) -> Transcript:
    if ctx.source.kind == "wistia":
        return wistia(ctx)
    if ctx.source.kind == "vimeo":
        return vimeo(ctx)
    raise Refused("only for Vimeo and Wistia")
