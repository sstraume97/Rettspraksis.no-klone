"""Shared helpers for talking to the Rettspraksis.no MediaWiki API politely.

Respects the site's robots.txt (`Crawl-delay: 15`) by never issuing two HTTP
requests less than CRAWL_DELAY_SECONDS apart, and identifies itself with a
descriptive User-Agent as required by MediaWiki API etiquette.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator

import requests

API_URL = "https://rettspraksis.no/w/api.php"
SITE_URL = "https://rettspraksis.no/wiki/"
CRAWL_DELAY_SECONDS = 15
BATCH_SIZE = 50
USER_AGENT = (
    "Rettspraksis.no-klone/1.0 "
    "(https://github.com/sstraume97/Rettspraksis.no-klone; "
    "ikke-kommersiell arkiveringsspeiling; kontakt via GitHub issues) "
    "requests/" + requests.__version__
)

COURT_CATEGORIES = {
    "hoyesterett": "Kategori:Høyesterett",
    "lagmannsrett": "Kategori:Lagmannsretter",
    "tingrett": "Kategori:Tingretter",
}

CENSORED_CATEGORY = "Lovdata-sensurert"


class MediaWikiClient:
    """Rate-limited client for the Rettspraksis.no MediaWiki API."""

    def __init__(self, crawl_delay: float = CRAWL_DELAY_SECONDS):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.crawl_delay = crawl_delay
        self._last_request_ts: float | None = None

    def _throttle(self) -> None:
        if self._last_request_ts is not None:
            elapsed = time.monotonic() - self._last_request_ts
            wait = self.crawl_delay - elapsed
            if wait > 0:
                time.sleep(wait)
        self._last_request_ts = time.monotonic()

    def _get(self, params: dict, retries: int = 3) -> dict:
        params = {**params, "format": "json", "formatversion": "2"}
        last_exc: Exception | None = None
        for attempt in range(retries):
            self._throttle()
            try:
                resp = self.session.get(API_URL, params=params, timeout=60)
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, json.JSONDecodeError) as exc:
                last_exc = exc
                if attempt < retries - 1:
                    time.sleep(5 * (attempt + 1))
        assert last_exc is not None
        raise last_exc

    def iter_category_member_batches(
        self, category: str, cmcontinue: str | None = None
    ) -> Iterator[tuple[list[dict], str | None]]:
        """Yield (members, next_cmcontinue) per API page (up to 500 members).

        `next_cmcontinue` is the cursor to resume from after this batch has
        been fully processed by the caller; it is None once the category is
        exhausted. Checkpointing at this (rather than per-title) granularity
        means an interrupted run re-fetches at most ~500 titles of content.
        """
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmnamespace": 0,
            "cmlimit": 500,
            "cmprop": "ids|title",
        }
        cont = cmcontinue
        while True:
            if cont:
                params["cmcontinue"] = cont
            else:
                params.pop("cmcontinue", None)
            data = self._get(params)
            members = data.get("query", {}).get("categorymembers", [])
            cont = data.get("continue", {}).get("cmcontinue")
            yield members, cont
            if not cont:
                return

    def fetch_pages_content(self, titles: list[str]) -> dict[str, dict]:
        """Batch-fetch wikitext + categories + timestamp for up to BATCH_SIZE titles."""
        if not titles:
            return {}
        if len(titles) > BATCH_SIZE:
            raise ValueError(f"fetch_pages_content: batch too large ({len(titles)} > {BATCH_SIZE})")
        params = {
            "action": "query",
            "prop": "revisions|categories",
            "rvprop": "content|timestamp",
            "rvslots": "main",
            "cllimit": "max",
            "titles": "|".join(titles),
        }
        data = self._get(params)
        result: dict[str, dict] = {}
        for page in data.get("query", {}).get("pages", []):
            title = page.get("title")
            if page.get("missing"):
                result[title] = {"missing": True}
                continue
            revisions = page.get("revisions") or []
            if not revisions:
                result[title] = {"missing": True}
                continue
            slot = revisions[0].get("slots", {}).get("main", {})
            wikitext = slot.get("content", "")
            timestamp = revisions[0].get("timestamp")
            categories = [c["title"].split(":", 1)[-1] for c in page.get("categories", []) or []]
            result[title] = {
                "missing": False,
                "wikitext": wikitext,
                "timestamp": timestamp,
                "categories": categories,
                "pageid": page.get("pageid"),
            }
        return result

    def iter_recent_changes(self, since_iso: str, rccontinue: str | None = None) -> Iterator[dict]:
        """Yield recent-changes entries (edits + new pages, ns=0) newer than since_iso."""
        params = {
            "action": "query",
            "list": "recentchanges",
            "rcnamespace": 0,
            "rctype": "edit|new",
            "rcprop": "title|timestamp|ids",
            "rclimit": 500,
            "rcdir": "newer",
            "rcstart": since_iso,
        }
        cont = rccontinue
        while True:
            if cont:
                params["rccontinue"] = cont
            data = self._get(params)
            for change in data.get("query", {}).get("recentchanges", []):
                yield change
            cont = data.get("continue", {}).get("rccontinue")
            self.last_rccontinue = cont
            if not cont:
                return


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "backfill": {
            "complete": False,
            "current_court": None,
            "cmcontinue": None,
            "completed_courts": [],
            "pages_imported": 0,
        },
        "last_rc_timestamp": None,
    }


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
