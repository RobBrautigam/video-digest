---
name: video-digest
description: Use when the user shares a video link or file (YouTube, Vimeo, Wistia, any site yt-dlp reads, a local recording) and asks for a transcript, a summary, the methods or claims in it, "digest this video", "what does this course teach", or quotes with times. Free caption doors first, local speech to text when there are none, every quote checked against the transcript by script.
---

# video-digest

Turn one video into a timed transcript and a chaptered digest: chapters with times and speakers,
every method or claim with its time and the exact words, an optional "actions for you" section from
the user's own context, as Markdown and a self-contained HTML page.

The words come from free doors first (YouTube's caption track, yt-dlp's subtitles, the player's own
caption file, then speech to text on this machine). The digest is written by you, in this session; the
tool never calls a language model. Its job is to make sure every quote you write is really in the
transcript, at the time you say, before anyone reads it.

## Install

1. `pip install "video-digest[speech] @ git+https://github.com/RobBrautigam/video-digest"` (or `pip install ".[speech]"` from a clone).
2. ffmpeg on PATH. For YouTube media downloads (only needed for speech to text and stills), a JavaScript runtime on PATH (deno or Node.js); yt-dlp uses it to answer YouTube's challenge.
3. Copy this folder to `~/.claude/skills/video-digest/` (every project) or `<project>/.claude/skills/video-digest/` (one project).
4. Check: `video-digest --version`.

## The method

Steps 2, 5 and 7 carry the quality: exact times, every quote matched by script, and a person (or a
fresh agent) reading speakers and context, which no script can check.

1. **Get the timed transcript.** `video-digest <url or file> -o digests`. Read the last line: the door
   used, words, chapters. Open `meta.json` when anything looks off:
   - `attempts` lists every door tried, why each failed and how long it took;
   - `transcript_notes.language_guessed` means the player did not say which track is spoken: rerun
     with `--lang <code>` if the guess is wrong;
   - for a screen demo, pass `--stills` (stills by chapter in `stills/`), or let the tool decide: it
     takes stills when the speaker keeps pointing at the screen.
2. **Make the reading file.** `video-digest digest <folder> --init` writes `reading.md` (a time stamp
   about every 30 seconds) and `digest.json` with the chapters already in it.
3. **Read the user's context** if they gave one (their goals, their business, what they want from the
   video). It only feeds the optional actions section; never invent it.
4. **Read the whole transcript** in `reading.md`, start to end. Note chapter edges, who is speaking,
   and every method, claim, number, tool, example and warning with its stamp. For a long video, read
   it in chapter-sized parts; do not skim.
5. **Fill `digest.json`.**
   - `summary`: three to five sentences, what the video teaches or argues.
   - `chapters[]`: `start` (H:MM:SS), `title`, `speakers` (mark uncertain names as uncertain),
     `summary` (two to five sentences). Say when a chapter is a sponsor segment or a promotion.
   - `points[]`: one line each: `time`, `kind` (method, claim, number, tool, example, warning,
     quote), `text` in your words, `quote` with the speaker's exact words (short, distinctive, from the
     transcript), `speaker`. Numbers are the speaker's numbers: say so.
   - `actions[]`: only when the user gave context; each a concrete step with the `time` it comes from.
     Leave it empty otherwise.
6. **Check by script.** `video-digest digest <folder> --check-only`. Every miss is a quote not found
   within 75 seconds of its time, a malformed time (a placeholder such as `1:00:1x` is refused), or
   chapters out of order. Fix each from the transcript (search `transcript.md` for the exact words; a
   caption track can hear a word differently from how it was said). Then
   `video-digest digest <folder> --snap` moves every point to the second its quote starts.
7. **Read speakers and context.** For every quote that names who said it or what it means, read the
   sentence before and after it in `transcript.md`. The script proves the words and the time; it
   cannot see a wrong speaker or a quote bent out of its context.
8. **Look at the stills** when there are any: open the images in `stills/<chapter>/` and add what the
   screen shows that the words do not (a setting, a price table, code) as points at the still's time.
9. **Write the pages.** `video-digest digest <folder>` writes `digest.md` and `digest.html` (it refuses
   while any problem remains; `--draft` writes them with the misses marked).
10. **Optional fresh reader.** For anything that will be published or acted on, have a fresh agent or a
    person check a sample of quotes for speaker and meaning against `transcript.md`.
11. **Report:** the folder, the door and words, chapters, `quotes N of N found`, and anything left
    uncertain (a guessed language, an unnamed speaker).

## Rules

- Quote exactly; paraphrase only in `text`. A quote that does not pass the check is fixed or removed,
  never kept.
- A speaker's claim is labeled as theirs ("the speaker says", "their number"), not stated as fact.
- No paid door unless the user turns it on (`--allow-paid` and their own `SUPADATA_API_KEY`).
- Respect the site: the tool paces its requests; do not loop it over a channel or a playlist.

## Limits

- YouTube refuses many cloud and data-center addresses; run from a home or office network.
- Automatic captions mishear names, numbers and jargon; check the high-stakes words against the audio
  when they matter.
- Speech to text on a processor is minutes, not seconds: measured at 6.5 to 12.5 times real time with
  the base models, download and model load included.
