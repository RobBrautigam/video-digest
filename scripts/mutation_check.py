"""Prove the tests guard the code: break each door and guard on purpose, and require its test to go red.

    python scripts/mutation_check.py

Each mutation replaces one exact snippet (it must occur exactly once), runs the one test that guards
it, and restores the file byte for byte whatever happens. A mutation whose test still passes is a
test that guards nothing, and the script exits 1.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "video_digest"
DOORS = "tests/test_doors.py"
PIPE = "tests/test_pipeline_digest.py"
PARSE = "tests/test_sources_parse.py"

MUTATIONS: list[tuple[str, str, str, str, str]] = [
    # (what it breaks, file, original snippet, mutated snippet, test that must go red)
    ("youtube door: never a translated track", "doors/youtube_api.py",
     "                if lang_matches(t.language_code, lang):", "                if True:",
     f"{DOORS}::test_youtube_pick_manual_first_never_a_translation"),
    ("youtube door: a block is a rate limit", "doors/youtube_api.py",
     'if name in _BLOCKED or "429" in text', "if False",
     f"{DOORS}::test_youtube_door_maps_refusals_and_missing_tracks"),
    ("youtube door: entities and line breaks cleaned", "doors/youtube_api.py",
     'clean_text(str(r["text"]))', 'str(r["text"])',
     f"{DOORS}::test_youtube_door_returns_timed_clean_lines"),
    ("yt-dlp: the -orig track over a translation", "ytdlp.py",
     'if auto_only_original and orig_keys and not key.endswith("-orig"):', "if False:",
     f"{DOORS}::test_caption_pick_takes_the_original_automatic_track_and_never_a_translation"),
    ("yt-dlp: the spoken language with no -orig key", "ytdlp.py",
     'if auto_only_original and not orig_keys and spoken and not lang_matches(base, spoken.split("-")[0]):',
     "if False:",
     f"{DOORS}::test_caption_pick_without_an_orig_key_matches_the_spoken_language"),
    ("yt-dlp: the original audio, not the dub", "ytdlp.py",
     "key=lambda f: (lang_pref(f), is_original(f), -abr(f))", "key=lambda f: (-abr(f),)",
     f"{DOORS}::test_audio_pick_avoids_the_dubbed_track"),
    ("yt-dlp: a bot check is a rate limit", "ytdlp.py",
     "if any(w.lower() in text.lower() for w in _BOT_WORDS):", "if False:",
     f"{DOORS}::test_ytdlp_errors_name_the_refusal"),
    ("yt-dlp subtitles door: parse by the file's format", "doors/ytdlp_subs.py",
     'entry.get("ext") or "vtt")', '"vtt")',
     f"{DOORS}::test_ytdlp_subs_door_fetches_the_picked_file"),
    ("page door: Wistia's three-letter codes", "doors/page_captions.py",
     "(len(code) == 3 and code[:2] == lang[:2].lower())", "False",
     f"{DOORS}::test_wistia_page_captions"),
    ("page door: Vimeo's relative track address", "doors/page_captions.py",
     'urljoin("https://vimeo.com", track["url"])', 'track["url"]',
     f"{DOORS}::test_vimeo_page_text_tracks"),
    ("speech door: the language is passed to the model", "doors/speech.py",
     'language=(lang.split("-")[0] if lang else None)', "language=None",
     f"{DOORS}::test_speech_door_reads_segments"),
    ("speech door: multilingual model when the language is unknown", "doors/speech.py",
     'return "base.en" if spoken.startswith("en") else "base"', 'return "base.en"',
     f"{DOORS}::test_speech_model_choice_and_override"),
    ("speech door: audio through the original-language pick", "doors/speech.py",
     'fmt = ytdlp.pick_audio_format(ctx.info.get("formats") or [])',
     'fmt = (ctx.info.get("formats") or [{}])[0].get("format_id")',
     f"{DOORS}::test_speech_audio_uses_the_original_language_pick"),
    ("paid door: off without --allow-paid", "doors/paid.py",
     "    if not ctx.allow_paid:", "    if False:",
     f"{DOORS}::test_paid_door_is_off_without_the_flag_and_the_key"),
    ("paid door: waits for a job", "doors/paid.py",
     "    while job and not data.get(\"content\"):", "    while False:",
     f"{DOORS}::test_paid_door_reads_timed_content_and_waits_for_a_job"),
    ("sidecar door: finds the caption file", "doors/sidecar.py",
     "    return cands[0] if cands else None", "    return None",
     f"{DOORS}::test_sidecar_caption_file_beside_a_local_video"),
    ("run: a refusal moves to the next door", "pipeline.py",
     "        except DoorError as e:\n            took", "        except NoCaptions as e:\n            took",
     f"{PIPE}::test_a_rate_limit_moves_to_the_next_door"),
    ("run: no captions on YouTube skips to speech", "pipeline.py",
     "                skip_captions = True", "                skip_captions = False",
     f"{PIPE}::test_no_captions_on_youtube_skips_to_speech"),
    ("run: the paid door is last", "pipeline.py",
     '"youtube": ["youtube-api", "ytdlp-subs", "speech", "paid"]',
     '"youtube": ["youtube-api", "ytdlp-subs", "paid", "speech"]',
     f"{PIPE}::test_door_order_free_first_and_the_paid_door_last"),
    ("pacing: waits between requests", "context.py",
     "            self.sleep(self.pace - gap)", "            pass",
     f"{PIPE}::test_polite_pacing_waits_between_requests"),
    ("source: a YouTube channel or playlist is refused", "sources.py",
     "    if host in YOUTUBE_HOSTS:\n        raise", "    if False:\n        raise",
     f"{PARSE}::test_youtube_address_that_is_not_one_video_is_refused"),
    ("captions: rolling automatic lines kept once", "parse.py",
     "            new = body[len(prev):].strip()", "            new = body",
     f"{PARSE}::test_vtt_rolling_automatic_captions_keep_each_word_once"),
    ("digest: a quote must be near its time", "digest.py",
     "        if near is not None and abs(t - near) > window:", "        if False:",
     f"{PIPE}::test_quote_found_near_its_time_and_refused_far_from_it"),
    ("digest: a placeholder time is refused", "digest.py",
     "            bad.append(m.group(0))", "            pass",
     f"{PIPE}::test_check_refuses_a_missing_quote_a_placeholder_time_and_disordered_chapters"),
    ("digest page: text is escaped", "html_page.py",
     "f\"<h1>{escape(d.get('title') or 'Untitled video')}</h1>\"", "f\"<h1>{d.get('title') or 'Untitled video'}</h1>\"",
     f"{PIPE}::test_check_passes_a_good_digest_and_renders_both_pages"),
    ("stills: a talk is not a screen demo", "stills.py",
     '"screen_demo": hits >= 5 and rate >= 0.5', '"screen_demo": True',
     f"{PIPE}::test_screen_demo_score_counts_pointing_phrases"),
    ("stills: every chapter gets a still", "stills.py",
     "            times.append(round(ch.start + min(5.0, max(0.0, (end - ch.start) / 2)), 2))", "            pass",
     f"{PIPE}::test_stills_choice_caps_and_gives_every_chapter_one"),
]


def run_test(nodeid: str) -> int:
    return subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "--color=no", "-p", "no:cacheprovider",
                           nodeid], cwd=ROOT, capture_output=True).returncode


def main() -> int:
    baseline = subprocess.run([sys.executable, "-m", "pytest", "-q", "--color=no", "-p", "no:cacheprovider"],
                              cwd=ROOT, capture_output=True, text=True)
    if baseline.returncode != 0:
        print("the suite is not green before mutating:\n" + baseline.stdout[-2000:])
        return 1
    survivors = 0
    for what, rel, old, new, nodeid in MUTATIONS:
        path = PKG / rel
        original = path.read_bytes()
        text = original.decode("utf-8")
        count = text.count(old)
        if count != 1:
            print(f"SETUP   {what}: snippet found {count} times in {rel}")
            survivors += 1
            continue
        try:
            path.write_bytes(text.replace(old, new).encode("utf-8"))
            code = run_test(nodeid)
        finally:
            path.write_bytes(original)
        verdict = "RED" if code != 0 else "SURVIVED"
        survivors += code == 0
        print(f"{verdict:8} {what}  [{nodeid.split('::')[-1]}]")
    after = run_test("tests")
    print(f"\n{len(MUTATIONS) - survivors} of {len(MUTATIONS)} mutations turned their test red; "
          f"suite after restore: {'green' if after == 0 else 'RED'}")
    return 0 if survivors == 0 and after == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
