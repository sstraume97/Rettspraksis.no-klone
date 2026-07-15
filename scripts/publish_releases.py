"""Create/update a GitHub Release per touched book, with the rendered PDF and
EPUB (from site_stage/, produced by render_books.py) attached as assets.

Requires the `gh` CLI to be authenticated (GH_TOKEN/GITHUB_TOKEN env var),
which is the case by default on GitHub-hosted Actions runners.

Usage:
    python scripts/publish_releases.py --touched-json '[["hoyesterett","1953"]]'
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from build_books import COURT_LABELS, slug_for

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_STAGE = REPO_ROOT / "site_stage"


def release_exists(tag: str) -> bool:
    return subprocess.run(["gh", "release", "view", tag], capture_output=True).returncode == 0


def publish_one(court: str, year: str | None) -> None:
    slug = slug_for(court, year)
    base = SITE_STAGE / court / year if year else SITE_STAGE / court
    assets = [p for p in (base / f"{slug}.pdf", base / f"{slug}.epub") if p.exists()]
    if not assets:
        print(f"  [hopper over] {court} {year or ''}: ingen PDF/EPUB funnet i {base}")
        return

    title = f"{COURT_LABELS[court]} {year}" if year else COURT_LABELS[court]
    notes = (
        f"Automatisk generert speiling av {title} fra Rettspraksis.no "
        "(CC BY-NC-SA 4.0, ikke-kommersiell). Se LICENSE-CONTENT.md for vilkår."
    )

    if not release_exists(slug):
        subprocess.run(
            ["gh", "release", "create", slug, "--title", title, "--notes", notes],
            check=True,
        )
    else:
        subprocess.run(["gh", "release", "edit", slug, "--notes", notes], check=True)

    subprocess.run(
        ["gh", "release", "upload", slug, *[str(a) for a in assets], "--clobber"],
        check=True,
    )
    print(f"  Publisert: {slug} ({len(assets)} filer)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--touched-json", required=True)
    args = parser.parse_args()
    targets = [tuple(pair) for pair in json.loads(args.touched_json)]

    for court, year in targets:
        publish_one(court, year)


if __name__ == "__main__":
    sys.exit(main())
