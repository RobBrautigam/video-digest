"""The digest and the transcript as self-contained HTML pages: no scripts, no fonts or images from elsewhere,
light and dark."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from video_digest.digest import (LABELS, CheckResult, _grouped, chapter_spans, how_made, longest_gap, paragraphs,
                                 time_key, time_link)
from video_digest.parse import parse_stamp, stamp

CSS = """
:root{--bg:#fbfbfa;--fg:#1d1d1f;--muted:#5f6368;--line:#e3e3e0;--card:#ffffff;--accent:#2457c5;--ok:#1e7d4f;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#141517;--fg:#e8e8e6;--muted:#a3a7ad;--line:#2c2e33;--card:#1b1d21;--accent:#8ab4ff;--ok:#6fcf97;--bad:#ff8a80}}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{display:grid;grid-template-columns:minmax(0,1fr);max-width:1180px;margin:0 auto;padding:24px 20px 64px;gap:32px}
@media (min-width:1000px){.wrap{grid-template-columns:minmax(0,1fr) 220px}nav{position:sticky;top:24px;align-self:start;order:2;max-height:calc(100vh - 48px);overflow-y:auto}}
nav{font-size:14px;border-left:2px solid var(--line);padding-left:14px}
nav a{display:block;color:var(--muted);text-decoration:none;padding:3px 0}nav a:hover{color:var(--accent)}
h1{font-size:28px;line-height:1.25;margin:0 0 8px}h2{font-size:20px;margin:40px 0 12px;padding-top:8px;border-top:1px solid var(--line)}
.meta{color:var(--muted);font-size:14px;margin:0;padding:0;list-style:none}.meta li{margin:2px 0}
a{color:var(--accent)}table{border-collapse:collapse;width:100%;font-size:15px}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--card)}
th,td{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--line)}th{font-size:13px;color:var(--muted);font-weight:600}
tr:last-child td{border-bottom:0}td.t,td.n{white-space:nowrap;font-variant-numeric:tabular-nums}td.n{text-align:right}
ul.points{list-style:none;padding:0;margin:0}ul.points li{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:0 0 10px}
.time{font-variant-numeric:tabular-nums;font-weight:600;margin-right:6px}.who{color:var(--muted);font-size:14px}
blockquote{margin:8px 0 0;padding:6px 12px;border-left:3px solid var(--line);color:var(--muted);font-style:italic}
.check{font-size:13px;margin-left:6px}.check.ok{color:var(--ok)}.check.bad{color:var(--bad)}
ol.actions li{margin:6px 0}ul.made{color:var(--muted);font-size:15px}footer{color:var(--muted);font-size:13px;margin-top:48px}
.span{color:var(--muted);font-size:14px;margin:-6px 0 10px}
details.fold{background:var(--card);border:1px solid var(--line);border-radius:8px;margin:0 0 10px}
details.fold summary{cursor:pointer;padding:10px 14px;color:var(--muted);font-size:14px}
details.fold[open] summary{border-bottom:1px solid var(--line)}details.fold .body{padding:4px 14px 6px}
details.fold p{margin:10px 0}
"""

FOLD_SPLIT = 4500  # words: a chapter longer than this is split into equal folds on the transcript page


def _t(value: Any, meta: dict[str, Any]) -> str:
    try:
        secs = parse_stamp(value)
    except (ValueError, AttributeError, TypeError):
        return escape(str(value))
    link = time_link(meta.get("source"), meta.get("kind"), meta.get("id"), secs)
    label = escape(stamp(secs))
    return f'<a class="time" href="{escape(link)}">{label}</a>' if link else f'<span class="time">{label}</span>'


def _mark(q: dict[str, Any] | None) -> str:
    if q and q["found_at"]:
        return f'<span class="check ok">found at {escape(q["found_at"])}</span>'
    return '<span class="check bad">not found in the transcript</span>'


def _entry(p: dict[str, Any], meta: dict[str, Any], q: dict[str, Any] | None) -> str:
    who = f' <span class="who">{escape(str(p["speaker"]))}</span>' if p.get("speaker") else ""
    item = f"<li>{_t(p.get('time', ''), meta)}{who} {escape(str(p.get('text') or '').strip())}"
    if p.get("quote"):
        item += f"<blockquote>&ldquo;{escape(p['quote'].strip())}&rdquo; {_mark(q)}</blockquote>"
    return item + "</li>"


def _page(title: str, nav: list[tuple[str, str]], body: list[str]) -> str:
    links = "".join(f'<a href="#{escape(a)}">{escape(label)}</a>' for a, label in nav)
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{escape(title)}</title><style>{CSS}</style></head><body>"
            f"<div class=\"wrap\"><nav aria-label=\"Sections\">{links}</nav><main>{''.join(body)}</main></div>"
            "</body></html>\n")


def _source(src: str) -> str:
    return f'<a href="{escape(src)}">{escape(src)}</a>' if src.startswith(("http://", "https://")) else escape(src)


def render_html(d: dict[str, Any], meta: dict[str, Any], result: CheckResult,
                lines: list[dict[str, Any]] | None = None, transcript_page: str | None = None) -> str:
    """The digest page. With the transcript's lines, the chapter table carries each chapter's length and
    words and the page names the longest gap; with `transcript_page`, it links the full transcript."""
    by_point = {q["point"]: q for q in result.quotes if "point" in q}
    by_action = {q["action"]: q for q in result.quotes if "action" in q}
    by_row = {(q["section"], q["row"]): q for q in result.quotes if "section" in q}
    matched = sum(1 for q in result.quotes if q["found_at"])
    sections: list[tuple[str, str]] = []
    if d.get("summary"):
        sections.append(("summary", "Summary"))
    sections.append(("chapters", "Chapters"))
    groups = _grouped(d.get("points") or [])
    sections += [(f"k-{k}", LABELS.get(k, k.title())) for k, _ in groups]
    extra = d.get("sections") or []
    sections += [(f"s-{i}", str(s.get("title") or f"Section {i}")) for i, s in enumerate(extra, 1)]
    if d.get("actions"):
        sections.append(("actions", "Actions for you"))
    sections.append(("made", "How this page was made"))

    body = [f"<h1>{escape(d.get('title') or 'Untitled video')}</h1>", '<ul class="meta">',
            f"<li>Source: {_source(str(d.get('source') or ''))}</li>",
            f"<li>Length {escape(stamp(meta.get('duration') or 0))}; transcript from {escape(str(meta.get('door')))}"
            f" ({int(meta.get('words') or 0):,} words)"
            + (f'; <a href="{escape(transcript_page)}">the full transcript</a>' if transcript_page else "") + "</li>",
            f"<li>Quotes checked against the transcript: {matched} of {len(result.quotes)} found</li>", "</ul>"]
    if d.get("summary"):
        body += ['<h2 id="summary">Summary</h2>', f"<p>{escape(d['summary'])}</p>"]
    counted = lines is not None
    head = "<th>Start</th>" + ("<th>Length</th><th>Words</th>" if counted else "")
    body += ['<h2 id="chapters">Chapters</h2>', '<div class="tablewrap"><table>',
             f"<thead><tr>{head}<th>Chapter</th><th>Speakers</th><th>Summary</th></tr></thead><tbody>"]
    for ch, sp in zip(d.get("chapters") or [], chapter_spans(d, meta, lines)):
        cells = f"<td class=\"t\">{_t(ch.get('start', ''), meta)}</td>"
        if counted:
            length = stamp(sp["end"] - sp["start"]) if sp["start"] is not None else ""
            words = f"{sp['words']:,}" if sp["words"] is not None else ""
            cells += f'<td class="n">{escape(length)}</td><td class="n">{escape(words)}</td>'
        body.append(f"<tr>{cells}<td>{escape(str(ch.get('title') or ''))}</td>"
                    f"<td>{escape(', '.join(ch.get('speakers') or []))}</td>"
                    f"<td>{escape(str(ch.get('summary') or ''))}</td></tr>")
    body.append("</tbody></table></div>")
    index = {id(p): i + 1 for i, p in enumerate(d.get("points") or [])}
    for kind, pts in groups:
        body += [f'<h2 id="k-{escape(kind)}">{escape(LABELS.get(kind, kind.title()))}</h2>', '<ul class="points">']
        body += [_entry(p, meta, by_point.get(index[id(p)])) for p in sorted(pts, key=time_key)]
        body.append("</ul>")
    for s, sec in enumerate(extra, 1):
        body.append(f'<h2 id="s-{s}">{escape(str(sec.get("title") or f"Section {s}"))}</h2>')
        if sec.get("intro"):
            body.append(f"<p>{escape(str(sec['intro']))}</p>")
        body.append('<ul class="points">')
        body += [_entry(r, meta, by_row.get((s, n))) for n, r in enumerate(sec.get("rows") or [], 1)]
        body.append("</ul>")
    if d.get("actions"):
        body += ['<h2 id="actions">Actions for you</h2>', '<ol class="actions">']
        for n, a in enumerate(d["actions"], 1):
            because = f" (see {_t(a['time'], meta)})" if a.get("time") else ""
            item = f"<li>{escape(str(a.get('text') or '').strip())}{because}"
            if a.get("quote"):
                item += f"<blockquote>&ldquo;{escape(a['quote'].strip())}&rdquo; {_mark(by_action.get(n))}</blockquote>"
            body.append(item + "</li>")
        body.append("</ol>")
    body += ['<h2 id="made">How this page was made</h2>', '<ul class="made">']
    body += [f"<li>{escape(s)}</li>" for s in how_made(meta, result, lines)]
    body.append("</ul>")
    body.append(f"<footer>Made with video-digest. Every quote above was matched against transcript.json "
                f"within {int(result.window)} seconds of its time before this page was written.</footer>")
    return _page(str(d.get("title") or "Video digest"), sections, body)


def _folds(paras: list[tuple[float, str]], words: int) -> list[list[tuple[float, str]]]:
    """A chapter's paragraphs in equal folds of at most about FOLD_SPLIT words."""
    n = max(1, -(-words // FOLD_SPLIT))
    if n == 1:
        return [paras]
    target, out, cur, count = words / n, [], [], 0
    for p in paras:
        cur.append(p)
        count += len(p[1].split())
        if count >= target * (len(out) + 1) and len(out) < n - 1:
            out.append(cur)
            cur = []
    return out + ([cur] if cur else [])


def write_transcript_page(folder: Path) -> Path:
    """transcript.html from a run folder: the digest's chapters when digest.json has good ones, else the
    video's own (chapters.json); a link to digest.html when it exists."""
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    tr = json.loads((folder / "transcript.json").read_text(encoding="utf-8"))
    chapters: list[dict[str, Any]] = []
    if (folder / "chapters.json").exists():
        chapters = json.loads((folder / "chapters.json").read_text(encoding="utf-8"))
    if (folder / "digest.json").exists():
        try:
            d = json.loads((folder / "digest.json").read_text(encoding="utf-8"))
            mine = [{"start": parse_stamp(c["start"]), "title": c.get("title") or "Untitled"}
                    for c in d.get("chapters") or []]
            if mine and any(str(c["title"]).strip() for c in mine):
                chapters = mine
        except (ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
            pass  # a digest still being written: the video's own chapters
    meta = {**meta, "title": meta.get("title") or tr.get("title")}
    target = folder / "transcript.html"
    digest_page = "digest.html" if (folder / "digest.html").exists() else None
    target.write_text(render_transcript_html(meta, chapters, tr.get("lines") or [], digest_page),
                      encoding="utf-8", newline="\n")
    return target


def render_transcript_html(meta: dict[str, Any], chapters: list[dict[str, Any]], lines: list[dict[str, Any]],
                           digest_page: str | None = None) -> str:
    """The whole transcript as one page: a section per chapter, its words in a fold of stamped paragraphs
    (a paragraph ends at a sentence end after 30 seconds, or at 45 seconds), each stamp a link to that
    second of the video where the site has one."""
    chs = [{"start": float(c.get("start") or 0), "title": str(c.get("title") or "Untitled")} for c in chapters]
    chs.sort(key=lambda c: c["start"])
    last_word = max((float(ln["start"]) + float(ln.get("dur") or 0) for ln in lines), default=0.0)
    end_all = max(float(meta.get("duration") or 0), last_word)
    if not chs:
        chs = [{"start": 0.0, "title": "Transcript"}]
    title = str(meta.get("title") or meta.get("id") or "Transcript")
    total = sum(len(str(ln["text"]).split()) for ln in lines)
    gen = {True: "automatic", False: "manual"}.get(meta.get("generated"), "not stated")
    body = [f"<h1>{escape(title)}</h1>", '<ul class="meta">',
            f"<li>Source: {_source(str(meta.get('source') or ''))}</li>",
            f"<li>Length {escape(stamp(end_all))}; {total:,} words from {escape(str(meta.get('door')))} "
            f"({escape(str(meta.get('track') or 'track not named'))}, captions {gen})</li>"]
    gap_at, gap = longest_gap(lines)
    if gap >= 1:
        body.append(f"<li>Longest stretch with no words: {escape(stamp(gap))}, from {_t(stamp(gap_at), meta)}</li>")
    if digest_page:
        body.append(f'<li><a href="{escape(digest_page)}">The digest</a></li>')
    body.append("</ul>")
    nav: list[tuple[str, str]] = []
    for i, c in enumerate(chs):
        a = 0.0 if i == 0 else c["start"]
        b = chs[i + 1]["start"] if i + 1 < len(chs) else end_all
        mine = [ln for ln in lines if a <= float(ln["start"]) < b or (i + 1 == len(chs) and float(ln["start"]) >= b)]
        words = sum(len(str(ln["text"]).split()) for ln in mine)
        anchor = f"c-{i + 1}"
        nav.append((anchor, f"{stamp(c['start'])} {c['title']}"))
        body += [f'<h2 id="{anchor}">{escape(c["title"])}</h2>',
                 f'<p class="span">{_t(stamp(c["start"]), meta)} to {escape(stamp(b))}, '
                 f"{escape(stamp(max(0.0, b - c['start'])))} long, {words:,} words</p>"]
        parts = _folds(paragraphs(mine), words)
        for j, part in enumerate(parts, 1):
            if not part:
                continue
            p_end = parts[j][0][0] if j < len(parts) and parts[j] else b
            n = sum(len(t.split()) for _, t in part)
            label = f"part {j} of {len(parts)}, " if len(parts) > 1 else ""
            body.append(f'<details class="fold"><summary>Transcript, {label}{escape(stamp(part[0][0]))} to '
                        f"{escape(stamp(p_end))} ({n:,} words)</summary><div class=\"body\">")
            body += [f"<p>{_t(stamp(t), meta)} {escape(text)}</p>" for t, text in part]
            body.append("</div></details>")
    body.append("<footer>Made with video-digest. The words are the track's own, as the door gave them; each "
                "chapter opens closed, click its transcript to read it.</footer>")
    return _page(f"{title}: transcript", nav, body)
