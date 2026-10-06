"""Caption file parsers: YouTube json3, WebVTT and SubRip, each to timed lines in seconds."""

from __future__ import annotations

import html
import re
from typing import Any

from video_digest.models import Line

_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
_TAG = re.compile(r"<[^>]+>")


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", text))).strip()


def parse_json3(payload: dict[str, Any]) -> list[Line]:
    """YouTube's json3 events: one line per event that carries words."""
    out: list[Line] = []
    for ev in payload.get("events") or []:
        text = clean_text("".join(s.get("utf8", "") for s in ev.get("segs") or []))
        if text:
            out.append(Line((ev.get("tStartMs") or 0) / 1000, (ev.get("dDurationMs") or 0) / 1000, text))
    return out


def _seconds(stamp: str) -> float:
    m = _TS.fullmatch(stamp.strip())
    if not m:
        raise ValueError(f"not a cue time: {stamp!r}")
    h, mi, s, frac = m.groups()
    return round(int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(frac.ljust(3, "0")) / 1000, 3)


def _cues(text: str) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    blocks = re.split(r"\r?\n\s*\r?\n", text.replace("﻿", ""))
    for block in blocks:
        rows = [r for r in block.splitlines() if r.strip()]
        for i, row in enumerate(rows):
            if "-->" in row:
                left, right = row.split("-->", 1)
                try:
                    start, end = _seconds(left), _seconds(right.split()[0])
                except (ValueError, IndexError):
                    break
                body = clean_text(" ".join(rows[i + 1:]))
                if body:
                    cues.append((start, end, body))
                break
    return cues


def _dedupe_rolling(cues: list[tuple[float, float, str]]) -> list[Line]:
    """Automatic captions as WebVTT repeat the previous line under the new one; keep each word once."""
    out: list[Line] = []
    prev = ""
    for start, end, body in cues:
        if body == prev:
            continue
        if prev and body.startswith(prev):
            new = body[len(prev):].strip()
        else:
            new = body
        prev = body
        if new:
            out.append(Line(start, max(0.0, end - start), new))
    return out


def parse_vtt(text: str) -> list[Line]:
    return _dedupe_rolling(_cues(text))


def parse_srt(text: str) -> list[Line]:
    return [Line(s, max(0.0, e - s), b) for s, e, b in _cues(text)]


def parse_caption_file(text: str, ext: str) -> list[Line]:
    ext = ext.lower().lstrip(".")
    if ext == "json3":
        import json

        return parse_json3(json.loads(text))
    if ext == "srt":
        return parse_srt(text)
    return parse_vtt(text)


def stamp(seconds: float) -> str:
    """H:MM:SS, the one time format every output uses."""
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


_STAMP_ANY = re.compile(r"^(?:(\d+):)?([0-5]?\d):([0-5]\d)$")


def parse_stamp(value: str | float | int) -> float:
    """H:MM:SS or M:SS or seconds; anything else (a placeholder like 1:00:1x) is refused."""
    if isinstance(value, (int, float)):
        return float(value)
    m = _STAMP_ANY.fullmatch(value.strip())
    if not m:
        raise ValueError(f"not a time: {value!r} (write H:MM:SS)")
    h, mi, s = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s)
