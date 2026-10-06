"""Every door, with the network and the tools replaced: no test makes a real request."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from video_digest import ytdlp
from video_digest.doors import page_captions, paid, sidecar, speech, youtube_api, ytdlp_subs
from video_digest.models import DoorError, NoCaptions, RateLimited, Refused
from tests.conftest import FakeFetch

YT = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
RAW = [{"text": "Welcome to the open movie", "start": 0.5, "duration": 2.0},
       {"text": "made\nwith &gt;&gt; free tools", "start": 2.5, "duration": 2.5}]


class Track:
    def __init__(self, code, generated, raw=RAW, error=None):
        self.language_code, self.is_generated, self._raw, self._error = code, generated, raw, error
        self.fetched = 0

    def fetch(self):
        self.fetched += 1
        if self._error:
            raise self._error
        return SimpleNamespace(to_raw_data=lambda: list(self._raw))


def named(cls_name, message="boom"):
    return type(cls_name, (Exception,), {})(message)


# --- youtube-transcript-api ------------------------------------------------------------------------

def test_youtube_pick_manual_first_never_a_translation():
    gen_en, man_en, man_de = Track("en", True), Track("en-US", False), Track("de", False)
    assert youtube_api.pick([gen_en, man_en, man_de], "en") is man_en
    assert youtube_api.pick([gen_en, man_de], "en") is gen_en
    assert youtube_api.pick([man_de, Track("de", True)], "en") is None
    assert youtube_api.pick([Track("eng", True)], "en") is None  # a prefix must end at a subtag


def test_youtube_pick_with_no_language_follows_the_spoken_track():
    gen_es, man_en, man_es = Track("es", True), Track("en", False), Track("es-419", False)
    assert youtube_api.pick([man_en, man_es, gen_es], None) is man_es
    assert youtube_api.pick([man_en, gen_es], None) is gen_es


def test_youtube_door_returns_timed_clean_lines(make_ctx):
    ctx = make_ctx(YT)
    man = Track("en", False)
    seen = []
    t = youtube_api.run(ctx, lister=lambda vid: seen.append(vid) or [Track("en", True), man])
    assert seen == ["aqz-KE-bpKQ"] and man.fetched == 1
    assert [ln.to_dict() for ln in t.lines] == [
        {"start": 0.5, "dur": 2.0, "text": "Welcome to the open movie"},
        {"start": 2.5, "dur": 2.5, "text": "made with >> free tools"}]
    assert (t.door, t.language, t.generated) == ("youtube-transcript-api", "en", False)
    assert ctx.original_language == "en"


def test_youtube_door_maps_refusals_and_missing_tracks(make_ctx):
    ctx = make_ctx(YT)
    with pytest.raises(RateLimited, match="yt-dlp"):
        youtube_api.run(ctx, lister=lambda vid: (_ for _ in ()).throw(named("RequestBlocked")))
    with pytest.raises(RateLimited):
        youtube_api.run(ctx, lister=lambda vid: [Track("en", True, error=named("YouTubeRequestFailed", "429 Too Many Requests"))])
    with pytest.raises(NoCaptions, match="speech"):
        youtube_api.run(ctx, lister=lambda vid: (_ for _ in ()).throw(named("TranscriptsDisabled")))
    with pytest.raises(NoCaptions, match="de"):
        youtube_api.run(make_ctx(YT, lang="en"), lister=lambda vid: [Track("de", True)])
    other = youtube_api.map_error(named("VideoUnavailable"))
    assert type(other) is DoorError


def test_youtube_door_refuses_other_sources(make_ctx):
    with pytest.raises(Refused):
        youtube_api.run(make_ctx("https://vimeo.com/76979871"), lister=lambda vid: [])


# --- yt-dlp: captions, formats, errors -------------------------------------------------------------

YT_INFO = {
    "id": "aqz-KE-bpKQ", "title": "A film", "duration": 600, "language": "en",
    "subtitles": {},
    "automatic_captions": {
        "en-orig": [{"ext": "json3", "url": "https://t.example/en-orig.json3"}],
        "en": [{"ext": "json3", "url": "https://t.example/en.json3"}],
        "de": [{"ext": "json3", "url": "https://t.example/de-translated.json3"}],
    },
}


def test_caption_pick_takes_the_original_automatic_track_and_never_a_translation():
    assert ytdlp.pick_caption(YT_INFO, None, None)[:1] == ("en-orig",)
    assert ytdlp.pick_caption(YT_INFO, "en", None)[0] == "en-orig"
    assert ytdlp.pick_caption(YT_INFO, "de", None) is None  # 'de' is a machine translation
    manual = {**YT_INFO, "subtitles": {"en-GB": [{"ext": "vtt", "url": "https://t.example/m.vtt"}]}}
    key, entry, generated = ytdlp.pick_caption(manual, "en", None)
    assert (key, generated, entry["ext"]) == ("en-GB", False, "vtt")


def test_caption_pick_without_an_orig_key_matches_the_spoken_language():
    info = {"language": "en", "subtitles": {},
            "automatic_captions": {"de": [{"ext": "vtt", "url": "https://t.example/de.vtt"}],
                                   "en": [{"ext": "vtt", "url": "https://t.example/en.vtt"}]}}
    assert ytdlp.pick_caption(info, None, None)[0] == "en"
    assert ytdlp.pick_caption(info, "de", None) is None


def test_ytdlp_subs_door_fetches_the_picked_file(make_ctx):
    ctx = make_ctx(YT)
    ctx.info = YT_INFO
    body = json.dumps({"events": [{"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "hello world"}]}]})
    got = []
    t = ytdlp_subs.run(ctx, fetch=lambda c, url: got.append(url) or body.encode())
    assert got == ["https://t.example/en-orig.json3"]
    assert (t.lines[0].start, t.lines[0].text, t.language, t.generated) == (1.0, "hello world", "en", True)


def test_ytdlp_subs_door_without_a_probe_or_a_track(make_ctx):
    ctx = make_ctx(YT)
    with pytest.raises(DoorError, match="probe"):
        ytdlp_subs.run(ctx, fetch=lambda c, u: b"")
    ctx.info = {"subtitles": {}, "automatic_captions": {}}
    with pytest.raises(NoCaptions):
        ytdlp_subs.run(ctx, fetch=lambda c, u: b"")


def test_audio_pick_avoids_the_dubbed_track():
    formats = [
        {"format_id": "dub-de", "vcodec": "none", "acodec": "mp4a", "abr": 30, "language_preference": -1,
         "format_note": "German (dubbed), low"},
        {"format_id": "139-orig", "vcodec": "none", "acodec": "mp4a", "abr": 48, "language_preference": 10,
         "format_note": "English original (default), low"},
        {"format_id": "140-orig", "vcodec": "none", "acodec": "mp4a", "abr": 129, "language_preference": 10,
         "format_note": "English original (default), medium"},
        {"format_id": "sb0", "vcodec": "none", "acodec": "none", "format_note": "storyboard"},
    ]
    assert ytdlp.pick_audio_format(formats) == "139-orig"
    combined = [{"format_id": "hls-720", "vcodec": "avc1", "acodec": "mp4a", "height": 720},
                {"format_id": "hls-360", "vcodec": "avc1", "acodec": "mp4a", "height": 360}]
    assert ytdlp.pick_audio_format(combined) == "hls-360"
    assert ytdlp.pick_audio_format([{"format_id": "v", "vcodec": "avc1", "acodec": "none", "height": 360}]) is None


def test_stills_format_is_the_smallest_picture_at_360_or_over():
    formats = [{"format_id": "a", "vcodec": "none", "acodec": "mp4a"},
               {"format_id": "240", "vcodec": "avc1", "height": 240},
               {"format_id": "360", "vcodec": "avc1", "acodec": "none", "height": 360},
               {"format_id": "1080", "vcodec": "avc1", "height": 1080}]
    assert ytdlp.pick_stills_format(formats) == "360"


def test_js_runtimes_enables_every_runtime_on_path():
    assert ytdlp.js_runtimes(lambda n: "/bin/" + n if n == "node" else None) == {"node": {}}
    assert ytdlp.js_runtimes(lambda n: None) == {"deno": {}}  # yt-dlp's own default
    assert "js_runtimes" in ytdlp.base_opts(SimpleNamespace(pace=1.0))


def test_ytdlp_errors_name_the_refusal():
    forbidden = ytdlp.map_error(Exception("ERROR: unable to download video data: HTTP Error 403: Forbidden"), "x")
    assert type(forbidden) is DoorError and "yt-dlp-ejs" in str(forbidden)
    assert isinstance(ytdlp.map_error(Exception("ERROR: HTTP Error 429: Too Many Requests"), "speech"), RateLimited)
    assert isinstance(ytdlp.map_error(Exception("Sign in to confirm you're not a bot"), "speech"), RateLimited)
    other = ytdlp.map_error(Exception("ERROR: Unsupported URL"), "speech")
    assert type(other) is DoorError and "speech" in str(other)


# --- the page's own captions (Wistia, Vimeo) -------------------------------------------------------

VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello from the player\n"


def test_wistia_page_captions(make_ctx):
    fetch = FakeFetch({
        "https://fast.wistia.com/embed/medias/a1b2c3d4e5.json": json.dumps(
            {"media": {"captions": [{"language": "spa"}, {"language": "eng"}]}}),
        "https://fast.wistia.com/embed/captions/a1b2c3d4e5.vtt?language=eng": VTT,
    })
    ctx = make_ctx("wistia:a1b2c3d4e5", lang="en", fetch=fetch)
    t = page_captions.run(ctx)
    assert t.lines[0].text == "Hello from the player" and t.language == "eng"
    with pytest.raises(NoCaptions):
        page_captions.run(make_ctx("wistia:a1b2c3d4e5", lang="fr", fetch=fetch))


def test_vimeo_page_text_tracks(make_ctx):
    fetch = FakeFetch({
        "https://player.vimeo.com/video/76979871/config": json.dumps(
            {"request": {"text_tracks": [{"lang": "en", "url": "/texttrack/1.vtt?token=x", "kind": "captions"}]}}),
        "https://vimeo.com/texttrack/1.vtt": VTT,
    })
    t = page_captions.run(make_ctx("https://vimeo.com/76979871", fetch=fetch))
    assert t.lines[0].start == 1.0 and fetch.calls[-1] == "https://vimeo.com/texttrack/1.vtt?token=x"
    assert t.notes["page_meta"] == {}
    empty = FakeFetch({"https://player.vimeo.com/video/76979871/config": json.dumps({"request": {}})})
    with pytest.raises(NoCaptions):
        page_captions.run(make_ctx("https://vimeo.com/76979871", fetch=empty))
    with pytest.raises(Refused):
        page_captions.run(make_ctx(YT))


def test_page_pick_with_no_language_asked_is_not_the_default_translation(make_ctx):
    tracks = [{"lang": "de", "url": "/t/de.vtt", "kind": "subtitles", "default": True},
              {"lang": "es", "url": "/t/es.vtt", "kind": "subtitles"},
              {"lang": "en", "url": "/t/en.vtt", "kind": "subtitles"}]
    fetch = FakeFetch({
        "https://player.vimeo.com/video/76979871/config": json.dumps(
            {"video": {"title": "Player", "duration": 62, "owner": {"name": "Owner"}},
             "request": {"text_tracks": tracks}}),
        "https://vimeo.com/t/en.vtt": VTT,
    })
    t = page_captions.run(make_ctx("https://vimeo.com/76979871", fetch=fetch))
    assert t.language == "en" and t.notes["language_guessed"] is True
    assert t.notes["page_meta"] == {"title": "Player", "duration": 62, "uploader": "Owner"}
    captions_kind = tracks + [{"lang": "fr", "url": "/t/fr.vtt", "kind": "captions"}]
    assert page_captions._pick(captions_kind, None, "lang")["lang"] == "fr"
    assert page_captions._pick(tracks, None, "lang", original="es")["lang"] == "es"


# --- speech ------------------------------------------------------------------------------------------

class FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, language=None, **kw):
        self.calls.append(language)
        segs = [SimpleNamespace(start=0.0, end=2.5, text=" Hello  there "), SimpleNamespace(start=2.5, end=4.0, text=" ")]
        return iter(segs), SimpleNamespace(language="en", language_probability=0.99)


def test_speech_door_reads_segments(make_ctx, tmp_path):
    import numpy as np

    ctx = make_ctx(YT)
    ctx.original_language = "en"
    model = FakeModel()
    t = speech.run(ctx, model=model, decoder=lambda p: np.zeros(16000 * 4, dtype=np.float32),
                   fetch_audio=lambda c: tmp_path / "audio.m4a")
    assert [ln.text for ln in t.lines] == ["Hello there"] and t.generated is True
    assert model.calls == ["en"] and t.notes["audio_seconds"] == 4.0


def test_speech_model_choice_and_override(make_ctx):
    ctx = make_ctx(YT)
    assert speech.model_name(ctx) == "base"  # spoken language unknown: the multilingual model
    ctx.original_language = "en-US"
    assert speech.model_name(ctx) == "base.en"
    ctx.env = {speech.MODEL_ENV: "small"}
    assert speech.model_name(ctx) == "small"


def test_speech_audio_uses_the_original_language_pick(make_ctx, tmp_path):
    ctx = make_ctx(YT)
    ctx.info = {"formats": [
        {"format_id": "dub", "vcodec": "none", "acodec": "opus", "abr": 20, "language_preference": -1},
        {"format_id": "orig", "vcodec": "none", "acodec": "opus", "abr": 50, "language_preference": 10}]}
    picked = []
    speech.audio_file(ctx, downloader=lambda c, fmt, stem: picked.append(fmt) or tmp_path / "a")
    assert picked == ["orig"]


# --- paid -------------------------------------------------------------------------------------------

def test_paid_door_is_off_without_the_flag_and_the_key(make_ctx):
    fetch = FakeFetch({})
    with pytest.raises(Refused, match="allow-paid"):
        paid.run(make_ctx(YT, env={paid.KEY_ENV: "k"}, fetch=fetch))
    with pytest.raises(Refused, match=paid.KEY_ENV):
        paid.run(make_ctx(YT, allow_paid=True, fetch=fetch))
    assert fetch.calls == []


def test_paid_door_reads_timed_content_and_waits_for_a_job(make_ctx):
    fetch = FakeFetch({
        "https://api.supadata.ai/v1/transcript?": json.dumps({"jobId": "j1"}),
        "https://api.supadata.ai/v1/transcript/j1": json.dumps(
            {"status": "completed", "lang": "en", "content": [{"text": "hi there", "offset": 8150, "duration": 1200}]}),
    })
    ctx = make_ctx(YT, allow_paid=True, env={paid.KEY_ENV: "k"}, fetch=fetch)
    t = paid.run(ctx)
    assert (t.lines[0].start, t.lines[0].dur, t.lines[0].text) == (8.15, 1.2, "hi there")
    assert "mode=native" in fetch.calls[0] and "text=false" in fetch.calls[0]


# --- sidecar ----------------------------------------------------------------------------------------

def test_sidecar_caption_file_beside_a_local_video(make_ctx, tmp_path):
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"x")
    with pytest.raises(NoCaptions):
        sidecar.run(make_ctx(str(video)))
    (tmp_path / "talk.en.vtt").write_text(VTT, encoding="utf-8")
    t = sidecar.run(make_ctx(str(video)))
    assert t.lines[0].text == "Hello from the player" and t.track == "talk.en.vtt"
