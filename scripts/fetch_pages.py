"""Fetch court-decision pages from Rettspraksis.no and write them as Markdown.

Two modes:

  backfill        Gradually import the full historical set (Høyesterett,
                   Lagmannsretter, Tingretter), resuming from
                   state/sync_state.json between runs. Safe to run
                   repeatedly/on a schedule — becomes a no-op once complete.

  recentchanges    Fetch only pages that are new or have changed since the
                   last successful run (state.last_rc_timestamp), regardless
                   of backfill status. This is what keeps already-imported
                   pages fresh, and is what the weekly workflow uses.

Both modes respect Rettspraksis.no's robots.txt `Crawl-delay: 15` via
mw_common.MediaWikiClient, and print the set of (court, year) pairs touched
so the caller can rebuild only the affected books.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import convert_to_markdown as ctm
import mw_common

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = REPO_ROOT / "content"
STATE_FILE = REPO_ROOT / "state" / "sync_state.json"

COURT_ORDER = ["hoyesterett", "lagmannsrett", "tingrett"]
YEAR_SPLIT_COURTS = {"hoyesterett", "lagmannsrett"}  # tingrett stays flat (low volume)

_TITLE_YEAR_RE = re.compile(r"-(\d{4})-")
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*]')


def chunked(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i : i + n]


def slugify_filename(title: str) -> str:
    return _UNSAFE_FILENAME_RE.sub("_", title).strip()


def source_url(title: str) -> str:
    return mw_common.SITE_URL + title.replace(" ", "_")


def year_for(title: str, parsed: ctm.ParsedCase) -> str:
    dato_clean = ctm.clean_inline(parsed.fields.get("dato", ""))
    m = re.search(r"(\d{4})-\d{2}-\d{2}", dato_clean)
    if m:
        return m.group(1)
    m2 = _TITLE_YEAR_RE.search(title)
    if m2:
        return m2.group(1)
    return "ukjent-aar"


def target_path(court: str, title: str, year: str) -> Path:
    filename = slugify_filename(title) + ".md"
    if court in YEAR_SPLIT_COURTS:
        return CONTENT_DIR / court / year / filename
    return CONTENT_DIR / court / filename


def write_case(court: str, title: str, info: dict) -> tuple[str, str] | None:
    """Parse + convert one page and write it to content/. Returns (court, year) or None if skipped."""
    wikitext = info.get("wikitext", "")
    try:
        parsed = ctm.parse_infobox(wikitext)
    except ctm.InfoboxNotFoundError:
        print(f"  [hopper over] {title}: ingen kjent infoboks-mal (trolig ikke en avgjørelse)")
        return None

    year = year_for(title, parsed)
    categories = info.get("categories", [])
    censored = ctm.CENSORED_CATEGORY in categories
    body_md = ctm.wikitext_to_markdown(parsed.body_wikitext)
    doc = ctm.assemble_document(
        title=title, parsed=parsed, body_md=body_md, source_url=source_url(title), censored=censored
    )

    path = target_path(court, title, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8", newline="\n")
    return (court, year)


def process_titles(client: mw_common.MediaWikiClient, court: str, titles: list[str], touched: set[tuple[str, str]]) -> int:
    written = 0
    for batch in chunked(titles, mw_common.BATCH_SIZE):
        content_map = client.fetch_pages_content(batch)
        for title in batch:
            info = content_map.get(title)
            if not info or info.get("missing"):
                print(f"  [mangler] {title}")
                continue
            result = write_case(court, title, info)
            if result:
                touched.add(result)
                written += 1
    return written


def run_backfill(args: argparse.Namespace) -> None:
    state = mw_common.load_state(STATE_FILE)
    bf = state["backfill"]
    touched: set[tuple[str, str]] = set()

    if bf.get("complete"):
        print("Backfill er allerede fullført for alle instanser – ingenting å gjøre.")
        _print_touched(touched)
        return

    if not bf.get("current_court"):
        remaining = [c for c in COURT_ORDER if c not in bf.get("completed_courts", [])]
        if not remaining:
            bf["complete"] = True
            mw_common.save_state(STATE_FILE, state)
            print("Backfill fullført for alle instanser!")
            return
        bf["current_court"] = remaining[0]
        bf["cmcontinue"] = None

    client = mw_common.MediaWikiClient()
    deadline = time.monotonic() + args.budget_minutes * 60
    total_processed = 0

    while True:
        court = bf["current_court"]
        category = mw_common.COURT_CATEGORIES[court]
        print(f"Henter {court} ({category})  cursor={bf.get('cmcontinue')!r}")

        stop_reason = None
        for members, next_cont in client.iter_category_member_batches(category, cmcontinue=bf.get("cmcontinue")):
            titles = [m["title"] for m in members]
            if args.limit:
                remaining_budget = args.limit - total_processed
                if remaining_budget <= 0:
                    stop_reason = "limit"
                    break
                titles = titles[:remaining_budget]

            written = process_titles(client, court, titles, touched)
            total_processed += written

            bf["cmcontinue"] = next_cont
            bf["pages_imported"] = bf.get("pages_imported", 0) + written
            if next_cont is None:
                if court not in bf["completed_courts"]:
                    bf["completed_courts"].append(court)
                bf["current_court"] = None
                bf["cmcontinue"] = None
            mw_common.save_state(STATE_FILE, state)

            if time.monotonic() >= deadline:
                stop_reason = "budget"
                break
            if args.limit and total_processed >= args.limit:
                stop_reason = "limit"
                break
            if next_cont is None:
                break

        if stop_reason:
            print(f"Stopper denne kjøringen ({stop_reason}). Totalt behandlet: {total_processed} sider.")
            _print_touched(touched)
            return

        if bf["current_court"] is None:
            remaining = [c for c in COURT_ORDER if c not in bf["completed_courts"]]
            if not remaining:
                bf["complete"] = True
                mw_common.save_state(STATE_FILE, state)
                print(f"Backfill fullført for alle instanser! Totalt behandlet denne kjøringen: {total_processed}.")
                _print_touched(touched)
                return
            bf["current_court"] = remaining[0]
            bf["cmcontinue"] = None
            mw_common.save_state(STATE_FILE, state)


def run_recentchanges(args: argparse.Namespace) -> None:
    state = mw_common.load_state(STATE_FILE)
    since = state.get("last_rc_timestamp")
    if not since:
        # First-ever run: only look back a short window, since the full
        # history is (or will be) covered by the backfill process instead.
        since = "2000-01-01T00:00:00Z"

    run_started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    client = mw_common.MediaWikiClient()
    touched: set[tuple[str, str]] = set()

    changed_titles = []
    for change in client.iter_recent_changes(since_iso=since):
        changed_titles.append(change["title"])
    changed_titles = sorted(set(changed_titles))
    print(f"{len(changed_titles)} endrede/nye sider siden {since}.")

    if changed_titles:
        # We don't know which court a changed title belongs to ahead of
        # time, so fetch categories for each and match against the three
        # tracked categories.
        total_written = 0
        for batch in chunked(changed_titles, mw_common.BATCH_SIZE):
            content_map = client.fetch_pages_content(batch)
            for title in batch:
                info = content_map.get(title)
                if not info or info.get("missing"):
                    continue
                court = _infer_court(info.get("categories", []))
                if not court:
                    continue
                result = write_case(court, title, info)
                if result:
                    touched.add(result)
                    total_written += 1
        print(f"Skrev {total_written} oppdaterte/nye avgjørelser.")

    state["last_rc_timestamp"] = run_started_at
    mw_common.save_state(STATE_FILE, state)
    _print_touched(touched)


def _infer_court(categories: list[str]) -> str | None:
    for court, category in mw_common.COURT_CATEGORIES.items():
        if category.split(":", 1)[-1] in categories:
            return court
    return None


def _print_touched(touched: set[tuple[str, str]]) -> None:
    payload = sorted(touched)
    print("TOUCHED_JSON=" + json.dumps(payload, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["backfill", "recentchanges"], required=True)
    parser.add_argument("--budget-minutes", type=float, default=45.0)
    parser.add_argument("--limit", type=int, default=None, help="Maks antall sider (til testing)")
    args = parser.parse_args()

    if args.mode == "backfill":
        run_backfill(args)
    else:
        run_recentchanges(args)


if __name__ == "__main__":
    sys.exit(main())
