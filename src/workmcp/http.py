"""Shared async HTTP client: timeouts, retries with backoff, polite per-host pacing."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}


class SourceError(RuntimeError):
    """A data source could not be reached or answered with an error."""

    def __init__(self, message: str, *, status: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status = status
        self.url = url


class NotFoundError(SourceError):
    """The source answered 404 (e.g. a job ad that no longer exists)."""


class HttpClient:
    def __init__(
        self,
        *,
        timeout: float = 30.0,
        user_agent: str = "WorkMCP",
        transport: httpx.AsyncBaseTransport | None = None,
        retries: int = 3,
        min_interval: float = 0.2,
        backoff: float = 1.0,
    ):
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": user_agent, "Accept": "application/json, text/plain, */*"},
            transport=transport,
            follow_redirects=True,
            trust_env=True,
        )
        self.retries = max(1, retries)
        self.min_interval = min_interval
        self.backoff = backoff
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._last_call: dict[str, float] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _pace(self, host: str) -> None:
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._last_call.get(host, 0.0) + self.min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call[host] = time.monotonic()

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        host = urlsplit(url).netloc
        last_error: Exception | None = None
        for attempt in range(self.retries):
            await self._pace(host)
            try:
                resp = await self._client.request(method, url, params=clean, headers=headers, data=data)
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if resp.status_code == 404:
                    raise NotFoundError(f"404 Nicht gefunden: {resp.url}", status=404, url=str(resp.url))
                if resp.status_code in RETRY_STATUS and attempt + 1 < self.retries:
                    await asyncio.sleep(self._retry_after(resp, attempt))
                    continue
                if resp.status_code >= 400:
                    snippet = resp.text[:300].replace("\n", " ")
                    raise SourceError(
                        f"HTTP {resp.status_code} von {resp.url}: {snippet}", status=resp.status_code, url=str(resp.url)
                    )
                return resp
            if attempt + 1 < self.retries:
                await asyncio.sleep(self.backoff * (2**attempt))
        raise SourceError(f"Keine Verbindung zu {host}: {last_error}", url=url)

    def _retry_after(self, resp: httpx.Response, attempt: int) -> float:
        header = resp.headers.get("Retry-After", "")
        if header.isdigit():
            return min(float(header), 10.0)
        return self.backoff * (2**attempt)

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        resp = await self.request("GET", url, **kwargs)
        try:
            return resp.json()
        except ValueError as exc:
            raise SourceError(f"Antwort von {resp.url} ist kein JSON", url=str(resp.url)) from exc

    async def get_text(self, url: str, **kwargs: Any) -> str:
        resp = await self.request("GET", url, **kwargs)
        return resp.text

    async def get_bytes(self, url: str, **kwargs: Any) -> bytes:
        resp = await self.request("GET", url, **kwargs)
        return resp.content
