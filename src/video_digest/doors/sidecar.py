"""For a local file: a caption file beside it with the same name (video.vtt, video.en.srt)."""

from __future__ import annotations

from pathlib import Path

from video_digest.context import RunContext, lang_matches
from video_digest.models import NoCaptions, Refused, Transcript
from video_digest.parse import parse_caption_file

NAME = "sidecar captions"


def find(path: Path, lang: str | None) -> Path | None:
    """The video's own name exactly (talk.vtt), or its name and one tag (talk.en.vtt); never talk-2.vtt.

    Names are compared as text, not as a glob, so a name with brackets (lecture [1080p]) still matches.
    With a language asked, the tagged file in that language wins, then the untagged one.
    """
    stem = path.stem.lower()
    plain: list[Path] = []
    tagged: list[tuple[str, Path]] = []
    for p in sorted(path.parent.iterdir()):
        if not p.is_file() or p.suffix.lower() not in (".vtt", ".srt"):
            continue
        name = p.stem.lower()
        if name == stem:
            plain.append(p)
        elif name.startswith(stem + ".") and "." not in name[len(stem) + 1:]:
            tagged.append((name[len(stem) + 1:], p))
    if lang:
        hits = [p for tag, p in tagged if lang_matches(tag, lang)]
        return (hits or plain or [None])[0]
    return (plain or [p for _, p in tagged] or [None])[0]


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
