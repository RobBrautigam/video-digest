"""A local file's metadata through ffprobe: length, title tag and any chapters the container carries."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from video_digest.models import DoorUnavailable


def probe(path: Path, run: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    if not shutil.which("ffprobe"):
        raise DoorUnavailable("ffprobe is not on PATH; install ffmpeg")
    p = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_chapters",
             "-show_streams", str(path)], capture_output=True, check=False)
    data = json.loads(p.stdout or b"{}")
    fmt = data.get("format") or {}
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    chapters = [{"start_time": float(c.get("start_time") or 0), "end_time": float(c.get("end_time") or 0),
                 "title": (c.get("tags") or {}).get("title") or f"Chapter {i + 1}"}
                for i, c in enumerate(data.get("chapters") or [])]
    has_video = any(s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")
                    for s in data.get("streams") or [])
    return {
        "id": path.stem,
        "title": tags.get("title") or path.stem,
        "duration": float(fmt["duration"]) if fmt.get("duration") else None,
        "chapters": chapters,
        "has_video": has_video,
        "webpage_url": None,
        "extractor_key": "file",
    }
