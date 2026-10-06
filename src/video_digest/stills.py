"""Scene stills: ffmpeg finds where the picture changes (at 360p), and one still per change is filed under its chapter."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from video_digest.models import Chapter, DoorUnavailable, Line
from video_digest.parse import stamp

SCENE_THRESHOLD = 0.30
# Words a speaker says when the screen carries something: a signal of a screen demo, not proof.
POINTING = re.compile(r"\b(on (?:the |my |your )?screen|you can see|right here|over here|click(?:ing)? (?:on )?|"
                      r"this button|let me show you|scroll (?:down|up)|drag(?:ging)? |type in|the menu)\b", re.I)


def screen_demo_score(lines: list[Line]) -> dict[str, Any]:
    """Pointing phrases per minute. A demo when there are at least 5 and at least 0.5 a minute."""
    hits = sum(len(POINTING.findall(ln.text)) for ln in lines)
    minutes = max((lines[-1].start + lines[-1].dur) / 60 if lines else 0.0, 1 / 60)
    rate = hits / minutes
    return {"pointing_phrases": hits, "per_minute": round(rate, 2), "screen_demo": hits >= 5 and rate >= 0.5}


def scene_times(video: Path, threshold: float = SCENE_THRESHOLD, run: Callable[..., Any] = subprocess.run
                ) -> list[float]:
    if not shutil.which("ffmpeg"):
        raise DoorUnavailable("ffmpeg is not on PATH")
    # the comma inside gt() is escaped for ffmpeg's filter parser; no shell is involved
    vf = f"scale=-2:360,select=gt(scene\\,{threshold:.2f}),showinfo"
    p = run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(video), "-an", "-vf", vf, "-f", "null", "-"],
            capture_output=True, check=False)
    err = p.stderr.decode("utf-8", "replace") if isinstance(p.stderr, bytes) else str(p.stderr)
    return [float(m.group(1)) for m in re.finditer(r"pts_time:\s*([0-9.]+)", err)]


def choose(times: list[float], chapters: list[Chapter], duration: float | None, cap: int) -> list[float]:
    """Every scene change up to the cap (spread evenly past it), plus one still for any chapter with none."""
    times = sorted(set(round(t, 2) for t in times))
    if len(times) > cap:
        step = len(times) / cap
        times = [times[int(i * step)] for i in range(cap)]
    for i, ch in enumerate(chapters):
        end = ch.end if ch.end is not None else (chapters[i + 1].start if i + 1 < len(chapters) else duration)
        if end is None:
            continue
        if not any(ch.start <= t < end for t in times):
            times.append(round(ch.start + min(5.0, max(0.0, (end - ch.start) / 2)), 2))
    if not times:
        times = [min(5.0, (duration or 10) / 2)]
    return sorted(set(times))


def chapter_of(t: float, chapters: list[Chapter]) -> int:
    idx = 0
    for i, ch in enumerate(chapters):
        if t >= ch.start:
            idx = i
    return idx


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "part"


def extract(video: Path, times: list[float], chapters: list[Chapter], outdir: Path,
            run: Callable[..., Any] = subprocess.run) -> list[dict[str, Any]]:
    chapters = chapters or [Chapter(0.0, None, "Whole video")]
    out: list[dict[str, Any]] = []
    for t in times:
        ci = chapter_of(t, chapters)
        folder = outdir / f"{ci + 1:02d}-{slug(chapters[ci].title)}"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{stamp(t).replace(':', '-')}.jpg"
        p = run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.2f}",
                 "-i", str(video), "-frames:v", "1", "-vf", "scale=-2:360", "-q:v", "4", str(target)],
                capture_output=True, check=False)
        if p.returncode == 0 and target.exists():
            out.append({"time": round(t, 2), "stamp": stamp(t), "chapter": ci + 1,
                        "chapter_title": chapters[ci].title, "file": target.relative_to(outdir.parent).as_posix()})
    return out
