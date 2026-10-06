"""Door 1 for YouTube: youtube-transcript-api, the whole timed caption track in one answer."""

from __future__ import annotations

from typing import Any, Callable, Iterable

from video_digest.context import RunContext, lang_matches
from video_digest.models import DoorError, DoorUnavailable, Line, NoCaptions, RateLimited, Refused, Transcript
from video_digest.parse import clean_text

NAME = "youtube-transcript-api"

_BLOCKED = {"RequestBlocked", "IpBlocked", "TooManyRequests"}
_NONE = {"TranscriptsDisabled", "NoTranscriptFound", "NoTranscriptAvailable"}


def pick(tracks: Iterable[Any], lang: str | None) -> Any | None:
    """A real track, never a translation: manual first, then the automatic one, in the language asked.

    With no language asked, the automatic track's language is the spoken one (YouTube makes it from the
    audio), so a manual track in that language wins, then the automatic track itself.
    """
    tracks = list(tracks)
    manual = [t for t in tracks if not t.is_generated]
    auto = [t for t in tracks if t.is_generated]
    if lang:
        for group in (manual, auto):
            for t in group:
                if lang_matches(t.language_code, lang):
                    return t
        return None
    if auto:
        spoken = auto[0].language_code
        for t in manual:
            if lang_matches(t.language_code, spoken.split("-")[0]):
                return t
        return auto[0]
    return manual[0] if manual else None


def map_error(exc: Exception) -> DoorError:
    """The library's errors, by class name (stable across its versions), to the run's next step."""
    name = type(exc).__name__
    text = str(exc)
    if name in _BLOCKED or "429" in text or "Too Many Requests" in text:
        return RateLimited(f"YouTube refused the caption request ({name}); next door: yt-dlp subtitles")
    if name in _NONE:
        return NoCaptions(f"no caption track ({name}); next door: speech to text")
    return DoorError(f"{name}: {text.splitlines()[0][:200] if text else 'no message'}; next door: yt-dlp subtitles")


def _default_lister() -> Callable[[str], Iterable[Any]]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as e:  # pragma: no cover - a declared dependency
        raise DoorUnavailable("youtube-transcript-api is not installed (pip install youtube-transcript-api)") from e
    api = YouTubeTranscriptApi()
    return api.list


def run(ctx: RunContext, lister: Callable[[str], Iterable[Any]] | None = None) -> Transcript:
    if ctx.source.kind != "youtube":
        raise Refused("only for one YouTube video")
    lister = lister or _default_lister()
    ctx.polite()
    try:
        tracks = list(lister(ctx.source.id))
    except Exception as e:  # the library raises its own classes
        raise map_error(e) from e
    track = pick(tracks, ctx.lang)
    if track is None:
        have = ", ".join(f"{t.language_code}{' (auto)' if t.is_generated else ''}" for t in tracks) or "none"
        raise NoCaptions(f"no {ctx.lang or 'original-language'} caption track (tracks: {have}); "
                         "next door: speech to text")
    try:
        raw = track.fetch().to_raw_data()
    except Exception as e:
        raise map_error(e) from e
    lines = [Line(float(r["start"]), float(r.get("duration") or 0.0), clean_text(str(r["text"])))
             for r in raw if str(r.get("text", "")).strip()]
    lines = [ln for ln in lines if ln.text]
    if not lines:
        raise NoCaptions("the caption track was empty; next door: speech to text")
    auto_langs = [t.language_code for t in tracks if t.is_generated]
    if auto_langs:
        ctx.original_language = auto_langs[0]
    return Transcript(lines=lines, door=NAME, language=track.language_code, generated=bool(track.is_generated),
                      track=f"{track.language_code}{' (automatic)' if track.is_generated else ' (manual)'}")
