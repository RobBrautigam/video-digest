from __future__ import annotations

from pathlib import Path

import pytest

from video_digest.context import RunContext
from video_digest.sources import detect


class FakeFetch:
    """Stands in for the network: a dict of URL prefix to bytes (or an exception to raise)."""

    def __init__(self, routes: dict[str, object]):
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict | None = None, timeout: float = 30.0) -> bytes:
        self.calls.append(url)
        for prefix, answer in self.routes.items():
            if url.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return answer if isinstance(answer, bytes) else str(answer).encode("utf-8")
        raise AssertionError(f"unexpected request: {url}")


@pytest.fixture
def make_ctx(tmp_path: Path):
    def make(ref: str, **kw) -> RunContext:
        ctx = RunContext(source=detect(ref), workdir=tmp_path, env=kw.pop("env", {}), sleep=lambda s: None,
                         log=lambda m: None, pace=kw.pop("pace", 0.0), **kw)
        return ctx
    return make
