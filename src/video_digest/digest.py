"""The digest step: a skeleton to fill, a quote check against the transcript, and the Markdown and HTML pages.

The words of the digest are written by a person or an agent (the Claude Code skill in skills/video-digest);
this module never calls a language model. What it guarantees: every quote in the digest is found in the
transcript, in order, within a window of the time it is given at, before anyone reads the page.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from video_digest.parse import parse_stamp, stamp

DEFAULT_WINDOW = 75.0  # seconds either side of a quote's stated time
KINDS = ("method", "claim", "number", "tool", "example", "warning", "quote")
# H:MM:SS or M:SS, and the placeholders that look like one (1:00:1x, 0:4?); a ratio like 16:9 is not a time
_TIME_LIKE = re.compile(r"(?<![\w:])\d{1,2}:[0-5x?][\dx?](?::[0-5x?][\dx?])?(?![\w:])", re.I)


@dataclass
class Word:
    norm: str
    time: float


def _norm(token: str) -> str:
    return re.sub(r"[^0-9a-z%$]+", "", token.lower().replace("’", "'").replace("'", ""))


def word_index(lines: list[dict[str, Any]]) -> list[Word]:
    """Every transcript word with a time, spread evenly across its line."""
    out: list[Word] = []
    for ln in lines:
        toks = [t for t in str(ln["text"]).split() if _norm(t)]
        n = len(toks) or 1
        for i, tok in enumerate(toks):
            out.append(Word(_norm(tok), float(ln["start"]) + float(ln.get("dur") or 0) * i / n))
    return out


def find_quote(words: list[Word], quote: str, near: float | None, window: float = DEFAULT_WINDOW
               ) -> float | None:
    """The time the quote starts at, the occurrence nearest `near` within the window. An ellipsis
    splits a quote into fragments that must appear in order, each within the window."""
    fragments = [f for f in re.split(r"\.\.\.|…|\[\.\.\.\]", quote) if [_norm(t) for t in f.split() if _norm(t)]]
    if not fragments:
        return None
    seqs = [[_norm(t) for t in f.split() if _norm(t)] for f in fragments]
    norms = [w.norm for w in words]

    def starts(seq: list[str], lo: int = 0) -> list[int]:
        hits = []
        first = seq[0]
        for i in range(lo, len(norms) - len(seq) + 1):
            if norms[i] == first and norms[i:i + len(seq)] == seq:
                hits.append(i)
        return hits

    best: tuple[float, float] | None = None  # (distance, time)
    for i in starts(seqs[0]):
        t = words[i].time
        if near is not None and abs(t - near) > window:
            continue
        pos, ok = i + len(seqs[0]), True
        for seq in seqs[1:]:
            nxt = [j for j in starts(seq, pos) if words[j].time - t <= window * 2]
            if not nxt:
                ok = False
                break
            pos = nxt[0] + len(seq)
        if ok:
            d = abs(t - near) if near is not None else 0.0
            if best is None or d < best[0]:
                best = (d, t)
    return None if best is None else best[1]


def _load(folder: Path, name: str) -> Any:
    return json.loads((folder / name).read_text(encoding="utf-8"))


def reading_file(lines: list[dict[str, Any]], every: float = 30.0) -> str:
    """The transcript as paragraphs with a time stamp about every 30 seconds, for reading end to end."""
    out: list[str] = []
    buf: list[str] = []
    mark = None
    for ln in lines:
        if mark is None:
            mark = float(ln["start"])
        buf.append(str(ln["text"]))
        if float(ln["start"]) - mark >= every:
            out.append(f"[{stamp(mark)}] " + " ".join(buf))
            buf, mark = [], None
    if buf and mark is not None:
        out.append(f"[{stamp(mark)}] " + " ".join(buf))
    return "\n\n".join(out) + "\n"


def init(folder: Path, force: bool = False) -> Path:
    """Write digest.json (chapters prefilled from chapters.json) and reading.md."""
    meta = _load(folder, "meta.json")
    tr = _load(folder, "transcript.json")
    chapters = _load(folder, "chapters.json") if (folder / "chapters.json").exists() else []
    target = folder / "digest.json"
    if target.exists() and not force:
        raise FileExistsError(f"{target} exists (pass --force to overwrite)")
    skeleton = {
        "title": meta.get("title") or "Untitled video",
        "source": meta.get("source"),
        "summary": "",
        "chapters": [{"start": stamp(c["start"]), "title": c["title"], "speakers": [], "summary": ""}
                     for c in chapters] or [{"start": "0:00:00", "title": "Whole video", "speakers": [],
                                              "summary": ""}],
        "points": [{"time": "0:00:00", "kind": "method", "text": "", "quote": "", "speaker": ""}],
        "actions": [],
    }
    target.write_text(json.dumps(skeleton, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    (folder / "reading.md").write_text(reading_file(tr["lines"]), encoding="utf-8", newline="\n")
    return target


@dataclass
class CheckResult:
    problems: list[str]
    quotes: list[dict[str, Any]]
    window: float = DEFAULT_WINDOW

    @property
    def ok(self) -> bool:
        return not self.problems


def _time_tokens_ok(text: str) -> list[str]:
    """A time-like token that is not a full H:MM:SS or M:SS (a placeholder such as 1:00:1x) is refused."""
    bad = []
    for m in _TIME_LIKE.finditer(text or ""):
        try:
            parse_stamp(m.group(0))
        except ValueError:
            bad.append(m.group(0))
    return bad


def check(folder: Path, window: float = DEFAULT_WINDOW) -> CheckResult:
    d = _load(folder, "digest.json")
    tr = _load(folder, "transcript.json")
    meta = _load(folder, "meta.json")
    duration = float(meta.get("duration") or 0) or None
    words = word_index(tr["lines"])
    problems: list[str] = []
    quotes: list[dict[str, Any]] = []

    def at(value: Any, where: str) -> float | None:
        try:
            t = parse_stamp(value)
        except (ValueError, AttributeError):
            problems.append(f"{where}: {value!r} is not a time (write H:MM:SS)")
            return None
        if duration and t > duration + 1:
            problems.append(f"{where}: {value} is past the end of the video ({stamp(duration)})")
        return t

    last = -1.0
    for i, ch in enumerate(d.get("chapters") or []):
        t = at(ch.get("start"), f"chapter {i + 1}")
        if t is not None and t <= last:
            problems.append(f"chapter {i + 1}: starts at {ch.get('start')}, not after the chapter before it")
        last = t if t is not None else last
        for bad in _time_tokens_ok(ch.get("summary", "")):
            problems.append(f"chapter {i + 1} summary: {bad!r} is not a time")
    for i, p in enumerate(d.get("points") or []):
        where = f"point {i + 1}"
        if not (p.get("text") or "").strip():
            problems.append(f"{where}: empty text")
        if p.get("kind") and p["kind"] not in KINDS:
            problems.append(f"{where}: kind {p['kind']!r} is not one of {', '.join(KINDS)}")
        for bad in _time_tokens_ok(p.get("text", "")):
            problems.append(f"{where} text: {bad!r} is not a time")
        t = at(p.get("time"), where)
        q = (p.get("quote") or "").strip()
        if q:
            found = find_quote(words, q, t, window) if t is not None else None
            quotes.append({"point": i + 1, "time": p.get("time"), "quote": q,
                           "found_at": None if found is None else stamp(found),
                           "offset_seconds": None if found is None or t is None else round(found - t, 1)})
            if found is None:
                problems.append(f"{where}: quote not found within {window:.0f} s of {p.get('time')}: {q[:80]!r}")
    for i, a in enumerate(d.get("actions") or []):
        if a.get("time"):
            at(a["time"], f"action {i + 1}")
    return CheckResult(problems, quotes, window)


# --- rendering ------------------------------------------------------------------------------------

def time_link(source: str | None, kind: str | None, vid: str | None, seconds: float) -> str | None:
    s = int(seconds)
    if kind == "youtube" and vid:
        return f"https://www.youtube.com/watch?v={vid}&t={s}s"
    if kind == "vimeo" and vid:
        return f"https://vimeo.com/{vid}#t={s}s"
    return None


def _grouped(points: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    order = {k: i for i, k in enumerate(KINDS)}
    groups: dict[str, list[dict[str, Any]]] = {}
    for p in points:
        groups.setdefault(p.get("kind") or "method", []).append(p)
    return sorted(groups.items(), key=lambda kv: order.get(kv[0], 99))


LABELS = {"method": "Methods", "claim": "Claims", "number": "Numbers", "tool": "Tools", "example": "Examples",
          "warning": "Warnings", "quote": "Quotes"}


def render_markdown(d: dict[str, Any], meta: dict[str, Any], result: CheckResult) -> str:
    out = [f"# {d.get('title')}", ""]
    out.append(f"- Source: {d.get('source')}")
    out.append(f"- Length: {stamp(meta.get('duration') or 0)}; transcript from {meta.get('door')} "
               f"({meta.get('words', 0):,} words)")
    matched = sum(1 for q in result.quotes if q["found_at"])
    out.append(f"- Quotes checked against the transcript: {matched} of {len(result.quotes)} found")
    out.append("")
    if d.get("summary"):
        out += ["## Summary", "", d["summary"], ""]
    out += ["## Chapters", "", "| Start | Chapter | Speakers | Summary |", "|---|---|---|---|"]
    for ch in d.get("chapters") or []:
        cells = [ch.get("start", ""), ch.get("title", ""), ", ".join(ch.get("speakers") or []),
                 (ch.get("summary") or "").replace("|", "\\|").replace("\n", " ")]
        out.append("| " + " | ".join(cells) + " |")
    out.append("")
    for kind, pts in _grouped(d.get("points") or []):
        out += [f"## {LABELS.get(kind, kind.title())}", ""]
        for p in sorted(pts, key=lambda p: parse_stamp(p.get("time", "0:00"))):
            who = f" ({p['speaker']})" if p.get("speaker") else ""
            line = f"- **{p.get('time')}**{who} {p.get('text', '').strip()}"
            if p.get("quote"):
                line += f'\n  > "{p["quote"].strip()}"'
            out.append(line)
        out.append("")
    if d.get("actions"):
        out += ["## Actions for you", ""]
        for i, a in enumerate(d["actions"], 1):
            because = f" (see {a['time']})" if a.get("time") else ""
            out.append(f"{i}. {a.get('text', '').strip()}{because}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"
