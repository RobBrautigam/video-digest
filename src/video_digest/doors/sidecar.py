"""For a local file: a caption file beside it with the same name (video.vtt, video.en.srt)."""

from __future__ import annotations

from pathlib import Path

from video_digest.context import RunContext
from video_digest.models import NoCaptions, Refused, Transcript
from video_digest.parse import parse_caption_file

NAME = "sidecar captions"


def find(path: Path, lang: str | None) -> Path | None:
    cands = sorted(p for p in path.parent.glob(f"{path.stem}*") if p.suffix.lower() in (".vtt", ".srt"))
    if lang:
        tagged = [p for p in cands if f".{lang.lower()}" in p.name.lower()]
        cands = tagged or [p for p in cands if p.stem == path.stem]
    return cands[0] if cands else None


def run(ctx: RunContext) -> Transcript:
    if ctx.source.kind != "file":
        raise Refused("only for local files")
    side = find(Path(ctx.source.ref), ctx.lang)
    if side is None:
        raise NoCaptions("no caption file beside the video; next door: speech")
    lines = parse_caption_file(side.read_text(encoding="utf-8", errors="replace"), side.suffix)
    if not lines:
        raise NoCaptions(f"{side.name} has no cues; next door: speech")
    return Transcript(lines=lines, door=NAME, language=ctx.lang, generated=None, track=side.name)
