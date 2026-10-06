"""The command line.

    video-digest <url or file> [options]        the transcript folder (alias: video-digest run ...)
    video-digest digest <folder> --init         digest.json to fill, plus reading.md
    video-digest digest <folder>                check every quote, then write digest.md and digest.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from video_digest import __version__, digest, html_page
from video_digest.pipeline import DOORS, AllDoorsFailed, Options, run


def _run_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="video-digest", description="A timed transcript from a video, free doors first.")
    p.add_argument("source", help="a YouTube, Vimeo or Wistia URL, any page yt-dlp supports, or a local file")
    p.add_argument("-o", "--out", default="digests", help="parent folder for the output (default: ./digests)")
    p.add_argument("--lang", default=None, help="caption language (default: the video's original language)")
    p.add_argument("--doors", default=None,
                   help=f"comma list to restrict or reorder the doors ({', '.join(DOORS)})")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--stills", dest="stills", action="store_const", const="always",
                   help="take scene stills by chapter (default: only when the video looks like a screen demo)")
    g.add_argument("--no-stills", dest="stills", action="store_const", const="never", help="never take stills")
    p.set_defaults(stills="auto")
    p.add_argument("--max-stills", type=int, default=40, help="cap on scene stills (default 40)")
    p.add_argument("--pace", type=float, default=2.0, help="seconds between requests to one site (default 2)")
    p.add_argument("--allow-paid", action="store_true",
                   help="allow the paid door last (needs your own SUPADATA_API_KEY; off by default)")
    p.add_argument("--keep-media", action="store_true", help="keep downloaded audio and video in media/")
    p.add_argument("--version", action="version", version=f"video-digest {__version__}")
    return p


def _digest_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="video-digest digest",
                                description="Check a digest's quotes against its transcript and write the pages.")
    p.add_argument("folder", help="an output folder from `video-digest <source>`")
    p.add_argument("--init", action="store_true", help="write digest.json (to fill) and reading.md")
    p.add_argument("--force", action="store_true", help="with --init: overwrite an existing digest.json")
    p.add_argument("--check-only", action="store_true", help="check, write nothing")
    p.add_argument("--draft", action="store_true", help="write the pages even with problems, misses marked")
    p.add_argument("--window", type=float, default=digest.DEFAULT_WINDOW,
                   help="seconds either side of a quote's time to search (default 75)")
    return p


def cmd_digest(argv: list[str]) -> int:
    a = _digest_parser().parse_args(argv)
    folder = Path(a.folder)
    if a.init:
        target = digest.init(folder, force=a.force)
        print(f"wrote {target} and {folder / 'reading.md'}; fill digest.json, then run: "
              f"video-digest digest {folder}")
        return 0
    result = digest.check(folder, a.window)
    matched = sum(1 for q in result.quotes if q["found_at"])
    print(f"quotes: {matched} of {len(result.quotes)} found within {a.window:.0f} s")
    for prob in result.problems:
        print(f"  problem: {prob}")
    if a.check_only:
        return 0 if result.ok else 1
    if not result.ok and not a.draft:
        print("nothing written: fix the problems above (or pass --draft to write the pages with misses marked)")
        return 1
    d = json.loads((folder / "digest.json").read_text(encoding="utf-8"))
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    (folder / "quote_check.json").write_text(json.dumps({"window": a.window, "problems": result.problems,
                                                         "quotes": result.quotes}, indent=2, ensure_ascii=False)
                                             + "\n", encoding="utf-8", newline="\n")
    (folder / "digest.md").write_text(digest.render_markdown(d, meta, result), encoding="utf-8", newline="\n")
    (folder / "digest.html").write_text(html_page.render_html(d, meta, result), encoding="utf-8", newline="\n")
    print(f"wrote {folder / 'digest.md'} and {folder / 'digest.html'}")
    return 0 if result.ok else 1


def cmd_run(argv: list[str]) -> int:
    a = _run_parser().parse_args(argv)
    doors = [d.strip() for d in a.doors.split(",") if d.strip()] if a.doors else None
    opts = Options(out=Path(a.out), lang=a.lang, doors=doors, stills=a.stills, max_stills=a.max_stills,
                   pace=a.pace, allow_paid=a.allow_paid, keep_media=a.keep_media)
    try:
        folder = run(a.source, opts)
    except AllDoorsFailed as e:
        print(f"video-digest: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"video-digest: {e}", file=sys.stderr)
        return 2
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    print(f"{folder}: {meta['words']:,} words from {meta['door']} ({meta.get('track')}), "
          f"{meta['chapters']} chapters, {meta['stills']['taken']} stills, {meta['wall_seconds']} s")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "digest":
        return cmd_digest(argv[1:])
    if argv and argv[0] == "run":
        argv = argv[1:]
    return cmd_run(argv)
