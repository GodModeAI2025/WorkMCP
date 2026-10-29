"""Common Crawl: URL index (CDX API) lookups and retrieval of single WARC records."""

from __future__ import annotations

import gzip
import json
from typing import Any

from ..config import Settings
from ..http import HttpClient, NotFoundError
from ..textutil import html_to_text


def parse_cdx_lines(text: str) -> list[dict[str, Any]]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def parse_warc_record(raw: bytes) -> dict[str, Any]:
    """Split one (gzip-compressed) WARC response record into WARC headers, HTTP headers and body."""
    data = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    warc_head, _, rest = data.partition(b"\r\n\r\n")
    warc_headers = _headers(warc_head.decode("utf-8", errors="replace"))
    http_head, _, body = rest.partition(b"\r\n\r\n")
    http_lines = http_head.decode("iso-8859-1", errors="replace").split("\r\n")
    status = None
    if http_lines and http_lines[0].startswith("HTTP/"):
        parts = http_lines[0].split(" ", 2)
        status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    http_headers = _headers("\r\n".join(http_lines[1:]))
    charset = "utf-8"
    ctype = http_headers.get("content-type", "")
    if "charset=" in ctype:
        charset = ctype.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
    try:
        html = body.decode(charset, errors="replace")
    except LookupError:
        html = body.decode("utf-8", errors="replace")
    return {"warc": warc_headers, "status": status, "http": http_headers, "html": html}


def _headers(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in block.split("\r\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


class CommonCrawlClient:
    def __init__(self, http: HttpClient, settings: Settings):
        self.http = http
        self.settings = settings

    async def crawls(self) -> list[dict[str, Any]]:
        raw = await self.http.get_json(f"{self.settings.commoncrawl_index}/collinfo.json")
        return [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []

    async def query(
        self, crawl_id: str, url_pattern: str, *, limit: int = 20, filters: list[str] | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"url": url_pattern, "output": "json", "limit": limit}
        if filters:
            params["filter"] = filters
        try:
            text = await self.http.get_text(f"{self.settings.commoncrawl_index}/{crawl_id}-index", params=params)
        except NotFoundError:
            return []  # the index answers 404 when there are no captures
        return parse_cdx_lines(text)

    async def fetch(self, filename: str, offset: int, length: int) -> dict[str, Any]:
        resp = await self.http.request(
            "GET",
            f"{self.settings.commoncrawl_data}/{filename}",
            headers={"Range": f"bytes={offset}-{offset + length - 1}"},
        )
        record = parse_warc_record(resp.content)
        record["text"] = html_to_text(record.pop("html"), limit=20000)
        return record
