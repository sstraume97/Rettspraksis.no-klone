"""Generate the GitHub Pages landing page (site_stage/index.html) listing
every book that currently has content in `content/`, regardless of whether it
was rebuilt in this run — non-touched books' rendered files already live on
the gh-pages branch (preserved via `keep_files: true` on deploy) at the same
predictable paths this page links to.

Usage:
    python scripts/build_index.py
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

from build_books import COURT_LABELS, discover_all, slug_for

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_STAGE = REPO_ROOT / "site_stage"

COURT_ORDER = ["hoyesterett", "lagmannsrett", "tingrett"]


def book_links(court: str, year: str | None) -> str:
    slug = slug_for(court, year)
    base = f"{court}/{year}" if year else court
    label = html.escape(year) if year else "Alle avgjørelser"
    return (
        f'<li><span class="year">{label}</span> '
        f'<a href="{base}/index.html">Les</a> · '
        f'<a href="{base}/{slug}.pdf">PDF</a> · '
        f'<a href="{base}/{slug}.epub">EPUB</a></li>'
    )


def build() -> None:
    books = discover_all()
    by_court: dict[str, list[str | None]] = {}
    for court, year in books:
        by_court.setdefault(court, []).append(year)

    sections = []
    for court in COURT_ORDER:
        years = by_court.get(court)
        if not years:
            continue
        label = html.escape(COURT_LABELS[court])
        items = "".join(book_links(court, y) for y in sorted(years, key=lambda y: y or "", reverse=True))
        sections.append(f"<section><h2>{label}</h2><ul>{items}</ul></section>")

    page = f"""<!doctype html>
<html lang="nb">
<head>
<meta charset="utf-8">
<title>Rettspraksis.no-klone</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 60rem; margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ margin-bottom: 0.2rem; }}
  .subtitle {{ color: #555; margin-top: 0; }}
  ul {{ list-style: none; padding-left: 0; }}
  li {{ padding: 0.25rem 0; border-bottom: 1px solid #eee; }}
  .year {{ display: inline-block; min-width: 4rem; font-weight: 600; }}
  footer {{ margin-top: 3rem; color: #777; font-size: 0.9rem; }}
</style>
</head>
<body>
<h1>Rettspraksis.no-klone</h1>
<p class="subtitle">Automatisk oppdatert speiling av norske rettsavgjørelser fra
<a href="https://rettspraksis.no">Rettspraksis.no</a>, publisert som Quarto-bøker
(HTML/PDF/EPUB) per rettsinstans og år.</p>
{"".join(sections) if sections else "<p>Ingen bøker publisert ennå.</p>"}
<footer>
Innhold lisensiert <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/deed.no">CC BY-NC-SA 4.0</a>
— kilde: <a href="https://rettspraksis.no">rettspraksis.no</a>. Ikke-kommersiell, ikke-offisiell speiling.
Kildekode: <a href="https://github.com/sstraume97/Rettspraksis.no-klone">GitHub</a>.
</footer>
</body>
</html>
"""
    SITE_STAGE.mkdir(parents=True, exist_ok=True)
    (SITE_STAGE / "index.html").write_text(page, encoding="utf-8", newline="\n")
    print(f"Skrev {SITE_STAGE / 'index.html'} med {len(books)} bøker.")


if __name__ == "__main__":
    sys.exit(build())
