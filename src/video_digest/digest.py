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

from video_digest import __version__
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
    """Every transcript word with a time, spread evenly across the time its line is actually spoken.

    A line's spoken span is the smaller of its displayed length and the gap to the next line: automatic
    captions keep a line on screen well past the start of the next one, and spreading its words over
    the whole display put a found quote (and its link) a second or more after the words were said.
    """
    out: list[Word] = []
    for k, ln in enumerate(lines):
        toks = [t for t in str(ln["text"]).split() if _norm(t)]
        n = len(toks) or 1
        start = float(ln["start"])
        span = float(ln.get("dur") or 0)
        if k + 1 < len(lines):
            gap = float(lines[k + 1]["start"]) - start
            if gap > 0:
                span = min(span, gap)
        for i, tok in enumerate(toks):
            out.append(Word(_norm(tok), start + span * i / n))
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


PARA_MIN, PARA_MAX = 30.0, 45.0  # seconds: a paragraph ends at a sentence end after 30 s, or at 45 s


def paragraphs(lines: list[dict[str, Any]], least: float = PARA_MIN, most: float = PARA_MAX
               ) -> list[tuple[float, str]]:
    """The lines as (start, text) paragraphs: each ends at the first sentence end after `least` seconds,
    or at `most` seconds when the speaker never ends a sentence (automatic captions carry no full stops)."""
    out: list[tuple[float, str]] = []
    buf: list[str] = []
    mark: float | None = None
    for ln in lines:
        text = str(ln["text"]).strip()
        if not text:
            continue
        if mark is None:
            mark = float(ln["start"])
        buf.append(text)
        age = float(ln["start"]) - mark
        if (age >= least and text.endswith((".", "?", "!", '."', '?"', '!"'))) or age >= most:
            out.append((mark, " ".join(buf)))
            buf, mark = [], None
    if buf and mark is not None:
        out.append((mark, " ".join(buf)))
    return out


def reading_file(lines: list[dict[str, Any]]) -> str:
    """The transcript as stamped paragraphs (a sentence end after 30 seconds, or 45 seconds), for reading
    end to end."""
    return "\n\n".join(f"[{stamp(t)}] {text}" for t, text in paragraphs(lines)) + "\n"


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
        "sections": [],
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


# Fields that hold a time or the speaker's own words; every other string in digest.json is the writer's
# prose, where a time-like token must be a real time (a placeholder such as 1:00:1x is refused).
_NOT_PROSE = {"time", "start", "quote", "source"}
_SINGULAR = {"chapters": "chapter", "points": "point", "actions": "action", "sections": "section", "rows": "row"}


def _prose_times(value: Any, where: str, problems: list[str]) -> None:
    """Walk the digest and refuse a placeholder time in any of the writer's own words."""
    if isinstance(value, str):
        problems.extend(f"{where}: {bad!r} is not a time" for bad in _time_tokens_ok(value))
    elif isinstance(value, dict):
        for k, v in value.items():
            if k in _NOT_PROSE:
                continue
            if isinstance(v, list):
                for i, item in enumerate(v, 1):
                    _prose_times(item, f"{where} {_SINGULAR.get(k, k)} {i}".strip(), problems)
            else:
                _prose_times(v, f"{where} {k}".strip(), problems)


def quote_target(d: dict[str, Any], q: dict[str, Any]) -> dict[str, Any] | None:
    """The entry of digest.json a quote record belongs to: a point, an action, or a section's row."""
    try:
        if "point" in q:
            return d["points"][q["point"] - 1]
        if "action" in q:
            return d["actions"][q["action"] - 1]
        if "section" in q:
            return d["sections"][q["section"] - 1]["rows"][q["row"] - 1]
    except (KeyError, IndexError, TypeError):
        return None
    return None


def check(folder: Path, window: float = DEFAULT_WINDOW) -> CheckResult:
    """Every quote (in points, actions and section rows) found in the transcript near its time, every
    time a real one inside the video, chapters in order, and no placeholder time in the prose."""
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
        except (ValueError, AttributeError, TypeError):
            problems.append(f"{where}: {value!r} is not a time (write H:MM:SS)")
            return None
        if duration and t > duration + 1:
            problems.append(f"{where}: {value} is past the end of the video ({stamp(duration)})")
        return t

    def quoted(entry: dict[str, Any], where: str, key: dict[str, int], t: float | None) -> None:
        q = (entry.get("quote") or "").strip()
        if not q:
            return
        found = find_quote(words, q, t, window) if t is not None else None
        quotes.append({**key, "time": entry.get("time"), "quote": q,
                       "found_at": None if found is None else stamp(found),
                       "offset_seconds": None if found is None or t is None else round(found - t, 1)})
        if found is None:
            problems.append(f"{where}: quote not found within {window:.0f} s of {entry.get('time')}: {q[:80]!r}")

    last = -1.0
    for i, ch in enumerate(d.get("chapters") or []):
        t = at(ch.get("start"), f"chapter {i + 1}")
        if t is not None and t <= last:
            problems.append(f"chapter {i + 1}: starts at {ch.get('start')}, not after the chapter before it")
        last = t if t is not None else last
    for i, p in enumerate(d.get("points") or []):
        where = f"point {i + 1}"
        if not (p.get("text") or "").strip():
            problems.append(f"{where}: empty text")
        if p.get("kind") and p["kind"] not in KINDS:
            problems.append(f"{where}: kind {p['kind']!r} is not one of {', '.join(KINDS)}")
        quoted(p, where, {"point": i + 1}, at(p.get("time"), where))
    for s, sec in enumerate(d.get("sections") or [], 1):
        if not (sec.get("title") or "").strip():
            problems.append(f"section {s}: empty title")
        for r, row in enumerate(sec.get("rows") or [], 1):
            where = f"section {s} row {r}"
            if not (row.get("text") or "").strip():
                problems.append(f"{where}: empty text")
            quoted(row, where, {"section": s, "row": r}, at(row.get("time"), where))
    for i, a in enumerate(d.get("actions") or []):
        where = f"action {i + 1}"
        t = at(a["time"], where) if a.get("time") else None
        if (a.get("quote") or "").strip() and not a.get("time"):
            problems.append(f"{where}: a quote needs the time it was said")
        quoted(a, where, {"action": i + 1}, t)
    _prose_times(d, "", problems)
    return CheckResult(problems, quotes, window)


def snap_times(folder: Path, result: CheckResult) -> int:
    """Set each quoted entry's time (point, action, section row) to the second its quote was found at;
    returns how many moved."""
    path = folder / "digest.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    moved = 0
    for q in result.quotes:
        entry = quote_target(d, q)
        if entry is not None and q["found_at"] and entry.get("time") != q["found_at"]:
            entry["time"] = q["found_at"]
            moved += 1
    path.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return moved


# --- rendering ------------------------------------------------------------------------------------

def time_link(source: str | None, kind: str | None, vid: str | None, seconds: float) -> str | None:
    s = int(seconds)
    if kind == "youtube" and vid:
        return f"https://www.youtube.com/watch?v={vid}&t={s}s"
    if kind == "vimeo" and vid:
        return f"https://vimeo.com/{vid}#t={s}s"
    return None


def time_key(p: dict[str, Any]) -> float:
    """A point's seconds for sorting; a malformed or missing time sorts last, so a --draft still renders."""
    try:
        return parse_stamp(p.get("time"))
    except (ValueError, AttributeError, TypeError):
        return float("inf")


def _grouped(points: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    order = {k: i for i, k in enumerate(KINDS)}
    groups: dict[str, list[dict[str, Any]]] = {}
    for p in points:
        groups.setdefault(p.get("kind") or "method", []).append(p)
    return sorted(groups.items(), key=lambda kv: order.get(kv[0], 99))


LABELS = {"method": "Methods", "claim": "Claims", "number": "Numbers", "tool": "Tools", "example": "Examples",
          "warning": "Warnings", "quote": "Quotes"}


def chapter_spans(d: dict[str, Any], meta: dict[str, Any], lines: list[dict[str, Any]] | None
                  ) -> list[dict[str, Any]]:
    """Each digest chapter's end, length and words counted on the transcript (None when no lines given).
    A chapter with a malformed start gets no span; the first takes any words before it, the last any after."""
    chs = d.get("chapters") or []
    starts: list[float | None] = []
    for ch in chs:
        try:
            starts.append(float(parse_stamp(ch.get("start"))))
        except (ValueError, AttributeError, TypeError):
            starts.append(None)
    last_word = max((float(ln["start"]) + float(ln.get("dur") or 0) for ln in lines or []), default=0.0)
    end_all = max(float(meta.get("duration") or 0), last_word)
    out = []
    for i, a in enumerate(starts):
        nxt = next((s for s in starts[i + 1:] if s is not None), None)
        b = nxt if nxt is not None else end_all
        span: dict[str, Any] = {"start": a, "end": None if a is None else b, "words": None}
        if a is not None and lines is not None:
            lo = 0.0 if i == 0 else a
            span["words"] = sum(len(str(ln["text"]).split()) for ln in lines
                                if lo <= float(ln["start"]) < b or (nxt is None and float(ln["start"]) >= b))
        out.append(span)
    return out


def longest_gap(lines: list[dict[str, Any]]) -> tuple[float, float]:
    """The longest stretch with no words on the track: (where it starts, how long), in seconds."""
    best, at = 0.0, 0.0
    for prev, nxt in zip(lines, lines[1:]):
        end = float(prev["start"]) + float(prev.get("dur") or 0)
        if float(nxt["start"]) - end > best:
            best, at = float(nxt["start"]) - end, end
    return at, best


def how_made(meta: dict[str, Any], result: CheckResult, lines: list[dict[str, Any]] | None) -> list[str]:
    """Plain sentences on how the page was made: the doors, the check, the gaps in the words."""
    doors = "; ".join(f"{a['door']} {'answered' if a.get('ok') else 'did not (' + str(a.get('kind')) + ')'}"
                      for a in meta.get("attempts") or [] if a.get("door") != "probe")
    matched = sum(1 for q in result.quotes if q["found_at"])
    out = [f"The words: {meta.get('door')}, {meta.get('track') or 'track not named'}, "
           f"{int(meta.get('words') or 0):,} words in {int(meta.get('lines') or 0):,} timed lines."
           + (f" Doors tried: {doors}." if doors else ""),
           f"The quote check: {matched} of {len(result.quotes)} quotes found in the transcript within "
           f"{result.window:.0f} seconds of their time, by script, before this page was written.",
           "What a script cannot check: a quote given to the wrong speaker or read out of its context; "
           "those are read by hand."]
    if lines:
        at, gap = longest_gap(lines)
        out.insert(2, "Gaps in the words: the longest stretch with no words on the track is "
                      + (f"{stamp(gap)} long, from {stamp(at)} (music, a demo or a missed caption; nothing "
                         "here is drawn from it)." if gap >= 1 else "under a second."))
    if (meta.get("transcript_notes") or {}).get("thin_transcript"):
        out.append(f"A thin track: {meta['transcript_notes']['thin_transcript']}.")
    made = f"video-digest {__version__}"
    if meta.get("tool") and meta["tool"] != made:
        out.append(f"The transcript was made with {meta['tool']} and this page with {made}; neither calls a "
                   "language model.")
    else:
        out.append(f"Made with {made}, which never calls a language model.")
    return out


def _md_cell(text: Any) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def _md_entry(p: dict[str, Any]) -> str:
    who = f" ({p['speaker']})" if p.get("speaker") else ""
    line = f"- **{p.get('time')}**{who} {str(p.get('text') or '').strip()}"
    if p.get("quote"):
        line += f'\n  > "{p["quote"].strip()}"'
    return line


def render_markdown(d: dict[str, Any], meta: dict[str, Any], result: CheckResult,
                    lines: list[dict[str, Any]] | None = None) -> str:
    out = [f"# {d.get('title')}", ""]
    out.append(f"- Source: {d.get('source')}")
    out.append(f"- Length: {stamp(meta.get('duration') or 0)}; transcript from {meta.get('door')} "
               f"({meta.get('words', 0):,} words)")
    matched = sum(1 for q in result.quotes if q["found_at"])
    out.append(f"- Quotes checked against the transcript: {matched} of {len(result.quotes)} found")
    out.append("")
    if d.get("summary"):
        out += ["## Summary", "", d["summary"], ""]
    spans = chapter_spans(d, meta, lines)
    out += ["## Chapters", ""]
    if lines is not None:
        out += ["| Start | Length | Words | Chapter | Speakers | Summary |", "|---|--:|--:|---|---|---|"]
    else:
        out += ["| Start | Chapter | Speakers | Summary |", "|---|---|---|---|"]
    for ch, sp in zip(d.get("chapters") or [], spans):
        cells = [_md_cell(ch.get("start")), _md_cell(ch.get("title")), _md_cell(", ".join(ch.get("speakers") or [])),
                 _md_cell(ch.get("summary"))]
        if lines is not None:
            length = stamp(sp["end"] - sp["start"]) if sp["start"] is not None else ""
            words = f"{sp['words']:,}" if sp["words"] is not None else ""
            cells[1:1] = [length, words]
        out.append("| " + " | ".join(cells) + " |")
    out.append("")
    for kind, pts in _grouped(d.get("points") or []):
        out += [f"## {LABELS.get(kind, kind.title())}", ""]
        out += [_md_entry(p) for p in sorted(pts, key=time_key)]
        out.append("")
    for sec in d.get("sections") or []:
        out += [f"## {sec.get('title') or 'Section'}", ""]
        if sec.get("intro"):
            out += [str(sec["intro"]), ""]
        out += [_md_entry(r) for r in sec.get("rows") or []]
        out.append("")
    if d.get("actions"):
        out += ["## Actions for you", ""]
        for i, a in enumerate(d["actions"], 1):
            because = f" (see {a['time']})" if a.get("time") else ""
            line = f"{i}. {str(a.get('text') or '').strip()}{because}"
            if a.get("quote"):
                line += f'\n   > "{a["quote"].strip()}"'
            out.append(line)
        out.append("")
    out += ["## How this page was made", ""]
    out += [f"- {s}" for s in how_made(meta, result, lines)]
    return "\n".join(out).rstrip() + "\n"
