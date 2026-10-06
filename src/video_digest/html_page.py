"""The digest as one self-contained HTML page: no scripts, no fonts or images from elsewhere, light and dark."""

from __future__ import annotations

from html import escape
from typing import Any

from video_digest.digest import LABELS, CheckResult, _grouped, time_key, time_link
from video_digest.parse import parse_stamp, stamp

CSS = """
:root{--bg:#fbfbfa;--fg:#1d1d1f;--muted:#5f6368;--line:#e3e3e0;--card:#ffffff;--accent:#2457c5;--ok:#1e7d4f;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#141517;--fg:#e8e8e6;--muted:#a3a7ad;--line:#2c2e33;--card:#1b1d21;--accent:#8ab4ff;--ok:#6fcf97;--bad:#ff8a80}}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{display:grid;grid-template-columns:minmax(0,1fr);max-width:1180px;margin:0 auto;padding:24px 20px 64px;gap:32px}
@media (min-width:1000px){.wrap{grid-template-columns:minmax(0,1fr) 220px}nav{position:sticky;top:24px;align-self:start;order:2}}
nav{font-size:14px;border-left:2px solid var(--line);padding-left:14px}
nav a{display:block;color:var(--muted);text-decoration:none;padding:3px 0}nav a:hover{color:var(--accent)}
h1{font-size:28px;line-height:1.25;margin:0 0 8px}h2{font-size:20px;margin:40px 0 12px;padding-top:8px;border-top:1px solid var(--line)}
.meta{color:var(--muted);font-size:14px;margin:0;padding:0;list-style:none}.meta li{margin:2px 0}
a{color:var(--accent)}table{border-collapse:collapse;width:100%;font-size:15px}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--card)}
th,td{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--line)}th{font-size:13px;color:var(--muted);font-weight:600}
tr:last-child td{border-bottom:0}td.t{white-space:nowrap;font-variant-numeric:tabular-nums}
ul.points{list-style:none;padding:0;margin:0}ul.points li{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:0 0 10px}
.time{font-variant-numeric:tabular-nums;font-weight:600;margin-right:6px}.who{color:var(--muted);font-size:14px}
blockquote{margin:8px 0 0;padding:6px 12px;border-left:3px solid var(--line);color:var(--muted);font-style:italic}
.check{font-size:13px;margin-left:6px}.check.ok{color:var(--ok)}.check.bad{color:var(--bad)}
ol.actions li{margin:6px 0}footer{color:var(--muted);font-size:13px;margin-top:48px}
"""


def _t(value: str, meta: dict[str, Any]) -> str:
    try:
        secs = parse_stamp(value)
    except (ValueError, AttributeError, TypeError):
        return escape(str(value))
    link = time_link(meta.get("source"), meta.get("kind"), meta.get("id"), secs)
    label = escape(stamp(secs))
    return f'<a class="time" href="{escape(link)}">{label}</a>' if link else f'<span class="time">{label}</span>'


def render_html(d: dict[str, Any], meta: dict[str, Any], result: CheckResult) -> str:
    found = {q["point"]: q for q in result.quotes}
    matched = sum(1 for q in result.quotes if q["found_at"])
    sections: list[tuple[str, str]] = []
    if d.get("summary"):
        sections.append(("summary", "Summary"))
    sections.append(("chapters", "Chapters"))
    groups = _grouped(d.get("points") or [])
    sections += [(f"k-{k}", LABELS.get(k, k.title())) for k, _ in groups]
    if d.get("actions"):
        sections.append(("actions", "Actions for you"))

    src = d.get("source") or ""
    src_html = f'<a href="{escape(src)}">{escape(src)}</a>' if src.startswith("http") else escape(src)
    body = [f"<h1>{escape(d.get('title') or 'Untitled video')}</h1>", '<ul class="meta">',
            f"<li>Source: {src_html}</li>",
            f"<li>Length {escape(stamp(meta.get('duration') or 0))}; transcript from {escape(str(meta.get('door')))}"
            f" ({int(meta.get('words') or 0):,} words)</li>",
            f"<li>Quotes checked against the transcript: {matched} of {len(result.quotes)} found</li>", "</ul>"]
    if d.get("summary"):
        body += ['<h2 id="summary">Summary</h2>', f"<p>{escape(d['summary'])}</p>"]
    body += ['<h2 id="chapters">Chapters</h2>', '<div class="tablewrap"><table>',
             "<thead><tr><th>Start</th><th>Chapter</th><th>Speakers</th><th>Summary</th></tr></thead><tbody>"]
    for ch in d.get("chapters") or []:
        body.append(f"<tr><td class=\"t\">{_t(ch.get('start', ''), meta)}</td><td>{escape(ch.get('title', ''))}</td>"
                    f"<td>{escape(', '.join(ch.get('speakers') or []))}</td><td>{escape(ch.get('summary', ''))}</td></tr>")
    body.append("</tbody></table></div>")
    index = {id(p): i + 1 for i, p in enumerate(d.get("points") or [])}
    for kind, pts in groups:
        body += [f'<h2 id="k-{escape(kind)}">{escape(LABELS.get(kind, kind.title()))}</h2>', '<ul class="points">']
        for p in sorted(pts, key=time_key):
            who = f' <span class="who">{escape(p["speaker"])}</span>' if p.get("speaker") else ""
            item = f"<li>{_t(p.get('time', ''), meta)}{who} {escape(p.get('text', '').strip())}"
            if p.get("quote"):
                q = found.get(index[id(p)])
                mark = (f'<span class="check ok">found at {escape(q["found_at"])}</span>' if q and q["found_at"]
                        else '<span class="check bad">not found in the transcript</span>')
                item += f"<blockquote>&ldquo;{escape(p['quote'].strip())}&rdquo; {mark}</blockquote>"
            body.append(item + "</li>")
        body.append("</ul>")
    if d.get("actions"):
        body += ['<h2 id="actions">Actions for you</h2>', '<ol class="actions">']
        for a in d["actions"]:
            because = f" (see {_t(a['time'], meta)})" if a.get("time") else ""
            body.append(f"<li>{escape(a.get('text', '').strip())}{because}</li>")
        body.append("</ol>")
    body.append(f"<footer>Made with video-digest. Every quote above was matched against transcript.json "
                f"within {int(result.window)} seconds of its time before this page was written.</footer>")
    nav = "".join(f'<a href="#{escape(a)}">{escape(label)}</a>' for a, label in sections)
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{escape(d.get('title') or 'Video digest')}</title><style>{CSS}</style></head><body>"
            f"<div class=\"wrap\"><nav aria-label=\"Sections\">{nav}</nav><main>{''.join(body)}</main></div>"
            "</body></html>\n")
