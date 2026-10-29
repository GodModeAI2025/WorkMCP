"""Adzuna API (optional; free developer key: app_id/app_key from developer.adzuna.com).

Endpoints (country code in the path, e.g. ``de``): ``jobs/{c}/search/{page}``, ``jobs/{c}/histogram``,
``jobs/{c}/top_companies``, ``jobs/{c}/history``.  Salaries are *advertised* salaries from job ads
(partly predicted by Adzuna, see ``salary_is_predicted``), not official statistics.
"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from ..http import HttpClient

ADZUNA_HINT = (
    "Adzuna ist nicht konfiguriert. Kostenlosen Developer-Key unter https://developer.adzuna.com anlegen und "
    "WORKMCP_ADZUNA_APP_ID / WORKMCP_ADZUNA_APP_KEY setzen."
)


class AdzunaNotConfigured(RuntimeError):
    pass


def normalize_adzuna_job(job: dict[str, Any]) -> dict[str, Any]:
    loc = job.get("location") or {}
    return {
        "id": str(job.get("id") or ""),
        "titel": job.get("title"),
        "arbeitgeber": (job.get("company") or {}).get("display_name"),
        "ort": loc.get("display_name"),
        "kategorie": (job.get("category") or {}).get("label"),
        "gehalt_min": job.get("salary_min"),
        "gehalt_max": job.get("salary_max"),
        "gehalt_geschaetzt": job.get("salary_is_predicted") == "1",
        "vertragsart": job.get("contract_type"),
        "arbeitszeit": job.get("contract_time"),
        "erstellt": job.get("created"),
        "url": job.get("redirect_url"),
        "beschreibung": job.get("description"),
    }


def location_params(standort: list[str] | None) -> dict[str, str]:
    return {f"location{i}": part for i, part in enumerate(standort or [])}


class AdzunaClient:
    def __init__(self, http: HttpClient, settings: Settings):
        self.http = http
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.adzuna_app_id and self.settings.adzuna_app_key)

    def _auth(self) -> dict[str, str]:
        if not self.configured:
            raise AdzunaNotConfigured(ADZUNA_HINT)
        return {"app_id": self.settings.adzuna_app_id or "", "app_key": self.settings.adzuna_app_key or ""}

    def _url(self, endpoint: str) -> str:
        return f"{self.settings.adzuna_base}/jobs/{self.settings.adzuna_country}/{endpoint}"

    async def search(self, what: str, where: str | None = None, page: int = 1, per_page: int = 20) -> dict[str, Any]:
        params = {
            **self._auth(),
            "what": what,
            "where": where,
            "results_per_page": per_page,
            "content-type": "application/json",
        }
        return await self.http.get_json(self._url(f"search/{page}"), params=params)

    async def histogram(self, what: str, standort: list[str] | None = None) -> dict[str, Any]:
        params = {**self._auth(), "what": what, **location_params(standort)}
        return await self.http.get_json(self._url("histogram"), params=params)

    async def top_companies(self, what: str, standort: list[str] | None = None) -> dict[str, Any]:
        params = {**self._auth(), "what": what, **location_params(standort)}
        return await self.http.get_json(self._url("top_companies"), params=params)

    async def history(
        self, category: str | None, standort: list[str] | None = None, months: int = 12
    ) -> dict[str, Any]:
        params = {**self._auth(), "category": category, "months": months, **location_params(standort)}
        return await self.http.get_json(self._url("history"), params=params)
