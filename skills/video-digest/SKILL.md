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
3. The skill: as a Claude Code plugin, `/plugin marketplace add RobBrautigam/video-digest`, then
   `/plugin install video-digest@video-digest` (Claude Code 2.1.275 or later also takes the one command
   `/plugin install video-digest --marketplace RobBrautigam/video-digest`); or copy this folder to
   `~/.claude/skills/video-digest/` (every project) or `<project>/.claude/skills/video-digest/` (one
   project).
4. Check: `video-digest --version`.

## The method

Steps 2, 5 and 7 carry the quality: exact times, every quote matched by script, and a person (or a
fresh agent) reading speakers and context, which no script can check.

0. **One video per run.** Get the video's own link from the user. If they named a talk but sent no
   link, find it with one ordinary web search, never by looping the tool or yt-dlp over search
   results: YouTube refuses an address that asks too often, and the caption door is the first to go.
1. **Get the timed transcript.** `video-digest <url or file> -o digests`. Read the last line: the door
   used, words, chapters. `transcript.html` in the folder is the whole text by chapter, for a person
   to read. Open `meta.json` when anything looks off:
   - `attempts` lists every door tried, why each failed and how long it took;
   - `transcript_notes.thin_transcript` means the caption track held almost no words for the video's
     length (a music track, a placeholder) and no later door heard more: say so in the report;
   - `transcript_notes.language_guessed` means the player did not say which track is spoken: rerun
     with `--lang <code>` if the guess is wrong;
   - for a screen demo, pass `--stills` (stills by chapter in `stills/`), or let the tool decide: it
     takes stills when the speaker keeps pointing at the screen.
2. **Make the reading file.** `video-digest digest <folder> --init` writes `reading.md` (paragraphs of
   30 to 45 seconds, each with its time stamp) and `digest.json` with the chapters already in it.
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
   - **Dates:** a price, a number or a product fact is dated by the day the talk was given when the
     description in `meta.json` says it (a conference talk is often uploaded months later), else by the
     upload date, and the digest says which.
   - `sections[]` (optional): any extra section the user asked for ("what we could borrow", "open
     questions"), each `{"title", "intro", "rows": [{"time", "text", "quote", "speaker"}]}`. Every row's
     quote is checked like a point's.
   - `actions[]`: only when the user gave context; each a concrete step with the `time` it comes from,
     and a `quote` when it rests on the speaker's words (checked too). Leave it empty otherwise.
6. **Check by script.** `video-digest digest <folder> --check-only`. Every miss is a quote not found
   within 75 seconds of its time (in a point, a section row or an action), a malformed time (a
   placeholder such as `1:00:1x` is refused anywhere in the digest, your own prose included), or
   chapters out of order. Fix each from the transcript (search `transcript.md` for the exact words; a
   caption track hears a product or a name its own way, so quote it as the track spells it). Then
   `video-digest digest <folder> --snap` moves every quoted entry to the second its quote starts.
7. **Read speakers and context.** For every quote that names who said it or what it means, read the
   sentence before and after it in `transcript.md`. The script proves the words and the time; it
   cannot see a wrong speaker or a quote bent out of its context.
8. **Look at the stills** when there are any: open the images in `stills/<chapter>/` before writing any
   point about what is on screen, and add what the screen shows that the words do not (a setting, a
   price table, code) as points at the still's time. Such a point says it came from a still: no quote
   checks it.
9. **Write the pages.** `video-digest digest <folder>` writes `digest.md`, `digest.html` and
   `transcript.html` (the whole text cut into your chapters; it refuses while any problem remains;
   `--draft` writes them with the misses marked).
10. **A fresh reader** for anything that will be published or acted on: a fresh agent or a person
    reads the pages against `transcript.md`. Every quote passing the script is not enough: the reader
    checks the digest's own words too (a count such as "three questions", a claim, a chapter summary,
    anything said about the user's own situation), because no script can see a wrong sentence that
    quotes nothing.
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
  the base models, download and model load included. For a long course, plan on the slower figure (a
  five-hour video is most of an hour).
