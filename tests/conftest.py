from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx
import pytest

from workmcp.config import Settings
from workmcp.http import HttpClient
from workmcp.service import KnowledgeService
from workmcp.store import KnowledgeStore


@pytest.fixture
def store() -> Iterator[KnowledgeStore]:
    s = KnowledgeStore(":memory:")
    yield s
    s.close()


Handler = Callable[[httpx.Request], Any]


class Router:
    """Minimal URL router for httpx.MockTransport; records every call."""

    def __init__(self) -> None:
        self.routes: list[tuple[str, re.Pattern[str], Handler]] = []
        self.calls: list[tuple[str, str]] = []

    def add(self, method: str, pattern: str, handler: Handler | Any) -> None:
        func = handler if callable(handler) else (lambda _req, value=handler: value)
        self.routes.insert(0, (method.upper(), re.compile(pattern), func))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append((request.method, url))
        for method, rx, handler in self.routes:
            if method == request.method and rx.search(url):
                result = handler(request)
                if isinstance(result, httpx.Response):
                    return result
                if isinstance(result, str):
                    return httpx.Response(200, text=result)
                return httpx.Response(200, json=result)
        return httpx.Response(404, json={"error": "keine Route", "url": url})

    def count(self, pattern: str) -> int:
        rx = re.compile(pattern)
        return sum(1 for _m, url in self.calls if rx.search(url))


@pytest.fixture
def router() -> Router:
    return Router()


@pytest.fixture
def settings(tmp_path) -> Settings:
    s = Settings()
    s.db_path = str(tmp_path / "knowledge.db")
    s.offline = False
    s.adzuna_app_id = None
    s.adzuna_app_key = None
    return s


@pytest.fixture
async def service(settings: Settings, router: Router) -> AsyncIterator[KnowledgeService]:
    http = HttpClient(transport=httpx.MockTransport(router), retries=1, min_interval=0, backoff=0)
    svc = KnowledgeService(settings, http=http)
    yield svc
    await svc.aclose()
