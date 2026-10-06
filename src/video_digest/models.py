"""The shapes every door returns, and the errors that move the run to the next door."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Line:
    """One timed caption line or speech segment, in seconds."""

    start: float
    dur: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"start": round(self.start, 2), "dur": round(self.dur, 2), "text": self.text}


@dataclass
class Chapter:
    start: float
    end: float | None
    title: str

    def to_dict(self) -> dict[str, Any]:
        return {"start": round(self.start, 2), "end": None if self.end is None else round(self.end, 2),
                "title": self.title}


@dataclass
class Transcript:
    """What a door hands back: timed lines plus where they came from."""

    lines: list[Line]
    door: str
    language: str | None = None
    generated: bool | None = None  # True for automatic captions or speech to text
    track: str | None = None  # the caption track or model the words came from
    notes: dict[str, Any] = field(default_factory=dict)

    @property
    def words(self) -> int:
        return sum(len(ln.text.split()) for ln in self.lines)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["lines"] = [ln.to_dict() for ln in self.lines]
        d["words"] = self.words
        return d


class DoorError(RuntimeError):
    """A door could not give a transcript; the run moves to the next door."""


class RateLimited(DoorError):
    """The site answered 429 or a bot check: this door stops and is never retried in the same run."""


class NoCaptions(DoorError):
    """The video has no caption track in the language asked; caption doors stop, speech is next."""


class Refused(DoorError):
    """The door does not apply to this source (a playlist, a cloud address, a missing key)."""


class DoorUnavailable(DoorError):
    """A tool the door needs is not installed (ffmpeg, faster-whisper)."""
