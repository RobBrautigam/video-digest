"""The run: detect the source, take the doors in order (free first), write the folder."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from video_digest import __version__, local, stills, ytdlp
from video_digest.context import RunContext
from video_digest.doors import page_captions, paid, sidecar, speech, youtube_api, ytdlp_subs
from video_digest.models import Chapter, DoorError, NoCaptions, RateLimited, Refused, Transcript
from video_digest.output import write_all, write_json
from video_digest.sources import Source, detect

DOORS: dict[str, Callable[[RunContext], Transcript]] = {
    "youtube-api": youtube_api.run,
    "ytdlp-subs": ytdlp_subs.run,
    "page": page_captions.run,
    "sidecar": sidecar.run,
    "speech": speech.run,
    "paid": paid.run,
}
CAPTION_DOORS = {"youtube-api", "ytdlp-subs", "page", "sidecar"}
NEEDS_PROBE = {"ytdlp-subs", "speech"}

# Free first. The paid door is last and runs only when the user turned it on.
ORDER: dict[str, list[str]] = {
    "youtube": ["youtube-api", "ytdlp-subs", "speech", "paid"],
    "vimeo": ["ytdlp-subs", "page", "speech", "paid"],
    "wistia": ["ytdlp-subs", "page", "speech", "paid"],
    "site": ["ytdlp-subs", "speech", "paid"],
    "file": ["sidecar", "speech"],
}


class AllDoorsFailed(RuntimeError):
    def __init__(self, attempts: list[dict[str, Any]]):
        self.attempts = attempts
        lines = [f"  - {a['door']}: {a['error']}" for a in attempts if not a["ok"]]
        hints = []
        if any(a["kind"] == "DoorUnavailable" and "faster-whisper" in a["error"] for a in attempts):
            hints.append("install the speech door: pip install 'video-digest[speech]'")
        if any(a["kind"] == "RateLimited" for a in attempts):
            hints.append("the site is limiting requests from this address: wait, or run from another network")
        msg = "no door returned a transcript:\n" + "\n".join(lines)
        if hints:
            msg += "\nnext: " + "; ".join(hints)
        super().__init__(msg)


@dataclass
class Options:
    out: Path = Path("digests")
    lang: str | None = None
    doors: list[str] | None = None
    stills: str = "auto"  # auto | always | never
    max_stills: int = 40
    pace: float = 2.0
    allow_paid: bool = False
    keep_media: bool = False
    env: dict[str, str] | None = None
    log: Callable[[str], None] | None = None


def door_order(source: Source, chosen: list[str] | None) -> list[str]:
    order = ORDER[source.kind]
    if not chosen:
        return list(order)
    unknown = [d for d in chosen if d not in DOORS]
    if unknown:
        raise ValueError(f"unknown door(s): {', '.join(unknown)} (doors: {', '.join(DOORS)})")
    return [d for d in chosen if d in order]


def _probe(ctx: RunContext) -> dict[str, Any] | None:
    if ctx.source.kind == "file":
        ctx.info = local.probe(Path(ctx.source.ref))
        return ctx.info
    return ytdlp.probe(ctx)


def _probe_attempt(ctx: RunContext, probe: Callable[[RunContext], Any]) -> dict[str, Any]:
    """Read the metadata once; a failure is recorded and the doors that do not need it go on."""
    t0 = time.monotonic()
    try:
        probe(ctx)
    except DoorError as e:
        ctx.log(f"metadata: {e}")
        return {"door": "probe", "ok": False, "kind": type(e).__name__, "error": str(e),
                "seconds": round(time.monotonic() - t0, 2)}
    return {"door": "probe", "ok": True, "kind": "ok", "error": "", "seconds": round(time.monotonic() - t0, 2)}


def take_doors(ctx: RunContext, order: list[str], doors: dict[str, Callable[[RunContext], Transcript]] | None = None,
               probe: Callable[[RunContext], Any] | None = None) -> tuple[Transcript | None, list[dict[str, Any]]]:
    doors = doors or DOORS
    probe = probe or _probe
    attempts: list[dict[str, Any]] = []
    probed = False
    skip_captions = False
    for i, name in enumerate(order):
        nxt = order[i + 1] if i + 1 < len(order) else "none (all doors tried)"
        if name in CAPTION_DOORS and skip_captions:
            attempts.append({"door": name, "ok": False, "kind": "Skipped",
                             "error": "skipped: the site said this video has no caption track", "seconds": 0.0})
            continue
        if name in NEEDS_PROBE and not probed:
            probed = True
            attempts.append(_probe_attempt(ctx, probe))
        t0 = time.monotonic()
        try:
            result = doors[name](ctx)
        except DoorError as e:
            took = round(time.monotonic() - t0, 2)
            attempts.append({"door": name, "ok": False, "kind": type(e).__name__, "error": str(e), "seconds": took})
            if isinstance(e, RateLimited):
                ctx.log(f"{name}: rate limited ({e}); next door: {nxt}")
            elif not isinstance(e, Refused):
                ctx.log(f"{name}: {e}")
            if isinstance(e, NoCaptions) and ctx.source.kind == "youtube" and name == "youtube-api":
                skip_captions = True
            continue
        took = round(time.monotonic() - t0, 2)
        attempts.append({"door": name, "ok": True, "kind": "ok", "error": "", "seconds": took,
                         "words": result.words})
        ctx.log(f"{name}: {result.words:,} words in {took:.1f} s")
        return result, attempts
    return None, attempts


def run(ref: str, opts: Options) -> Path:
    t_start = time.monotonic()
    source = detect(ref)
    folder = Path(opts.out) / source.folder_name
    work = folder / "media"
    work.mkdir(parents=True, exist_ok=True)
    ctx = RunContext(source=source, workdir=work, lang=opts.lang, pace=opts.pace, allow_paid=opts.allow_paid)
    if opts.env is not None:
        ctx.env = opts.env
    if opts.log is not None:
        ctx.log = opts.log
    order = door_order(source, opts.doors)
    transcript, attempts = take_doors(ctx, order)
    if not any(a["door"] == "probe" for a in attempts):
        # a door that needs no metadata won: one read for the title, length and chapters
        attempts.append(_probe_attempt(ctx, _probe))
    if transcript is None:
        raise AllDoorsFailed(attempts)
    if transcript.notes.get("language_guessed"):
        ctx.log(f"language: took {transcript.language} of {', '.join(transcript.notes.get('tracks') or [])} "
                "(the player does not say which is spoken); pass --lang to choose")
    info = dict(ctx.info or {})
    for k, v in (transcript.notes.get("page_meta") or {}).items():
        info.setdefault(k, v)  # the player's own title and length when yt-dlp could not read them
    chapters = ytdlp.chapters_from_info(info)
    duration = info.get("duration") or (transcript.lines[-1].start + transcript.lines[-1].dur)
    if chapters and chapters[-1].end is None:
        chapters[-1].end = float(duration)
    meta: dict[str, Any] = {
        "source": ref,
        "kind": source.kind,
        "id": source.id,
        **({k: v for k, v in ytdlp_subs.info_summary(info).items() if k != "id"} if source.kind != "file"
           else {"title": info.get("title"), "duration": info.get("duration")}),
        "door": transcript.door,
        "track": transcript.track,
        "language": transcript.language,
        "generated": transcript.generated,
        "words": transcript.words,
        "lines": len(transcript.lines),
        "chapters": len(chapters),
        "attempts": attempts,
        "transcript_notes": transcript.notes,
        "tool": f"video-digest {__version__}",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    meta["duration"] = duration
    meta["stills"] = take_stills(ctx, transcript, chapters, duration, folder, opts)
    meta["wall_seconds"] = round(time.monotonic() - t_start, 2)
    write_all(folder, transcript, chapters, meta)
    if not opts.keep_media:
        for p in work.glob("*"):
            if p.is_file():
                p.unlink()
        try:
            work.rmdir()
        except OSError:
            pass
    return folder


def take_stills(ctx: RunContext, transcript: Transcript, chapters: list[Chapter], duration: float,
                folder: Path, opts: Options) -> dict[str, Any]:
    score = stills.screen_demo_score(transcript.lines)
    report: dict[str, Any] = {"mode": opts.stills, **score, "taken": 0}
    wanted = opts.stills == "always" or (opts.stills == "auto" and score["screen_demo"])
    if not wanted:
        report["reason"] = "not asked" if opts.stills == "never" else "not a screen demo (pass --stills to force)"
        return report
    try:
        if ctx.source.kind == "file":
            if not (ctx.info or {}).get("has_video", True):
                report["reason"] = "the file has no picture"
                return report
            video = Path(ctx.source.ref)
        else:
            if not ctx.info:
                report["reason"] = "no metadata to choose a picture format from"
                return report
            video = ytdlp.download(ctx, ytdlp.pick_stills_format(ctx.info.get("formats") or []), "picture")
        times = stills.choose(stills.scene_times(video), chapters, duration, opts.max_stills)
        taken = stills.extract(video, times, chapters, folder / "stills")
    except DoorError as e:
        report["reason"] = f"stills failed: {e}"
        return report
    write_json(folder / "stills.json", taken)
    report["taken"] = len(taken)
    return report
