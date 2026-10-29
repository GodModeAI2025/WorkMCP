"""Runtime settings, read from environment variables (prefix ``WORKMCP_``)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(f"WORKMCP_{name}")
    return value if value not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    try:
        return float(raw) if raw is not None else default
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "ja", "on"}


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: _env("DB", str(Path.home() / ".workmcp" / "knowledge.db")) or "")
    offline: bool = field(default_factory=lambda: _env_bool("OFFLINE"))
    language: str = field(default_factory=lambda: _env("LANGUAGE", "de") or "de")

    # cache lifetimes: after this age a repeated identical request is fetched again
    ttl_jobs_hours: float = field(default_factory=lambda: _env_float("TTL_JOBS_HOURS", 6))
    ttl_details_hours: float = field(default_factory=lambda: _env_float("TTL_DETAILS_HOURS", 24))
    ttl_reference_days: float = field(default_factory=lambda: _env_float("TTL_REFERENCE_DAYS", 30))
    ttl_signals_hours: float = field(default_factory=lambda: _env_float("TTL_SIGNALS_HOURS", 24))

    http_timeout: float = field(default_factory=lambda: _env_float("HTTP_TIMEOUT", 30))
    user_agent: str = field(
        default_factory=lambda: (
            _env("USER_AGENT", f"WorkMCP/{__version__} (+https://github.com/GodModeAI2025/WorkMCP)") or ""
        )
    )

    # Arbeitsagentur (community-documented endpoints, see bundesAPI on GitHub)
    ba_jobsuche_base: str = field(
        default_factory=lambda: (
            _env("BA_JOBSUCHE_BASE", "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service") or ""
        )
    )
    ba_jobsuche_key: str = field(default_factory=lambda: _env("BA_JOBSUCHE_KEY", "jobboerse-jobsuche") or "")
    ba_berufenet_base: str = field(
        default_factory=lambda: _env("BA_BERUFENET_BASE", "https://rest.arbeitsagentur.de/infosysbub/bnet/pc/v1") or ""
    )
    ba_berufenet_key: str = field(default_factory=lambda: _env("BA_BERUFENET_KEY", "infosysbub-berufenet") or "")
    ba_entgeltatlas_base: str = field(
        default_factory=lambda: (
            _env("BA_ENTGELTATLAS_BASE", "https://rest.arbeitsagentur.de/infosysbub/entgeltatlas/pc/v1") or ""
        )
    )
    # client id of the Entgeltatlas web app; the bundesAPI docs also name an OAuth client id that is
    # accepted as X-API-Key, it is tried when the first key is rejected
    ba_entgeltatlas_key: str = field(default_factory=lambda: _env("BA_ENTGELTATLAS_KEY", "infosysbub-ega") or "")
    ba_entgeltatlas_fallback_key: str = field(
        default_factory=lambda: _env("BA_ENTGELTATLAS_FALLBACK_KEY", "c4f0d292-9d0f-4763-87dd-d3f9e78fb006") or ""
    )

    esco_base: str = field(default_factory=lambda: _env("ESCO_BASE", "https://ec.europa.eu/esco/api") or "")
    esco_version: str | None = field(default_factory=lambda: _env("ESCO_VERSION"))

    onet_base: str = field(
        default_factory=lambda: _env("ONET_BASE", "https://www.onetcenter.org/dl_files/database") or ""
    )
    onet_database_page: str = field(
        default_factory=lambda: _env("ONET_DATABASE_PAGE", "https://www.onetcenter.org/database.html") or ""
    )
    onet_version: str | None = field(default_factory=lambda: _env("ONET_VERSION"))

    arbeitnow_url: str = field(
        default_factory=lambda: _env("ARBEITNOW_URL", "https://www.arbeitnow.com/api/job-board-api") or ""
    )
    hn_base: str = field(default_factory=lambda: _env("HN_BASE", "https://hn.algolia.com/api/v1") or "")
    commoncrawl_index: str = field(
        default_factory=lambda: _env("COMMONCRAWL_INDEX", "https://index.commoncrawl.org") or ""
    )
    commoncrawl_data: str = field(
        default_factory=lambda: _env("COMMONCRAWL_DATA", "https://data.commoncrawl.org") or ""
    )

    # Adzuna (optional): free developer key from https://developer.adzuna.com – without it the tools stay inactive
    adzuna_app_id: str | None = field(default_factory=lambda: _env("ADZUNA_APP_ID"))
    adzuna_app_key: str | None = field(default_factory=lambda: _env("ADZUNA_APP_KEY"))
    adzuna_base: str = field(default_factory=lambda: _env("ADZUNA_BASE", "https://api.adzuna.com/v1/api") or "")
    adzuna_country: str = field(default_factory=lambda: _env("ADZUNA_COUNTRY", "de") or "de")

    # job details can contain contact persons; they are removed before storing unless enabled
    store_personal_data: bool = field(default_factory=lambda: _env_bool("STORE_PERSONAL_DATA"))

    # default target of export_knowledge('archivy'): an Archivy data directory (notes go into <dir>/WorkMCP)
    archivy_dir: str | None = field(default_factory=lambda: _env("ARCHIVY_DIR"))

    # optional default locations of reference files (URL or local path)
    kldb_source: str | None = field(default_factory=lambda: _env("KLDB_SOURCE"))
    kldb_isco_source: str | None = field(default_factory=lambda: _env("KLDB_ISCO_SOURCE"))
    esco_onet_source: str | None = field(default_factory=lambda: _env("ESCO_ONET_SOURCE"))
