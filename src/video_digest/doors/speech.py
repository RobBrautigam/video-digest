"""The speech door: faster-whisper on this machine, reading the original-language audio track."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from video_digest import ytdlp
from video_digest.context import RunContext
from video_digest.models import DoorError, DoorUnavailable, Line, Transcript

NAME = "faster-whisper"

MODEL_ENV = "VIDEO_DIGEST_WHISPER_MODEL"  # a model name (base.en, small) or a local model folder
MODEL_DIR_ENV = "VIDEO_DIGEST_MODEL_DIR"  # where models are downloaded and cached
DEVICE_ENV = "VIDEO_DIGEST_WHISPER_DEVICE"  # cpu (default) or cuda
SAMPLE_RATE = 16000


def model_name(ctx: RunContext) -> str:
    """The English-only base model when the speech is known to be English; the multilingual base otherwise."""
    if ctx.env.get(MODEL_ENV):
        return ctx.env[MODEL_ENV]
    spoken = (ctx.lang or ctx.original_language or "").lower()
    return "base.en" if spoken.startswith("en") else "base"


def decode(path: Path, run: Callable[..., Any] = subprocess.run) -> Any:
    """ffmpeg to 16 kHz mono float32, handed to the model as an array (no PyAV decode on the way)."""
    if not shutil.which("ffmpeg"):
        raise DoorUnavailable("ffmpeg is not on PATH; install it to use the speech door")
    import numpy as np

    p = run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1",
             "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"], capture_output=True, check=False)
    if p.returncode != 0 or not p.stdout:
        raise DoorError(f"ffmpeg could not decode the audio: {p.stderr.decode('utf-8', 'replace')[-300:]}")
    return np.frombuffer(p.stdout, dtype=np.float32)


def load_model(ctx: RunContext) -> Any:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise DoorUnavailable("faster-whisper is not installed (pip install 'video-digest[speech]')") from e
    name = model_name(ctx)
    device = ctx.env.get(DEVICE_ENV, "cpu")
    kwargs: dict[str, Any] = {"device": device, "compute_type": "int8" if device == "cpu" else "float16"}
    if ctx.env.get(MODEL_DIR_ENV):
        kwargs["download_root"] = ctx.env[MODEL_DIR_ENV]
    ctx.log(f"speech: loading {name} on {device} (downloads once on first use)")
    return WhisperModel(name, **kwargs)


def audio_file(ctx: RunContext, downloader: Callable[..., Path] = ytdlp.download) -> Path:
    if ctx.source.kind == "file":
        return Path(ctx.source.ref)
    if ctx.info is None:
        raise DoorError("no metadata to choose an audio track from (the probe failed)")
    fmt = ytdlp.pick_audio_format(ctx.info.get("formats") or [])
    if not fmt:
        raise DoorError("the site offers no format with sound")
    ctx.log(f"speech: downloading audio format {fmt}")
    return downloader(ctx, fmt, "audio")


def run(ctx: RunContext, model: Any = None, decoder: Callable[[Path], Any] = decode,
        fetch_audio: Callable[[RunContext], Path] = audio_file) -> Transcript:
    path = fetch_audio(ctx)
    audio = decoder(path)
    model = model or load_model(ctx)
    name = model_name(ctx)
    lang = ctx.lang or ctx.original_language
    if name.endswith(".en"):
        lang = "en"
    segments, info = model.transcribe(audio, language=(lang.split("-")[0] if lang else None),
                                      beam_size=5, vad_filter=True)
    lines = [Line(float(s.start), float(s.end) - float(s.start), " ".join(s.text.split()))
             for s in segments if s.text.strip()]
    if not lines:
        raise DoorError("the speech model heard no words")
    detected = getattr(info, "language", None)
    return Transcript(lines=lines, door=NAME, language=detected or lang, generated=True, track=name,
                      notes={"audio_seconds": round(len(audio) / SAMPLE_RATE, 1),
                             "language_probability": getattr(info, "language_probability", None)})
