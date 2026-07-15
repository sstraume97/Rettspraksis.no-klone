"""Generate/refresh Quarto book projects (per-year for Høyesterett/Lagmannsrett,
one combined book for Tingrett) directly inside the `content/` directories that
hold the case Markdown files — no separate copy of the files is kept, so each
`content/<court>/[<year>/]` directory doubles as its own Quarto book project
once `_quarto.yml` + `index.qmd` have been generated into it.

Usage:
    python scripts/build_books.py --all
    python scripts/build_books.py --touched-json '[["hoyesterett","1953"],["tingrett",null]]'
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = REPO_ROOT / "content"

YEAR_SPLIT_COURTS = {"hoyesterett", "lagmannsrett"}
COURT_LABELS = {
    "hoyesterett": "Høyesterett",
    "lagmannsrett": "Lagmannsrettene",
    "tingrett": "Tingrettene",
}
TABLE_COLUMNS = [
    ("instans", "Instans"),
    ("dato", "Dato"),
    ("publisert", "Publisert"),
    ("stikkord", "Stikkord"),
    ("sammendrag", "Sammendrag"),
    ("saksgang", "Saksgang"),
    ("parter", "Parter"),
    ("forfatter", "Forfatter"),
    ("lovhenvisninger", "Lovhenvisninger"),
]
TRUNCATE_LEN = 120

_REG_NUMBER_RE = re.compile(r"-\d{4}-0*(\d+)")
_YAML_FRONTMATTER_RE = re.compile(r"^---\n(.*?\n)---\n", re.DOTALL)


def read_frontmatter(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    m = _YAML_FRONTMATTER_RE.match(text)
    if not m:
        return None
    data = yaml.safe_load(m.group(1)) or {}
    data["_filename"] = path.name
    return data


def registration_number(publisert: str) -> int:
    m = _REG_NUMBER_RE.search(publisert or "")
    return int(m.group(1)) if m else -1


def collect_cases(dir_path: Path) -> list[dict]:
    cases = []
    for path in sorted(dir_path.glob("*.md")):
        fm = read_frontmatter(path)
        if fm is None:
            continue
        cases.append(fm)
    cases.sort(key=lambda fm: (registration_number(str(fm.get("publisert", ""))), fm["_filename"]))
    return cases


def _table_cell(value) -> str:
    if value is None:
        text = ""
    elif isinstance(value, list):
        text = "; ".join(str(v) for v in value)
    else:
        text = str(value)
    text = text.replace("\n", " ").replace("|", "\\|").strip()
    if len(text) > TRUNCATE_LEN:
        text = text[: TRUNCATE_LEN - 1].rstrip() + "…"
    return text


def write_index_qmd(dir_path: Path, title: str, cases: list[dict]) -> None:
    lines = [
        "---",
        f'title: "{title}"',
        "---",
        "",
        f"Denne boken er en automatisk generert speiling av avgjørelser fra "
        f"[Rettspraksis.no](https://rettspraksis.no), lisensiert "
        f"[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.no). "
        f"Se [LICENSE-CONTENT.md](https://github.com/sstraume97/Rettspraksis.no-klone/blob/main/LICENSE-CONTENT.md) "
        f"for fullstendige vilkår. Boken inneholder {len(cases)} avgjørelser.",
        "",
        "| " + " | ".join(label for _, label in TABLE_COLUMNS) + " |",
        "|" + "---|" * len(TABLE_COLUMNS),
    ]
    for fm in cases:
        cells = []
        for key, _ in TABLE_COLUMNS:
            if key == "publisert":
                link_text = _table_cell(fm.get("publisert", fm["_filename"]))
                cells.append(f"[{link_text}]({fm['_filename']})")
            else:
                cells.append(_table_cell(fm.get(key)))
        lines.append("| " + " | ".join(cells) + " |")
    (dir_path / "index.qmd").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def slug_for(court: str, year: str | None) -> str:
    """ASCII-safe, predictable basename used for rendered PDF/EPUB and release tags."""
    return f"{court}-{year}" if year else court


def write_quarto_yml(dir_path: Path, title: str, chapters: list[str]) -> None:
    # NOTE: format-level `output-file` is intentionally not set here — Quarto
    # book projects name the combined PDF/EPUB after the (slugified) book
    # title regardless, so render_books.py renames the rendered artifacts to
    # the canonical `slug_for()` name itself after rendering.
    config = {
        "project": {"type": "book"},
        "book": {
            "title": title,
            "subtitle": "Speilet fra Rettspraksis.no (CC BY-NC-SA 4.0)",
            "date": date.today().isoformat(),
            "chapters": chapters,
            "page-footer": {
                "center": "Kilde: [rettspraksis.no](https://rettspraksis.no) — CC BY-NC-SA 4.0 — "
                "ikke-kommersiell speiling"
            },
        },
        "lang": "nb",
        "format": {
            "html": {"theme": "cosmo"},
            "pdf": {
                "documentclass": "report",
                "pdf-engine": "xelatex",
                "toc": True,
                "mainfont": "Noto Serif",
            },
            "epub": {"toc": True},
        },
    }
    with (dir_path / "_quarto.yml").open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)


def build_book(dir_path: Path, title: str) -> int:
    if not dir_path.is_dir():
        print(f"  [hopper over] {dir_path} finnes ikke")
        return 0
    cases = collect_cases(dir_path)
    if not cases:
        print(f"  [hopper over] {dir_path} har ingen avgjørelser")
        return 0
    write_index_qmd(dir_path, title, cases)
    chapters = ["index.qmd"] + [fm["_filename"] for fm in cases]
    write_quarto_yml(dir_path, title, chapters)
    print(f"  Bygget bok: {dir_path} ({len(cases)} avgjørelser)")
    return len(cases)


def build_for(court: str, year: str | None) -> int:
    label = COURT_LABELS[court]
    if court in YEAR_SPLIT_COURTS:
        if not year:
            raise ValueError(f"{court} krever et årstall")
        return build_book(CONTENT_DIR / court / year, f"{label} {year}")
    return build_book(CONTENT_DIR / court, label)


def discover_all() -> list[tuple[str, str | None]]:
    targets: list[tuple[str, str | None]] = []
    for court in YEAR_SPLIT_COURTS:
        court_dir = CONTENT_DIR / court
        if not court_dir.is_dir():
            continue
        for year_dir in sorted(p for p in court_dir.iterdir() if p.is_dir()):
            targets.append((court, year_dir.name))
    if (CONTENT_DIR / "tingrett").is_dir():
        targets.append(("tingrett", None))
    return targets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Bygg alle bøker som finnes innhold for")
    group.add_argument(
        "--touched-json",
        help='JSON-liste av [court, year] par, f.eks. \'[["hoyesterett","1953"],["tingrett",null]]\'',
    )
    args = parser.parse_args()

    targets = discover_all() if args.all else [tuple(pair) for pair in json.loads(args.touched_json)]

    total = 0
    for court, year in targets:
        total += build_for(court, year)
    print(f"Ferdig. {len(targets)} bok(er) behandlet, {total} avgjørelser totalt.")


if __name__ == "__main__":
    sys.exit(main())
