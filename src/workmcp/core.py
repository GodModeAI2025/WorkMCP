"""Shared types, source names and helpers of the service layer."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .store import Record

SRC_BA = "ba_jobsuche"
SRC_BERUFENET = "berufenet"
SRC_ENTGELT = "entgeltatlas"
SRC_ESCO = "esco"
SRC_ONET = "onet"
SRC_KLDB = "kldb"
SRC_KLDB_ISCO = "kldb_isco"
SRC_ESCO_ONET = "esco_onet"
SRC_ARBEITNOW = "arbeitnow"
SRC_HN = "hackernews"
SRC_CC = "commoncrawl"
SRC_ATS = "ats"
SRC_ADZUNA = "adzuna"
SRC_EXTRACTION = "extraktion"

PERSONAL_KEY_PARTS = ("kontakt", "ansprechpartner", "telefon", "email", "e-mail", "bewerbung")
SYSTEMS = ("kldb", "isco", "esco", "onet", "berufenet")
CROSSWALK_GRAPH = {
    "kldb": ("isco", "berufenet"),
    "isco": ("kldb", "esco"),
    "esco": ("isco", "onet"),
    "onet": ("esco",),
    "berufenet": ("kldb",),
}
_REL_RE = re.compile(r"^(\d+)\s*([mhdw])$")


@dataclass
class Item:
    key: str
    data: Any
    title: str | None = None
    text: str | None = None
    origin: str | None = None


@dataclass
class OpResult:
    records: list[Record]
    from_cache: bool
    stand: str | None
    delta: dict[str, Any] | None = None
    warning: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def memory(self) -> dict[str, Any]:
        out: dict[str, Any] = {"aus_speicher": self.from_cache, "stand": self.stand}
        if self.delta is not None:
            out["delta"] = self.delta
        if self.warning:
            out["warnung"] = self.warning
        return out


@dataclass
class Resolution:
    eingabe: str
    berufenet: list[str] = field(default_factory=list)
    kldb: list[str] = field(default_factory=list)
    isco: list[str] = field(default_factory=list)
    esco: list[str] = field(default_factory=list)
    onet: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    hinweise: list[str] = field(default_factory=list)

    def add(self, system: str, code: str | None, label: str | None = None) -> None:
        if not code:
            return
        target: list[str] = getattr(self, system)
        if code not in target:
            target.append(code)
        if label:
            self.labels[f"{system}:{code}"] = label

    def as_dict(self) -> dict[str, Any]:
        def entries(system: str) -> list[dict[str, Any]]:
            return [{"code": c, "titel": self.labels.get(f"{system}:{c}")} for c in getattr(self, system)]

        out: dict[str, Any] = {"eingabe": self.eingabe}
        for system in SYSTEMS:
            if getattr(self, system):
                out[system] = entries(system)
        if self.hinweise:
            out["hinweise"] = self.hinweise
        return out


def strip_personal(data: Any) -> Any:
    """Drop contact persons and similar personal data from job ad payloads (data minimisation)."""
    if isinstance(data, dict):
        return {
            k: strip_personal(v) for k, v in data.items() if not any(part in k.lower() for part in PERSONAL_KEY_PARTS)
        }
    if isinstance(data, list):
        return [strip_personal(v) for v in data]
    return data


def parse_since(value: str | None) -> str | None:
    """'24h', '7d', '30m', '2w', an ISO date or timestamp -> ISO timestamp (UTC)."""
    if not value:
        return None
    text = value.strip().lower()
    m = _REL_RE.match(text)
    if m:
        amount, unit = int(m.group(1)), m.group(2)
        delta = {
            "m": timedelta(minutes=amount),
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount),
            "w": timedelta(weeks=amount),
        }[unit]
        return (datetime.now(timezone.utc) - delta).replace(microsecond=0).isoformat()
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"Zeitangabe nicht verstanden: {value!r} (z. B. '24h', '7d', '2026-10-01')") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(microsecond=0).isoformat()


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _join(*parts: Any) -> str:
    return " ".join(str(p) for p in parts if p)


def _compact(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}
