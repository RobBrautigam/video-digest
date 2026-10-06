"""The output folder: transcript.md, transcript.json, chapters.json, meta.json (and stills/ when taken)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from video_digest.models import Chapter, Transcript
from video_digest.parse import stamp


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def transcript_markdown(t: Transcript, chapters: list[Chapter], title: str, source: str,
                        duration: float | None) -> str:
    gen = {True: "automatic", False: "manual", None: "unknown"}[t.generated]
    head = [f"# {title}", "",
            f"- Source: {source}",
            f"- Door: {t.door} ({t.track or 'n/a'}), language {t.language or 'unknown'}, captions {gen}",
            f"- Length: {stamp(duration) if duration else 'unknown'}, {t.words:,} words, {len(t.lines):,} lines",
            ""]
    body: list[str] = []
    marks = list(chapters)
    ci = 0
    if not marks:
        body.append("## Transcript")
        body.append("")
    for ln in t.lines:
        while ci < len(marks) and ln.start >= marks[ci].start - 0.5:
            if body:
                body.append("")
            body.append(f"## {marks[ci].title} ({stamp(marks[ci].start)})")
            body.append("")
            ci += 1
        body.append(f"[{stamp(ln.start)}] {ln.text}")
    return "\n".join(head + body) + "\n"


def write_all(folder: Path, t: Transcript, chapters: list[Chapter], meta: dict[str, Any]) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    title = meta.get("title") or meta.get("id") or "Untitled video"
    paths = {
        "transcript.md": folder / "transcript.md",
        "transcript.json": folder / "transcript.json",
        "chapters.json": folder / "chapters.json",
        "meta.json": folder / "meta.json",
    }
    paths["transcript.md"].write_text(
        transcript_markdown(t, chapters, title, meta.get("source", ""), meta.get("duration")),
        encoding="utf-8", newline="\n")
    write_json(paths["transcript.json"], {"title": title, "source": meta.get("source"), **t.to_dict()})
    write_json(paths["chapters.json"], [c.to_dict() for c in chapters])
    write_json(paths["meta.json"], meta)
    return paths
