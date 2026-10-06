"""The optional paid door (Supadata): off unless the user sets their own key AND passes --allow-paid."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from video_digest.context import RunContext
from video_digest.models import DoorError, Line, NoCaptions, Refused, Transcript

NAME = "supadata (paid)"
KEY_ENV = "SUPADATA_API_KEY"
MODE_ENV = "VIDEO_DIGEST_SUPADATA_MODE"  # native (default: existing captions only), auto or generate
API = "https://api.supadata.ai/v1/transcript"
POLLS = 12


def _get(ctx: RunContext, url: str, key: str) -> dict[str, Any]:
    body = ctx.fetch(url, {"x-api-key": key, "Accept": "application/json"})
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise DoorError("Supadata answered something that is not JSON") from e


def run(ctx: RunContext) -> Transcript:
    key = ctx.env.get(KEY_ENV, "").strip()
    if not ctx.allow_paid:
        raise Refused("the paid door is off (pass --allow-paid and set SUPADATA_API_KEY to use it)")
    if not key:
        raise Refused(f"the paid door needs your own key in {KEY_ENV}")
    if ctx.source.kind == "file":
        raise Refused("the paid door reads URLs, not local files")
    params = {"url": ctx.source.ref, "text": "false", "mode": ctx.env.get(MODE_ENV, "native")}
    if ctx.lang:
        params["lang"] = ctx.lang.split("-")[0]
    ctx.polite()
    data = _get(ctx, f"{API}?{urlencode(params)}", key)
    job = data.get("jobId")
    polls = 0
    while job and not data.get("content"):
        if polls >= POLLS:
            raise DoorError(f"Supadata job {job} did not finish after {POLLS} checks")
        ctx.sleep(max(ctx.pace, 5.0))
        polls += 1
        data = _get(ctx, f"{API}/{job}", key)
        if data.get("status") == "failed":
            raise DoorError(f"Supadata job failed: {data.get('error')}")
    content = data.get("content")
    if not isinstance(content, list) or not content:
        raise NoCaptions("Supadata returned no timed lines")
    lines = [Line(float(c.get("offset") or 0) / 1000, float(c.get("duration") or 0) / 1000,
                  " ".join(str(c.get("text") or "").split())) for c in content]
    lines = [ln for ln in lines if ln.text]
    return Transcript(lines=lines, door=NAME, language=data.get("lang"), generated=None,
                      track=f"supadata {params['mode']}", notes={"available_languages": data.get("availableLangs")})
