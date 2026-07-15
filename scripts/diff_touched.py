"""Determine which (court, year) book directories have new/changed content
since the last successful publish, via `git diff`.

This is the authoritative source for what weekly-update.yml should
(re)build+render+publish — it naturally covers *both* this week's live
`recentchanges` updates *and* everything backfill.yml accumulated on main
throughout the week (backfill.yml only imports content, it never builds or
publishes books itself), by diffing against `state.last_published_ref`
rather than just this run's own commit.

Usage:
    python scripts/diff_touched.py --since <git-sha-or-empty>

Prints "TOUCHED_JSON=[...]" to stdout, same [ [court, year_or_null], ... ]
shape used by build_books.py / render_books.py / publish_releases.py.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_YEAR_COURT_RE = re.compile(r"^content/(hoyesterett|lagmannsrett)/(\d{4})/")
_FLAT_COURT_RE = re.compile(r"^content/(tingrett)/")


def _paths_to_touched(paths: list[str]) -> set[tuple[str, str | None]]:
    touched: set[tuple[str, str | None]] = set()
    for line in paths:
        m = _YEAR_COURT_RE.match(line)
        if m:
            touched.add((m.group(1), m.group(2)))
            continue
        if _FLAT_COURT_RE.match(line):
            touched.add(("tingrett", None))
    return touched


def changed_content_dirs(since_ref: str | None) -> set[tuple[str, str | None]]:
    if since_ref:
        cmd = ["git", "diff", "--name-only", f"{since_ref}..HEAD", "--", "content/"]
    else:
        # First-ever publish: treat every currently-tracked content file as touched.
        cmd = ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", "content/"]
    out = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout
    return _paths_to_touched(out.splitlines())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=None, help="Git-ref å diffe fra (tom = alt innhold)")
    args = parser.parse_args()

    since_ref = args.since or None
    touched = sorted(changed_content_dirs(since_ref))
    print("TOUCHED_JSON=" + json.dumps(touched, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
