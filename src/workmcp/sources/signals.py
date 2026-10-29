"""Hacker News (Algolia search API) as a source of automation signals, and the Arbeitnow job board API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from ..http import HttpClient
from ..textutil import html_to_text

# Fields that change with every fetch without changing the substance of a post.
HN_VOLATILE = ("points", "num_comments", "_highlightResult", "_rankingInfo", "updated_at", "children",
               "relevancy_score")  # fmt: skip


def normalize_hn_hit(hit: dict[str, Any]) -> dict[str, Any]:
    tags = hit.get("_tags") or []
    typ = "comment" if "comment" in tags else "story" if "story" in tags else (tags[0] if tags else None)
    text = hit.get("comment_text") or hit.get("story_text") or ""
    oid = str(hit.get("objectID") or "")
    return {
        "id": oid,
        "typ": typ,
        "titel": hit.get("title") or hit.get("story_title"),
        "text": html_to_text(text, limit=1200) if text else None,
        "url": hit.get("url") or hit.get("story_url"),
        "autor": hit.get("author"),
        "erstellt": hit.get("created_at"),
        "punkte": hit.get("points"),
        "story_id": hit.get("story_id"),
        "hn_url": f"https://news.ycombinator.com/item?id={oid}" if oid else None,
    }


class HackerNewsClient:
    def __init__(self, http: HttpClient, settings: Settings):
        self.http = http
        self.settings = settings

    async def search(self, query: str, *, tags: str = "(story,comment)", hits: int = 20,
                     since_days: int | None = None, by_date: bool = False) -> dict[str, Any]:  # fmt: skip
        params: dict[str, Any] = {"query": query, "tags": tags, "hitsPerPage": max(1, min(hits, 100))}
        if since_days:
            cutoff = int(datetime.now(timezone.utc).timestamp()) - since_days * 86400
            params["numericFilters"] = f"created_at_i>{cutoff}"
        endpoint = "search_by_date" if by_date else "search"
        raw = await self.http.get_json(f"{self.settings.hn_base}/{endpoint}", params=params)
        return raw if isinstance(raw, dict) else {}


def normalize_arbeitnow_job(job: dict[str, Any]) -> dict[str, Any]:
    created = job.get("created_at")
    if isinstance(created, (int, float)):
        created = datetime.fromtimestamp(created, timezone.utc).date().isoformat()
    return {
        "slug": job.get("slug"),
        "titel": job.get("title"),
        "arbeitgeber": job.get("company_name"),
        "ort": job.get("location"),
        "remote": job.get("remote"),
        "tags": job.get("tags") or [],
        "arten": job.get("job_types") or [],
        "erstellt": created,
        "url": job.get("url"),
        "beschreibung": html_to_text(job.get("description"), limit=4000) if job.get("description") else None,
    }


def arbeitnow_matches(job: dict[str, Any], was: str | None, wo: str | None) -> bool:
    """Local filter: every word of ``was`` in title/tags/description, ``wo`` in location (or 'remote')."""
    if was:
        haystack = " ".join([job.get("title") or "", " ".join(job.get("tags") or []), job.get("description") or ""])
        haystack = haystack.lower()
        if not all(word in haystack for word in was.lower().split()):
            return False
    if wo:
        place = wo.strip().lower()
        if place == "remote":
            return bool(job.get("remote"))
        if place not in (job.get("location") or "").lower():
            return False
    return True


class ArbeitnowClient:
    def __init__(self, http: HttpClient, settings: Settings):
        self.http = http
        self.settings = settings

    async def page(self, page: int = 1) -> dict[str, Any]:
        raw = await self.http.get_json(self.settings.arbeitnow_url, params={"page": page})
        return raw if isinstance(raw, dict) else {"data": raw}
