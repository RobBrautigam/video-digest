from __future__ import annotations

import pytest

from video_digest.parse import parse_json3, parse_srt, parse_stamp, parse_vtt, stamp
from video_digest.sources import detect


@pytest.mark.parametrize("url,kind,vid", [
    ("https://www.youtube.com/watch?v=aqz-KE-bpKQ&t=10s", "youtube", "aqz-KE-bpKQ"),
    ("https://youtu.be/aqz-KE-bpKQ?si=abc", "youtube", "aqz-KE-bpKQ"),
    ("https://www.youtube.com/shorts/aqz-KE-bpKQ", "youtube", "aqz-KE-bpKQ"),
    ("https://www.youtube.com/live/aqz-KE-bpKQ", "youtube", "aqz-KE-bpKQ"),
    ("https://vimeo.com/76979871", "vimeo", "76979871"),
    ("https://player.vimeo.com/video/76979871?h=abc", "vimeo", "76979871"),
    ("https://fast.wistia.net/embed/iframe/a1b2c3d4e5", "wistia", "a1b2c3d4e5"),
    ("https://home.wistia.com/medias/a1b2c3d4e5", "wistia", "a1b2c3d4e5"),
    ("wistia:a1b2c3d4e5", "wistia", "a1b2c3d4e5"),
    ("https://example.org/talks/opening", "site", "example.org-opening"),
])
def test_detect_kinds(url, kind, vid):
    s = detect(url)
    assert (s.kind, s.id) == (kind, vid)


@pytest.mark.parametrize("url", ["https://www.youtube.com/@somechannel",
                                 "https://www.youtube.com/playlist?list=PLabc",
                                 "https://www.youtube.com/results?search_query=x"])
def test_youtube_address_that_is_not_one_video_is_refused(url):
    with pytest.raises(ValueError, match="not one video"):
        detect(url)


def test_a_local_file_and_a_missing_path(tmp_path):
    f = tmp_path / "clip one.mp4"
    f.write_bytes(b"x")
    s = detect(str(f))
    assert s.kind == "file" and s.id == "clip one" and s.folder_name.startswith("file-clip-one-")
    with pytest.raises(ValueError, match="not a file"):
        detect(str(tmp_path / "missing.mp4"))


def test_two_videos_never_share_an_output_folder(tmp_path):
    one, two = detect("https://example.com/player?id=1"), detect("https://example.com/player?id=2")
    assert one.id == two.id == "example.com-player"  # the readable part
    assert one.folder_name != two.folder_name
    assert detect("https://example.com/player?id=1").folder_name == one.folder_name  # stable across runs
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "talk.mp4").write_bytes(b"x")
    (tmp_path / "b" / "talk.mp4").write_bytes(b"x")
    fa, fb = detect(str(tmp_path / "a" / "talk.mp4")), detect(str(tmp_path / "b" / "talk.mp4"))
    assert fa.id == fb.id == "talk" and fa.folder_name != fb.folder_name
    assert fa.folder_name.startswith("file-talk-")
    assert detect("https://vimeo.com/76979871").folder_name == "vimeo-76979871"  # a site id is unique already


def test_json3_keeps_each_event_time_and_drops_empty_events():
    payload = {"events": [
        {"tStartMs": 0, "dDurationMs": 134840},
        {"tStartMs": 160, "dDurationMs": 4360, "segs": [{"utf8": "If"}, {"utf8": " you"}, {"utf8": " use"}]},
        {"tStartMs": 2270, "dDurationMs": 2090, "aAppend": 1, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 2280, "dDurationMs": 3960, "segs": [{"utf8": "it &amp; this"}]},
    ]}
    lines = [ln.to_dict() for ln in parse_json3(payload)]
    assert lines == [{"start": 0.16, "dur": 4.36, "text": "If you use"},
                     {"start": 2.28, "dur": 3.96, "text": "it & this"}]


VTT_ROLLING = """WEBVTT
Kind: captions

00:00:00.160 --> 00:00:02.270 align:start position:0%
the<00:00:00.400><c> first</c><00:00:00.800><c> line</c>

00:00:02.270 --> 00:00:02.280 align:start position:0%
the first line

00:00:02.280 --> 00:00:05.000 align:start position:0%
the first line
and<c> the</c><c> second</c>
"""


def test_vtt_rolling_automatic_captions_keep_each_word_once():
    lines = parse_vtt(VTT_ROLLING)
    assert [ln.text for ln in lines] == ["the first line", "and the second"]
    assert lines[1].start == 2.28


def test_srt_and_short_stamps():
    srt = "1\n00:00:01,000 --> 00:00:03,500\nHello there\n\n2\n00:00:04,000 --> 00:00:06,000\n<i>General</i> Kenobi\n"
    assert [(ln.start, ln.text) for ln in parse_srt(srt)] == [(1.0, "Hello there"), (4.0, "General Kenobi")]
    assert [ln.start for ln in parse_vtt("WEBVTT\n\n01:05.500 --> 01:07.000\nshort stamp\n")] == [65.5]


def test_stamps_round_trip_and_placeholders_are_refused():
    assert stamp(3725.9) == "1:02:05"
    assert parse_stamp("1:02:05") == 3725 and parse_stamp("2:05") == 125 and parse_stamp(7) == 7.0
    for bad in ("1:00:1x", "1:2:3", "12", "0:61"):
        with pytest.raises(ValueError):
            parse_stamp(bad)
