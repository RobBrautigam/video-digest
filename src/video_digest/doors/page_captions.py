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


def _is(code: str, lang: str) -> bool:
    # Wistia uses three-letter codes (eng); Vimeo two-letter (en, en-US)
    return lang_matches(code, lang) or (len(code) == 3 and code[:2] == lang[:2].lower())


def _pick(tracks: list[dict[str, Any]], lang: str | None, lang_key: str, original: str | None = None
          ) -> dict[str, Any] | None:
    """The language asked; with none asked, the spoken language when known, else a best guess.

    A player's list does not say which track is the spoken one, and its "default" flag can point at a
    translation (Vimeo's own player video defaults to German). So with no language asked: a track
    of kind "captions" (same-language by convention), then the known spoken language, then English,
    then the default, then the first. The run records that the language was a guess.
    """
    if not tracks:
        return None
    if lang:
        return next((t for t in tracks if _is(str(t.get(lang_key) or ""), lang)), None)
    rules = [
        lambda t: str(t.get("kind") or "").lower() == "captions",
        lambda t: bool(original) and _is(str(t.get(lang_key) or ""), str(original)),
        lambda t: _is(str(t.get(lang_key) or ""), "en"),
        lambda t: bool(t.get("default")),
    ]
    for rule in rules:
        hit = next((t for t in tracks if rule(t)), None)
        if hit:
            return hit
    return tracks[0]


def _json(ctx: RunContext, url: str) -> dict[str, Any]:
    ctx.polite()
    body = ctx.fetch(url, {"Referer": ctx.source.ref if ctx.source.ref.startswith("http") else "https://example.com/"})
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise DoorError(f"the player answered something that is not JSON ({url}); next door: speech") from e


def _notes(ctx: RunContext, tracks: list[dict[str, Any]], key: str, page_meta: dict[str, Any]) -> dict[str, Any]:
    notes: dict[str, Any] = {"page_meta": {k: v for k, v in page_meta.items() if v is not None},
                             "tracks": [str(t.get(key)) for t in tracks]}
    if not ctx.lang and not ctx.original_language and len(tracks) > 1:
        notes["language_guessed"] = True
    return notes


def wistia(ctx: RunContext) -> Transcript:
    media = _json(ctx, WISTIA_MEDIA.format(id=ctx.source.id)).get("media") or {}
    tracks = [c for c in media.get("captions") or [] if c.get("language")]
    track = _pick(tracks, ctx.lang, "language", ctx.original_language)
    if track is None:
        raise NoCaptions(f"the Wistia player lists no {ctx.lang or ''} captions "
                         f"(has: {', '.join(c['language'] for c in tracks) or 'none'}); next door: speech")
    ctx.polite()
    vtt = ctx.fetch(WISTIA_CAPTIONS.format(id=ctx.source.id, lang=track["language"])).decode("utf-8", "replace")
    lines = parse_vtt(vtt)
    if not lines:
        raise NoCaptions("the Wistia caption file was empty; next door: speech")
    meta = {"title": media.get("name"), "duration": media.get("duration")}
    return Transcript(lines=lines, door=NAME, language=track["language"], generated=None,
                      track=f"wistia captions {track['language']}", notes=_notes(ctx, tracks, "language", meta))


def vimeo(ctx: RunContext) -> Transcript:
    config = _json(ctx, VIMEO_CONFIG.format(id=ctx.source.id))
    tracks = [t for t in (config.get("request") or {}).get("text_tracks") or [] if t.get("url")]
    track = _pick(tracks, ctx.lang, "lang", ctx.original_language)
    if track is None:
        raise NoCaptions(f"the Vimeo player lists no {ctx.lang or ''} text tracks "
                         f"(has: {', '.join(str(t.get('lang')) for t in tracks) or 'none'}); next door: speech")
    ctx.polite()
    vtt = ctx.fetch(urljoin("https://vimeo.com", track["url"])).decode("utf-8", "replace")
    lines = parse_vtt(vtt)
    if not lines:
        raise NoCaptions("the Vimeo text track was empty; next door: speech")
    generated = "auto" in str(track.get("kind") or "").lower() or "auto" in str(track.get("label") or "").lower()
    video = config.get("video") or {}
    meta = {"title": video.get("title"), "duration": video.get("duration"),
            "uploader": (video.get("owner") or {}).get("name")}
    return Transcript(lines=lines, door=NAME, language=str(track.get("lang")), generated=generated,
                      track=f"vimeo text track {track.get('lang')} ({track.get('kind') or 'captions'})",
                      notes=_notes(ctx, tracks, "lang", meta))


def run(ctx: RunContext) -> Transcript:
    if ctx.source.kind == "wistia":
        return wistia(ctx)
    if ctx.source.kind == "vimeo":
        return vimeo(ctx)
    raise Refused("only for Vimeo and Wistia")
