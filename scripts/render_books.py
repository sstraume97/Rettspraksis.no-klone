"""Render touched Quarto book projects (HTML+PDF+EPUB) and stage the output
for publishing: rendered files are moved from `content/<court>/[<year>/]/_book`
into `site_stage/<court>/[<year>/]` (ready to be deployed to GitHub Pages).

Usage:
    python scripts/render_books.py --touched-json '[["hoyesterett","1953"],["tingrett",null]]'
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from build_books import CONTENT_DIR, YEAR_SPLIT_COURTS, slug_for

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_STAGE = REPO_ROOT / "site_stage"


def dir_for(court: str, year: str | None) -> Path:
    return CONTENT_DIR / court / year if court in YEAR_SPLIT_COURTS else CONTENT_DIR / court


def stage_path_for(court: str, year: str | None) -> Path:
    return SITE_STAGE / court / year if court in YEAR_SPLIT_COURTS else SITE_STAGE / court


def render_one(court: str, year: str | None) -> bool:
    src = dir_for(court, year)
    if not (src / "_quarto.yml").exists():
        print(f"  [hopper over] {src}: ingen _quarto.yml (kjør build_books.py først)")
        return False

    subprocess.run(["quarto", "render", str(src)], check=True)

    book_out = src / "_book"
    if not book_out.is_dir():
        print(f"  [FEIL] {src}: quarto render produserte ingen _book/-mappe")
        return False

    # Quarto book projects name the combined PDF/EPUB after the (slugified)
    # book title, not the format's `output-file` setting — rename to our own
    # ASCII-safe, predictable slug so links/release assets are deterministic.
    slug = slug_for(court, year)
    for ext in ("pdf", "epub"):
        matches = list(book_out.glob(f"*.{ext}"))
        if len(matches) == 1:
            matches[0].rename(book_out / f"{slug}.{ext}")
        elif len(matches) > 1:
            print(f"  [ADVARSEL] {book_out}: flere .{ext}-filer funnet, kan ikke gi entydig navn: {matches}")

    dest = stage_path_for(court, year)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(book_out, dest)
    shutil.rmtree(book_out)
    print(f"  Rendret og iscenesatt: {court} {year or ''} -> {dest}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--touched-json", required=True)
    args = parser.parse_args()
    targets = [tuple(pair) for pair in json.loads(args.touched_json)]

    if not targets:
        print("Ingen bøker å rendre.")
        return

    ok = 0
    for court, year in targets:
        print(f"Rendrer {court} {year or ''}...")
        if render_one(court, year):
            ok += 1
    print(f"Ferdig. {ok}/{len(targets)} bøker rendret.")


if __name__ == "__main__":
    sys.exit(main())
