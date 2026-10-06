from __future__ import annotations

import json
import time

import pytest

from video_digest import digest, html_page, stills
from video_digest.context import RunContext
from video_digest.models import Chapter, DoorError, Line, NoCaptions, RateLimited, Transcript
from video_digest.pipeline import AllDoorsFailed, door_order, take_doors
from video_digest.sources import detect

YT = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"


def _t(door: str) -> Transcript:
    return Transcript(lines=[Line(0, 1, "words here")], door=door)


def test_door_order_free_first_and_the_paid_door_last():
    assert door_order(detect(YT), None) == ["youtube-api", "ytdlp-subs", "speech", "paid"]
    assert door_order(detect("https://vimeo.com/76979871"), None)[-1] == "paid"
    assert door_order(detect(YT), ["speech", "page"]) == ["speech"]  # page does not apply to YouTube
    with pytest.raises(ValueError, match="unknown"):
        door_order(detect(YT), ["nope"])


def test_a_rate_limit_moves_to_the_next_door(make_ctx):
    calls = []

    def limited(ctx):
        calls.append("youtube-api")
        raise RateLimited("429")

    def subs(ctx):
        calls.append("ytdlp-subs")
        return _t("ytdlp-subs")

    probes = []
    result, attempts = take_doors(make_ctx(YT), ["youtube-api", "ytdlp-subs", "speech"],
                                  doors={"youtube-api": limited, "ytdlp-subs": subs},
                                  probe=lambda c: probes.append(1))
    assert result.door == "ytdlp-subs" and calls == ["youtube-api", "ytdlp-subs"] and probes == [1]
    assert attempts[0]["kind"] == "RateLimited" and attempts[-1]["ok"] is True


def test_no_captions_on_youtube_skips_to_speech(make_ctx):
    def none(ctx):
        raise NoCaptions("no track")

    def never(ctx):
        raise AssertionError("a second caption door ran for a video with no captions")

    result, attempts = take_doors(make_ctx(YT), ["youtube-api", "ytdlp-subs", "speech"],
                                  doors={"youtube-api": none, "ytdlp-subs": never, "speech": lambda c: _t("speech")},
                                  probe=lambda c: None)
    assert result.door == "speech"
    assert [a["kind"] for a in attempts if a["door"] != "probe"] == ["NoCaptions", "Skipped", "ok"]


def test_every_door_failing_names_each_one_and_the_next_step(make_ctx):
    def fail(msg):
        def door(ctx):
            raise DoorError(msg)
        return door

    result, attempts = take_doors(make_ctx(YT), ["youtube-api", "speech"],
                                  doors={"youtube-api": fail("blocked"),
                                         "speech": fail("faster-whisper is not installed (pip ...)")},
                                  probe=lambda c: None)
    assert result is None
    msg = str(AllDoorsFailed(attempts))
    assert "youtube-api: blocked" in msg and "video-digest[speech]" in msg


def test_a_failed_probe_is_tried_once_and_the_player_supplies_the_title(tmp_path, monkeypatch):
    from video_digest import pipeline

    probes = []

    def probe(ctx):
        probes.append(1)
        raise DoorError("the web client only works when logged in")

    def page(ctx):
        return Transcript(lines=[Line(5, 2, "hello")], door="page captions", language="en",
                          notes={"page_meta": {"title": "Player video", "duration": 62}})

    monkeypatch.setattr(pipeline, "_probe", probe)
    monkeypatch.setitem(pipeline.DOORS, "page", page)
    folder = pipeline.run("https://vimeo.com/76979871",
                          pipeline.Options(out=tmp_path, doors=["ytdlp-subs", "page"], stills="never",
                                           log=lambda m: None, env={}))
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert probes == [1]
    assert (meta["title"], meta["duration"], meta["door"]) == ("Player video", 62, "page captions")
    assert "## Transcript" in (folder / "transcript.md").read_text(encoding="utf-8")


def test_polite_pacing_waits_between_requests(tmp_path):
    slept = []
    ctx = RunContext(source=detect(YT), workdir=tmp_path, pace=2.0, sleep=slept.append, log=lambda m: None)
    ctx.polite()
    ctx.polite()
    assert len(slept) == 1 and 0 < slept[0] <= 2.0
    ctx._last_request = time.monotonic() - 5
    ctx.polite()
    assert len(slept) == 1


# --- stills -----------------------------------------------------------------------------------------

def test_screen_demo_score_counts_pointing_phrases():
    talk = [Line(i * 10.0, 10.0, "we talked about the market and the team") for i in range(60)]
    demo = [Line(i * 10.0, 10.0, "click on Settings, you can see it right here") for i in range(60)]
    assert stills.screen_demo_score(talk)["screen_demo"] is False
    s = stills.screen_demo_score(demo)
    assert s["screen_demo"] is True and s["pointing_phrases"] >= 60


def test_stills_choice_caps_and_gives_every_chapter_one():
    times = [float(t) for t in range(0, 100)]
    chapters = [Chapter(0, 100, "One"), Chapter(100, 200, "Two")]
    chosen = stills.choose(times, chapters, 200, cap=10)
    assert len([t for t in chosen if t < 100]) == 10
    assert any(100 <= t < 200 for t in chosen)  # chapter two had no scene change
    assert stills.choose([3.2, 3.27, 3.9, 9.0], [], 20, cap=10) == [3.2, 9.0]  # one still per transition


# --- digest -----------------------------------------------------------------------------------------

LINES = [{"start": 0.0, "dur": 4.0, "text": "Welcome to the open movie project."},
         {"start": 60.0, "dur": 5.0, "text": "We render every frame with free tools, and it's fast."},
         {"start": 300.0, "dur": 5.0, "text": "Render every frame again at the end."}]


def test_quote_found_near_its_time_and_refused_far_from_it():
    words = digest.word_index(LINES)
    assert digest.find_quote(words, "render every frame", 62) == pytest.approx(61.0, abs=1.5)
    assert digest.find_quote(words, "render every frame", 290) == pytest.approx(301.0, abs=1.5)
    assert digest.find_quote(words, "render every frame", 180, window=60) is None
    assert digest.find_quote(words, "free tools, and it's FAST", 60) is not None
    assert digest.find_quote(words, "We render ... it's fast", 60) is not None
    assert digest.find_quote(words, "we paint every frame", 60) is None


def _folder(tmp_path, d):
    (tmp_path / "transcript.json").write_text(json.dumps({"lines": LINES}), encoding="utf-8")
    (tmp_path / "meta.json").write_text(json.dumps({"duration": 310, "kind": "youtube", "id": "aqz-KE-bpKQ",
                                                    "source": YT, "door": "youtube-transcript-api", "words": 25}),
                                        encoding="utf-8")
    (tmp_path / "chapters.json").write_text(json.dumps([{"start": 0, "end": 310, "title": "Intro"}]), encoding="utf-8")
    if d is not None:
        (tmp_path / "digest.json").write_text(json.dumps(d), encoding="utf-8")
    return tmp_path


GOOD = {"title": "A film <b>", "source": YT, "summary": "s",
        "chapters": [{"start": "0:00:00", "title": "Intro", "speakers": ["Host"], "summary": "Opens."}],
        "points": [{"time": "0:01:00", "kind": "method", "text": "Free tools", "quote": "render every frame",
                    "speaker": "Host"}],
        "actions": [{"text": "Try it", "time": "0:05:00"}]}


def test_check_passes_a_good_digest_and_renders_both_pages(tmp_path):
    folder = _folder(tmp_path, GOOD)
    r = digest.check(folder)
    assert r.ok and r.quotes[0]["found_at"] == "0:01:00"
    html = html_page.render_html(GOOD, json.loads((folder / "meta.json").read_text()), r)
    assert "<h1>A film &lt;b&gt;</h1>" in html and "found at 0:01:00" in html
    assert "https://www.youtube.com/watch?v=aqz-KE-bpKQ&amp;t=60s" in html
    assert "<script" not in html and "http-equiv" not in html
    md = digest.render_markdown(GOOD, json.loads((folder / "meta.json").read_text()), r)
    assert "## Actions for you" in md and '> "render every frame"' in md


def test_check_refuses_a_missing_quote_a_placeholder_time_and_disordered_chapters(tmp_path):
    bad = json.loads(json.dumps(GOOD))
    bad["points"][0]["quote"] = "words nobody said"
    bad["points"].append({"time": "0:04:1x", "kind": "claim", "text": "see 1:00:1x"})
    bad["chapters"].append({"start": "0:00:00", "title": "Again", "speakers": [], "summary": ""})
    r = digest.check(_folder(tmp_path, bad))
    text = " | ".join(r.problems)
    assert not r.ok
    assert "quote not found" in text and "'0:04:1x' is not a time" in text
    assert "'1:00:1x' is not a time" in text and "not after the chapter before it" in text


def test_snap_moves_each_point_to_where_its_quote_starts(tmp_path):
    d = json.loads(json.dumps(GOOD))
    d["points"][0]["time"] = "0:01:20"
    folder = _folder(tmp_path, d)
    assert digest.snap_times(folder, digest.check(folder)) == 1
    assert json.loads((folder / "digest.json").read_text())["points"][0]["time"] == "0:01:00"


def test_init_writes_a_skeleton_and_a_reading_file(tmp_path):
    folder = _folder(tmp_path, None)
    digest.init(folder)
    d = json.loads((folder / "digest.json").read_text())
    assert d["chapters"][0] == {"start": "0:00:00", "title": "Intro", "speakers": [], "summary": ""}
    assert (folder / "reading.md").read_text().startswith("[0:00:00] Welcome")
    with pytest.raises(FileExistsError):
        digest.init(folder)
