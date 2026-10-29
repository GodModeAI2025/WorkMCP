"""ESCO web service API (European Commission), HAL+JSON responses.

Relations of a resource are listed in ``_links`` keyed by relation name, e.g. ``hasEssentialSkill``,
``hasOptionalSkill``, ``broaderIscoGroup`` – each value is a link object or a list of link objects
with ``uri``/``title``/``href``.
"""

from __future__ import annotations

import re
from typing import Any

from ..config import Settings
from ..http import HttpClient

OCCUPATION_PREFIX = "http://data.europa.eu/esco/occupation/"
SKILL_PREFIX = "http://data.europa.eu/esco/skill/"
ISCO_PREFIX = "http://data.europa.eu/esco/isco/C"

_ISCO_FROM_CODE = re.compile(r"^(\d{4})")


def esco_label(doc: dict[str, Any], language: str) -> str | None:
    if isinstance(doc.get("title"), str):
        return doc["title"]
    labels = doc.get("preferredLabel")
    if isinstance(labels, dict):
        for lang in (language, "de", "en"):
            if isinstance(labels.get(lang), str):
                return labels[lang]
        for v in labels.values():
            if isinstance(v, str):
                return v
    if isinstance(labels, str):
        return labels
    return None


def esco_description(doc: dict[str, Any], language: str) -> str | None:
    desc = doc.get("description")
    if isinstance(desc, dict):
        for lang in (language, "de", "en"):
            entry = desc.get(lang)
            if isinstance(entry, dict) and isinstance(entry.get("literal"), str):
                return entry["literal"]
            if isinstance(entry, str):
                return entry
    if isinstance(desc, str):
        return desc
    return None


def alt_labels(doc: dict[str, Any], language: str) -> list[str]:
    labels = doc.get("alternativeLabel") or doc.get("alternativeLabels")
    if isinstance(labels, dict):
        vals = labels.get(language) or labels.get("de") or labels.get("en") or []
        return [v for v in vals if isinstance(v, str)]
    if isinstance(labels, list):
        return [v for v in labels if isinstance(v, str)]
    return []


def links(doc: dict[str, Any], *names: str, contains: str | None = None) -> list[dict[str, Any]]:
    """Link objects of the given relation names (or all relations whose name contains ``contains``)."""
    raw = doc.get("_links") or {}
    out: list[dict[str, Any]] = []
    for rel, value in raw.items():
        if rel in names or (contains and contains.lower() in rel.lower()):
            entries = value if isinstance(value, list) else [value]
            for e in entries:
                if isinstance(e, dict) and (e.get("uri") or e.get("href")):
                    out.append({"uri": e.get("uri") or e.get("href"), "titel": e.get("title"), "relation": rel})
    return out


def isco_code_of(doc: dict[str, Any]) -> str | None:
    code = doc.get("code")
    if isinstance(code, str):
        m = _ISCO_FROM_CODE.match(code)
        if m:
            return m.group(1)
    for link in links(doc, "broaderIscoGroup"):
        uri = str(link["uri"])
        if uri.startswith(ISCO_PREFIX):
            return uri[len(ISCO_PREFIX) :][:4]
    return None


def normalize_search(raw: dict[str, Any], language: str) -> tuple[list[dict[str, Any]], int | None]:
    results = (raw.get("_embedded") or {}).get("results") or []
    out = []
    for r in results:
        if not isinstance(r, dict) or not r.get("uri"):
            continue
        out.append(
            {
                "uri": r["uri"],
                "titel": esco_label(r, language),
                "typ": r.get("className") or r.get("type"),
                "code": r.get("code"),
            }
        )
    total = raw.get("total")
    return out, int(total) if isinstance(total, (int, str)) and str(total).isdigit() else None


def normalize_occupation(raw: dict[str, Any], language: str) -> dict[str, Any]:
    def compact(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen, out = set(), []
        for i in items:
            if i["uri"] not in seen:
                seen.add(i["uri"])
                out.append({"uri": i["uri"], "titel": i["titel"]})
        return out

    isco = isco_code_of(raw)
    return {
        "uri": raw.get("uri"),
        "titel": esco_label(raw, language),
        "beschreibung": esco_description(raw, language),
        "code": raw.get("code"),
        "isco_code": isco,
        "alternative_titel": alt_labels(raw, language)[:25],
        "essential_skills": compact(links(raw, contains="essential")),
        "optional_skills": compact(links(raw, contains="optional")),
        "uebergeordnet": compact(links(raw, "broaderOccupation", "broaderIscoGroup")),
        "untergeordnet": compact(links(raw, "narrowerOccupation")),
    }


def normalize_skill(raw: dict[str, Any], language: str) -> dict[str, Any]:
    skill_type = None
    for link in links(raw, "hasSkillType"):
        skill_type = link["titel"] or link["uri"]
    return {
        "uri": raw.get("uri"),
        "titel": esco_label(raw, language),
        "beschreibung": esco_description(raw, language),
        "typ": skill_type,
        "alternative_titel": alt_labels(raw, language)[:15],
        "uebergeordnet": [
            {"uri": x["uri"], "titel": x["titel"]} for x in links(raw, "broaderSkill", "broaderHierarchyConcept")
        ],
        "essenziell_fuer": len(links(raw, contains="essentialfor")),
        "optional_fuer": len(links(raw, contains="optionalfor")),
    }


def normalize_isco_group(raw: dict[str, Any], language: str) -> dict[str, Any]:
    occupations = [x for x in links(raw, contains="narrower") if str(x["uri"]).startswith(OCCUPATION_PREFIX)]
    uri = str(raw.get("uri") or "")
    return {
        "uri": uri,
        "code": raw.get("code") or (uri[len(ISCO_PREFIX) :] if uri.startswith(ISCO_PREFIX) else None),
        "titel": esco_label(raw, language),
        "berufe": [{"uri": x["uri"], "titel": x["titel"]} for x in occupations],
    }


class EscoClient:
    def __init__(self, http: HttpClient, settings: Settings):
        self.http = http
        self.settings = settings

    def _params(self, **params: Any) -> dict[str, Any]:
        if self.settings.esco_version:
            params["selectedVersion"] = self.settings.esco_version
        return params

    async def search(
        self, text: str, *, type_: str = "occupation", language: str = "de", limit: int = 10, offset: int = 0
    ) -> dict[str, Any]:
        raw = await self.http.get_json(
            self.settings.esco_base + "/search",
            params=self._params(text=text, type=type_, language=language, limit=limit, offset=offset, full="false"),
        )
        return raw if isinstance(raw, dict) else {}

    async def resource(self, uri: str, *, kind: str = "occupation", language: str = "de") -> dict[str, Any]:
        raw = await self.http.get_json(
            f"{self.settings.esco_base}/resource/{kind}", params=self._params(uri=uri, language=language)
        )
        return raw if isinstance(raw, dict) else {}

    async def related(self, uri: str, relation: str, *, language: str = "de", limit: int = 100) -> dict[str, Any]:
        raw = await self.http.get_json(
            f"{self.settings.esco_base}/resource/related",
            params=self._params(uri=uri, relation=relation, language=language, limit=limit),
        )
        return raw if isinstance(raw, dict) else {}


def isco_uri(code: str) -> str:
    return f"{ISCO_PREFIX}{code}"
