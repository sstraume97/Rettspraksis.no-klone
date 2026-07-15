"""Convert Rettspraksis.no wikitext pages into Markdown files with YAML frontmatter.

Each court-decision page starts with an infobox template, e.g.:

    {{Høyesterett
    |Instans=
    Høyesterett - Dom
    |Dato=
    1953-11-04
    ...
    }}
    <fritekst dom>

This module parses that template (field markers always start their own line,
so we don't need a full wikitext parser) and converts the remaining body via
pandoc (mediawiki -> gfm).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache

TEMPLATE_NAMES = ("Høyesterett", "Lagmannsretter", "Tingretter")
CENSORED_CATEGORY = "Lovdata-sensurert"

FRONTMATTER_FIELDS = [
    "instans",
    "dato",
    "publisert",
    "stikkord",
    "sammendrag",
    "saksgang",
    "parter",
    "forfatter",
]

_TEMPLATE_START_RE = re.compile(
    r"\{\{\s*(" + "|".join(re.escape(n) for n in TEMPLATE_NAMES) + r")\s*\n"
)
_FIELD_RE = re.compile(r"^\|([^\s=|]+)=", re.MULTILINE)
_TEMPLATE_END_RE = re.compile(r"\n\}\}")
_EXTERNAL_LINK_RE = re.compile(r"\[https?://\S+\s+([^\]]+)\]")
_BARE_EXTERNAL_LINK_RE = re.compile(r"\[(https?://\S+)\]")
_WIKILINK_PIPED_RE = re.compile(r"\[\[[^\]|]*\|([^\]]+)\]\]")
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_BOLD_ITALIC_RE = re.compile(r"'{2,5}")
_SIDE_MARKER_RE = re.compile(r"(?m)^Side:(\d+)\s*$")


@dataclass
class ParsedCase:
    template: str
    fields: dict[str, str]
    body_wikitext: str
    categories: list[str] = field(default_factory=list)


class InfoboxNotFoundError(ValueError):
    pass


def parse_infobox(wikitext: str) -> ParsedCase:
    """Split a page's wikitext into (template name, field dict, body wikitext)."""
    start_match = _TEMPLATE_START_RE.search(wikitext)
    if not start_match:
        raise InfoboxNotFoundError("Fant ingen kjent infoboks-mal i wikiteksten")
    template_name = start_match.group(1)
    template_body_start = start_match.end()

    end_match = _TEMPLATE_END_RE.search(wikitext, template_body_start)
    if not end_match:
        raise InfoboxNotFoundError("Fant ingen avsluttende '}}' for infoboksen")
    template_body = wikitext[template_body_start:end_match.start()]
    rest = wikitext[end_match.end():].strip("\n")

    field_matches = list(_FIELD_RE.finditer(template_body))
    fields: dict[str, str] = {}
    for i, m in enumerate(field_matches):
        name = m.group(1).strip().lower()
        value_start = m.end()
        value_end = field_matches[i + 1].start() if i + 1 < len(field_matches) else len(template_body)
        raw_value = template_body[value_start:value_end].strip("\n").strip()
        fields[name] = raw_value

    return ParsedCase(template=template_name, fields=fields, body_wikitext=rest)


def clean_inline(text: str) -> str:
    """Strip common wiki markup from a short infobox field value, returning plain text."""
    if not text:
        return ""
    text = _EXTERNAL_LINK_RE.sub(r"\1", text)
    text = _BARE_EXTERNAL_LINK_RE.sub(r"\1", text)
    text = _WIKILINK_PIPED_RE.sub(r"\1", text)
    text = _WIKILINK_RE.sub(r"\1", text)
    text = _BOLD_ITALIC_RE.sub("", text)
    # Infobox field values are metadata (used in frontmatter and table cells),
    # so collapse all whitespace/newlines to single spaces rather than trying
    # to preserve paragraph breaks in a YAML scalar.
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_lovhenvisninger(raw: str) -> list[str]:
    """Extract a list of readable law-reference strings from the raw field value."""
    cleaned = clean_inline(raw)
    if not cleaned:
        return []
    parts = [p.strip() for p in cleaned.split(",")]
    return [p for p in parts if p]


@lru_cache(maxsize=1)
def _pandoc_cmd() -> list[str]:
    if shutil.which("pandoc"):
        return ["pandoc"]
    if shutil.which("quarto"):
        return ["quarto", "pandoc"]
    raise RuntimeError("Fant hverken 'pandoc' eller 'quarto' i PATH")


def wikitext_to_markdown(body_wikitext: str) -> str:
    """Convert the free-text body of a case from MediaWiki syntax to GitHub-flavored Markdown."""
    if not body_wikitext.strip():
        return ""
    cmd = _pandoc_cmd() + ["-f", "mediawiki", "-t", "gfm", "--wrap=preserve"]
    proc = subprocess.run(
        cmd,
        input=body_wikitext,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pandoc feilet: {proc.stderr.strip()}")
    md = proc.stdout
    md = _SIDE_MARKER_RE.sub(lambda m: f"\n*— side {m.group(1)} —*\n", md)
    return md.strip() + "\n"


def _yaml_scalar(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_frontmatter(
    *,
    title: str,
    parsed: ParsedCase,
    source_url: str,
    censored: bool,
) -> str:
    lines = ["---"]
    lines.append(f"title: {_yaml_scalar(title)}")
    lines.append(f"instans: {_yaml_scalar(clean_inline(parsed.fields.get('instans', '')))}")

    dato_raw = clean_inline(parsed.fields.get("dato", ""))
    dato_match = re.search(r"\d{4}-\d{2}-\d{2}", dato_raw)
    lines.append(f"dato: {dato_match.group(0) if dato_match else _yaml_scalar(dato_raw)}")

    lines.append(f"publisert: {_yaml_scalar(clean_inline(parsed.fields.get('publisert', title)))}")
    lines.append(f"stikkord: {_yaml_scalar(clean_inline(parsed.fields.get('stikkord', '')))}")
    lines.append(f"sammendrag: {_yaml_scalar(clean_inline(parsed.fields.get('sammendrag', '')))}")
    lines.append(f"saksgang: {_yaml_scalar(clean_inline(parsed.fields.get('saksgang', '')))}")
    lines.append(f"parter: {_yaml_scalar(clean_inline(parsed.fields.get('parter', '')))}")
    lines.append(f"forfatter: {_yaml_scalar(clean_inline(parsed.fields.get('forfatter', '')))}")

    lovhenvisninger = parse_lovhenvisninger(parsed.fields.get("lovhenvisninger", ""))
    if lovhenvisninger:
        lines.append("lovhenvisninger:")
        lines.extend(f"  - {_yaml_scalar(item)}" for item in lovhenvisninger)
    else:
        lines.append("lovhenvisninger: []")

    lines.append(f"kilde: {_yaml_scalar(source_url)}")
    lines.append(f"censurert: {'true' if censored else 'false'}")
    lines.append("---")
    return "\n".join(lines)


def assemble_document(
    *,
    title: str,
    parsed: ParsedCase,
    body_md: str,
    source_url: str,
    censored: bool,
) -> str:
    """Combine a parsed infobox + already-converted body Markdown into the final document."""
    frontmatter = build_frontmatter(title=title, parsed=parsed, source_url=source_url, censored=censored)
    censored_note = (
        "\n> **Merk:** Denne avgjørelsen er markert som `Lovdata-sensurert` på "
        "Rettspraksis.no og kan være redigert/forkortet der.\n\n"
        if censored
        else ""
    )
    return f"{frontmatter}\n\n# {title}\n{censored_note}\n{body_md}\n"


def convert_page(
    *,
    title: str,
    wikitext: str,
    categories: list[str],
    source_url: str,
) -> str:
    """Full pipeline: wikitext -> Markdown document with YAML frontmatter."""
    parsed = parse_infobox(wikitext)
    censored = CENSORED_CATEGORY in categories
    body_md = wikitext_to_markdown(parsed.body_wikitext)
    return assemble_document(
        title=title, parsed=parsed, body_md=body_md, source_url=source_url, censored=censored
    )
