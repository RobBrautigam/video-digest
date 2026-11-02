"""The 0.2.0 additions: a word clock that is not late on automatic captions, quotes checked in actions and
extra sections, placeholder times refused anywhere in the prose, the transcript page, and thin caption
tracks that do not end the run. No test touches the network."""

from __future__ import annotations

import json

import pytest

from video_digest import cli, digest, html_page
from video_digest.models import DoorUnavailable, Line, Transcript
from video_digest.pipeline import take_doors

YT = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
LINES = [{"start": 0.0, "dur": 4.0, "text": "Welcome to the open movie project."},
         {"start": 60.0, "dur": 5.0, "text": "We render every frame with free tools, and it's fast."},
         {"start": 300.0, "dur": 5.0, "text": "Render every frame again at the end."}]
GOOD = {"title": "A film", "source": YT, "summary": "s",
        "chapters": [{"start": "0:00:00", "title": "Intro", "speakers": ["Host"], "summary": "Opens."},
                     {"start": "0:04:00", "title": "Ending", "speakers": ["Host"], "summary": "Closes."}],
        "points": [{"time": "0:01:00", "kind": "method", "text": "Free tools", "quote": "render every frame",
                    "speaker": "Host"}],
        "sections": [{"title": "What to borrow", "intro": "Ideas worth taking.",
                      "rows": [{"time": "0:01:10", "text": "Use free tools", "quote": "with free tools",
                                "speaker": "Host"}]}],
        "actions": [{"text": "Render twice", "time": "0:05:04", "quote": "Render every frame again"}]}


def _folder(tmp_path, d, lines=LINES, chapters=None):
    (tmp_path / "transcript.json").write_text(json.dumps({"title": "A film", "lines": lines}), encoding="utf-8")
    (tmp_path / "meta.json").write_text(json.dumps(
        {"duration": 310, "kind": "youtube", "id": "aqz-KE-bpKQ", "source": YT, "title": "A film",
         "door": "youtube-transcript-api", "track": "en (manual)", "words": 25, "lines": len(lines),
         "attempts": [{"door": "youtube-api", "ok": True, "kind": "ok"}], "tool": "video-digest test"}),
        encoding="utf-8")
    (tmp_path / "chapters.json").write_text(json.dumps(chapters if chapters is not None else
                                                       [{"start": 0, "end": 310, "title": "Whole"}]), encoding="utf-8")
    if d is not None:
        (tmp_path / "digest.json").write_text(json.dumps(d), encoding="utf-8")
    return tmp_path


# --- the word clock ---------------------------------------------------------------------------------

def test_word_clock_on_overlapping_automatic_captions_is_not_late():
    # an automatic caption line stays on screen 6 s, but the next line starts 2 s later
    rolling = [{"start": 10.0, "dur": 6.0, "text": "alpha beta gamma delta"},
               {"start": 12.0, "dur": 4.0, "text": "epsilon zeta"}]
    words = digest.word_index(rolling)
    found = digest.find_quote(words, "gamma delta", 11)
    assert found == pytest.approx(11.0, abs=0.01) and found < 12.0  # said before the next line began
    assert digest.word_index([{"start": 0.0, "dur": 4.0, "text": "one two"}])[1].time == 2.0  # last line: its dur


# --- quotes in actions and sections, and placeholder times anywhere ---------------------------------------

def test_action_and_section_quotes_are_checked_snapped_and_rendered(tmp_path):
    folder = _folder(tmp_path, GOOD)
    r = digest.check(folder)
    assert r.ok, r.problems
    assert [sorted(k for k in q if k in ("point", "action", "section", "row")) for q in r.quotes] == [
        ["point"], ["row", "section"], ["action"]]
    assert digest.snap_times(folder, r) == 2  # the row (0:01:10 to 0:01:0x) and the action moved
    d = json.loads((folder / "digest.json").read_text())
    assert d["sections"][0]["rows"][0]["time"].startswith("0:01:0") and d["actions"][0]["time"] == "0:05:00"
    meta = json.loads((folder / "meta.json").read_text())
    html = html_page.render_html(d, meta, digest.check(folder), LINES, "transcript.html")
    assert '<h2 id="s-1">What to borrow</h2>' in html and html.count("found at") == 3
    assert 'href="transcript.html"' in html and 'id="made"' in html
    md = digest.render_markdown(d, meta, digest.check(folder), LINES)
    assert "## What to borrow" in md and '> "Render every frame again"' in md and "## How this page was made" in md


def test_a_wrong_action_or_section_quote_is_refused(tmp_path):
    bad = json.loads(json.dumps(GOOD))
    bad["actions"].append({"text": "Paint", "time": "0:01:00", "quote": "we paint every frame"})
    bad["actions"].append({"text": "No time", "quote": "render every frame"})
    bad["sections"][0]["rows"][0]["quote"] = "with paid tools"
    text = " | ".join(digest.check(_folder(tmp_path, bad)).problems)
    assert "action 2: quote not found" in text and "action 3: a quote needs the time" in text
    assert "section 1 row 1: quote not found" in text


def test_a_placeholder_time_is_refused_anywhere_in_the_prose(tmp_path):
    bad = json.loads(json.dumps(GOOD))
    bad["summary"] = "The key moment is at 0:1x."
    bad["sections"][0]["intro"] = "See 1:00:1x for the demo."
    bad["actions"][0]["text"] = "Rewatch 2:3x"
    bad["chapters"][1]["title"] = "Ending at 4:?0"
    text = " | ".join(digest.check(_folder(tmp_path, bad)).problems)
    for where in ("summary: '0:1x'", "section 1 intro: '1:00:1x'", "action 1 text: '2:3x'",
                  "chapter 2 title: '4:?0'"):
        assert where in text, text
    assert digest.check(_folder(tmp_path, GOOD)).ok  # a real time in prose (none here) and a 16:9 ratio pass


# --- the transcript page ----------------------------------------------------------------------------

def test_paragraphs_end_at_a_sentence_after_thirty_seconds_or_at_forty_five():
    lines = [{"start": float(t), "dur": 2.0, "text": text} for t, text in
             [(0, "First thought."), (20, "Still going."), (31, "Ends here."), (40, "next part with no stop"),
              (60, "and on"), (86, "and on"), (90, "Done.")]]
    paras = digest.paragraphs(lines)
    assert [t for t, _ in paras] == [0.0, 40.0, 90.0]
    assert paras[0][1] == "First thought. Still going. Ends here."
    assert digest.reading_file(lines).startswith("[0:00:00] First thought.")


def test_transcript_page_has_every_chapter_its_words_and_time_links(tmp_path):
    folder = _folder(tmp_path, None, chapters=[{"start": 0, "end": 120, "title": "Opening <1>"},
                                               {"start": 120, "end": 310, "title": "Close"}])
    page = html_page.write_transcript_page(folder).read_text(encoding="utf-8")
    assert '<h2 id="c-1">Opening &lt;1&gt;</h2>' in page and '<h2 id="c-2">Close</h2>' in page
    assert page.count('<details class="fold">') == 2
    assert "https://www.youtube.com/watch?v=aqz-KE-bpKQ&amp;t=300s" in page  # the last line, in chapter 2
    assert "We render every frame" in page and "<script" not in page
    assert "Longest stretch with no words: 0:03:55" in page  # 65 s to 300 s
    (folder / "digest.json").write_text(json.dumps(GOOD), encoding="utf-8")
    page = html_page.write_transcript_page(folder).read_text(encoding="utf-8")
    assert '<h2 id="c-2">Ending</h2>' in page  # the digest's own chapters once it has them


def test_a_long_chapter_is_split_into_folds():
    paras = [(float(i), " ".join(["word"] * 1000)) for i in range(10)]
    folds = html_page._folds(paras, 10000)
    assert len(folds) == 3 and sum(len(f) for f in folds) == 10


def test_the_digest_command_writes_three_pages_and_page_rewrites_the_transcript(tmp_path, capsys):
    folder = _folder(tmp_path, GOOD)
    assert cli.main(["digest", str(folder)]) == 0
    for name in ("digest.md", "digest.html", "transcript.html", "quote_check.json"):
        assert (folder / name).exists(), name
    assert 'href="digest.html"' in (folder / "transcript.html").read_text(encoding="utf-8")
    assert 'href="transcript.html"' in (folder / "digest.html").read_text(encoding="utf-8")
    (folder / "transcript.html").unlink()
    assert cli.main(["page", str(folder)]) == 0 and (folder / "transcript.html").exists()
    assert cli.main(["page", str(tmp_path / "nothing-here")]) == 2


# --- thin caption tracks ----------------------------------------------------------------------------

def _thin() -> Transcript:
    return Transcript(lines=[Line(0.0, 170.0, "[Music]"), Line(170.0, 10.0, "♪ la la ♪")], door="ytdlp-subs")


def _speech() -> Transcript:
    return Transcript(lines=[Line(float(i), 1.0, "a real sentence was spoken here") for i in range(30)],
                      door="speech")


def test_a_thin_caption_track_does_not_end_the_run(make_ctx):
    ctx = make_ctx(YT)
    ctx.info = {"duration": 180}
    result, attempts = take_doors(ctx, ["ytdlp-subs", "speech"],
                                  doors={"ytdlp-subs": lambda c: _thin(), "speech": lambda c: _speech()},
                                  probe=lambda c: None)
    assert result.door == "speech"
    assert [a["kind"] for a in attempts if a["door"] != "probe"] == ["Thin", "ok"]


def test_a_thin_track_is_kept_with_a_note_when_no_later_door_hears_more(make_ctx):
    ctx = make_ctx(YT)
    ctx.info = {"duration": 180}

    def no_speech(c):
        raise DoorUnavailable("faster-whisper is not installed")

    result, attempts = take_doors(ctx, ["ytdlp-subs", "speech"],
                                  doors={"ytdlp-subs": lambda c: _thin(), "speech": no_speech},
                                  probe=lambda c: None)
    assert result.door == "ytdlp-subs" and "only 2 spoken word(s) in 0:03:00" in result.notes["thin_transcript"]
    assert any(a.get("kept") for a in attempts)


def test_a_short_clip_or_a_full_track_is_not_thin(make_ctx):
    ctx = make_ctx(YT)
    ctx.info = {"duration": 20}
    short = Transcript(lines=[Line(0.0, 20.0, "hi")], door="ytdlp-subs")
    result, _ = take_doors(ctx, ["ytdlp-subs", "speech"],
                           doors={"ytdlp-subs": lambda c: short, "speech": lambda c: pytest.fail("speech ran")},
                           probe=lambda c: None)
    assert result is short and "thin_transcript" not in result.notes
