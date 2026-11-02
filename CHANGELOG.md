# Changelog

The version lives in `pyproject.toml`, `src/video_digest/__init__.py` and `.claude-plugin/plugin.json`.

## 0.2.0 (2026-11-02)

### Added

- `transcript.html`: the whole transcript as a page for people, under its chapters, in paragraphs of
  30 to 45 seconds (a paragraph ends at the first sentence end after 30 seconds, or at 45; a line
  after a long silence starts its own), each paragraph's time a link into the video on YouTube and
  Vimeo, each chapter a fold, a chapter over about 4,500 words split
  into several folds. Every run writes it; `video-digest digest` rewrites it with the digest's
  chapters and a link back to the digest; `video-digest page <folder>` writes it on its own.
- `sections[]` in `digest.json`: any extra section (a title, an intro line, rows each with a time, text,
  quote and speaker), rendered after the points, with every row's quote checked.
- Quotes in `actions[]` are checked and snapped like points; an action with a quote needs its time.
- The digest page's chapter table carries each chapter's length and word count, and the page ends with
  "How this page was made": the doors tried, the quote count, the longest stretch with no spoken words
  (the stretch before the first word and after the last included), and the versions that made the
  transcript and the page.
- A thin answer (on a video of a minute or more, fewer than 5 spoken words a minute; sound tags do not
  count) is kept in reserve while the next doors run; the video's length is read from its metadata
  before the first answer is judged; the answer with the most spoken words wins, a later answer that
  heard less is marked `Fewer words`, and a kept thin answer is marked `kept` and noted as
  `transcript_notes.thin_transcript` in `meta.json`.
- The skill installs as a Claude Code plugin: `.claude-plugin/plugin.json` and `marketplace.json`.
- The skill's method: one video per run, dates for product facts, extra sections, quoted actions,
  stills opened before a point about the screen, and a fresh reader for the digest's own words.
- README: a quick start that runs offline on the committed example, a diagram of the doors, a
  "missing tools" table, troubleshooting, and screenshots of both pages.

### Changed

- The word clock spreads each caption line's words over the time until the next line starts when
  lines overlap (automatic captions do), or when a line has no length, so a quote's time is no longer
  late.
- A placeholder time such as `1:00:1x` is refused anywhere in the digest's text (summary, chapter
  titles and summaries, points, sections, actions), not only in point text and chapter summaries; a
  ratio of digits only (16:9, 80:20) is no longer taken for a time.
- `reading.md` is cut into paragraphs by the same rule as the transcript page.
- A digest entry with no time says "has no time" rather than printing `None`; an action with a quote
  and no time is one problem, not also a missed quote.
- On a `--draft` page, a chapter that ends before it starts (chapters out of order) gets no length,
  and the first good chapter takes any words before it.
- The transcript page names a speech-to-text track as such, not as automatic captions.
- `--snap` moves quoted section rows and actions as well as points.
- The committed example's pages are regenerated with 0.2.0 and include `transcript.html`.

### Tests

- 17 new tests (`tests/test_v02.py`) and 23 new mutations in `scripts/mutation_check.py`; all 73
  mutations turn their test red.
- The speech test that needs numpy is skipped when the `[speech]` extra is not installed.

## 0.1.0 (2026-10-05)

- The transcript command: free doors in order (YouTube's caption library, yt-dlp subtitles, the
  player's own caption file for Vimeo and Wistia, a caption file beside a local file, speech to text
  with faster-whisper, and a paid door that is off by default), with pacing and no retry after a
  refusal.
- Output per video: `transcript.md`, `transcript.json`, `chapters.json`, `meta.json` and scene stills
  by chapter.
- The digest step: `--init`, `--check-only`, `--snap`, `--draft`; every quote checked against the
  transcript within 75 seconds of its time; Markdown and a self-contained HTML page.
- The Claude Code skill in `skills/video-digest/`.
- A committed example from a Creative Commons NASA video, and `scripts/mutation_check.py`.
