"""Bundesagentur für Arbeit: Jobsuche, BERUFENET and Entgeltatlas.

The endpoints are the JSON backends of the BA web apps.  They are not an official, contractually
offered API; their documentation is maintained by the community project bundesAPI
(github.com/bundesAPI/jobsuche-api, /berufenet-api, /entgeltatlas-api).  The public client ids
used as ``X-API-Key`` come from that documentation and can be overridden via settings.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

from ..config import Settings
from ..http import HttpClient, NotFoundError, SourceError
from ..textutil import html_blocks, html_to_text, list_items, sections_by_heading

SEARCH_PATHS = ("/pc/v6/jobs", "/pc/v4/app/jobs", "/pc/v4/jobs")
DETAIL_PATHS = ("/pc/v4/jobdetails/{code}", "/pc/v3/jobdetails/{code}")
JOB_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
BERUFENET_URL = "https://web.arbeitsagentur.de/berufenet/beruf/{id}"

ANGEBOTSART = {"arbeit": 1, "selbstaendigkeit": 2, "selbständigkeit": 2, "ausbildung": 4, "praktikum": 34}
ARBEITSZEIT = {"vollzeit": "vz", "teilzeit": "tz", "schicht": "snw", "homeoffice": "ho", "minijob": "mj"}
BEFRISTUNG = {"befristet": 1, "unbefristet": 2}

ENTGELT_REGIONEN = {
    "deutschland": 1,
    "ostdeutschland": 2,
    "westdeutschland": 3,
    "schleswig-holstein": 4,
    "hamburg": 5,
    "niedersachsen": 6,
    "bremen": 7,
    "nordrhein-westfalen": 8,
    "nrw": 8,
    "hessen": 9,
    "rheinland-pfalz": 10,
    "baden-württemberg": 11,
    "baden-wuerttemberg": 11,
    "bayern": 12,
    "saarland": 13,
    "berlin": 14,
    "brandenburg": 15,
    "mecklenburg-vorpommern": 16,
    "sachsen": 17,
    "sachsen-anhalt": 18,
    "thüringen": 19,
    "thueringen": 19,
    "dresden": 20,
    "düsseldorf": 21,
    "duesseldorf": 21,
    "dortmund": 22,
    "essen": 23,
    "frankfurt am main": 24,
    "frankfurt": 24,
    "nürnberg": 25,
    "nuernberg": 25,
    "hannover": 26,
    "köln": 27,
    "koeln": 27,
    "leipzig": 28,
    "münchen": 29,
    "muenchen": 29,
    "stuttgart": 30,
}
ENTGELT_NIVEAUS = {"helfer": 1, "fachkraft": 2, "spezialist": 3, "experte": 4}
ENTGELT_GESCHLECHT = {"gesamt": 1, "männer": 2, "maenner": 2, "frauen": 3}
ENTGELT_ALTER = {"gesamt": 1, "unter 25": 2, "25 bis unter 55": 3, "ab 55": 4}
ENTGELT_BRANCHEN = {
    "gesamt": 1,
    "land- und forstwirtschaft, fischerei": 2,
    "produzierendes gewerbe ohne bau": 3,
    "baugewerbe": 4,
    "handel, verkehr, lagerei und gastgewerbe": 5,
    "information und kommunikation": 6,
    "finanz- und versicherungsgewerbe": 7,
    "grundstücks- und wohnungswesen": 8,
    "erbringung wirtschaftlicher dienstleistungen": 9,
    "öffentliche verwaltung, schul-, gesundheits-, sozialwesen": 10,
    "sonstige dienstleistungen": 11,
}

_KLDB_RE = re.compile(r"(?<!\d)(\d{5})(?!\d)")
_KLDB_ANY_RE = re.compile(r"(?<!\d)(\d{3,5})(?!\d)")


def resolve_code(value: int | str | None, mapping: dict[str, int], what: str) -> int | None:
    """Accept a numeric code or a (partial) German name and return the numeric code."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    if text.isdigit():
        return int(text)
    if text in mapping:
        return mapping[text]
    for name, code in mapping.items():
        if name.startswith(text) or text in name:
            return code
    raise ValueError(f"Unbekannte(r) {what}: {value!r}. Erlaubt: {', '.join(sorted(mapping))}")


# ----------------------------------------------------------------- Jobsuche


def build_search_params(
    *,
    was: str | None = None,
    wo: str | None = None,
    umkreis: int | None = None,
    berufsfeld: str | None = None,
    arbeitgeber: str | None = None,
    veroeffentlicht_seit: int | None = None,
    angebotsart: int | str | None = 1,
    befristung: Iterable[int | str] | int | str | None = None,
    arbeitszeit: Iterable[str] | str | None = None,
    zeitarbeit: bool | None = None,
    pav: bool | None = None,
    behinderung: bool | None = None,
    page: int = 1,
    size: int = 50,
) -> dict[str, Any]:
    def as_list(v: Any) -> list[Any]:
        if v is None:
            return []
        if isinstance(v, (str, int)):
            return [p for p in str(v).replace(",", ";").split(";") if p.strip()]
        return list(v)

    params: dict[str, Any] = {
        "was": was or None,
        "wo": wo or None,
        "umkreis": umkreis if wo else None,
        "berufsfeld": berufsfeld or None,
        "arbeitgeber": arbeitgeber or None,
        "veroeffentlichtseit": veroeffentlicht_seit,
        "angebotsart": resolve_code(angebotsart, ANGEBOTSART, "Angebotsart"),
        "page": max(1, page),
        "size": max(1, min(size, 100)),
    }
    if befristung is not None:
        codes = [
            str(resolve_code(b.strip() if isinstance(b, str) else b, BEFRISTUNG, "Befristung"))
            for b in as_list(befristung)
        ]
        params["befristung"] = ";".join(codes) or None
    if arbeitszeit is not None:
        codes = []
        for a in as_list(arbeitszeit):
            a = str(a).strip().lower()
            codes.append(ARBEITSZEIT.get(a, a))
        params["arbeitszeit"] = ";".join(codes) or None
    for name, flag in (("zeitarbeit", zeitarbeit), ("pav", pav), ("behinderung", behinderung)):
        if flag is not None:
            params[name] = "true" if flag else "false"
    return {k: v for k, v in params.items() if v is not None}


def job_refnr(item: dict[str, Any]) -> str | None:
    value = item.get("referenznummer") or item.get("refnr")
    return str(value) if value else None


def search_results(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Result list of a Jobsuche response: ``ergebnisliste`` (v6) or ``stellenangebote`` (v4)."""
    items = raw.get("ergebnisliste")
    if items is None:
        items = raw.get("stellenangebote")
    if items is None:
        items = (raw.get("_embedded") or {}).get("stellenangebote") or []
    return [i for i in items if isinstance(i, dict)]


def _period_start(value: Any) -> Any:
    return value.get("von") if isinstance(value, dict) else value


def _locations(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Locations from ``stellenlokationen`` (v6/new details), ``arbeitsorte`` or ``arbeitsort`` (v4)."""
    out: list[dict[str, Any]] = []
    for loc in item.get("stellenlokationen") or []:
        if isinstance(loc, dict):
            addr: dict[str, Any] = loc["adresse"] if isinstance(loc.get("adresse"), dict) else loc
            koord = loc.get("koordinaten") or addr.get("koordinaten") or {}
            out.append(
                {
                    "ort": addr.get("ort"),
                    "plz": addr.get("plz"),
                    "region": addr.get("region"),
                    "land": addr.get("land"),
                    "lat": koord.get("lat"),
                    "lon": koord.get("lon"),
                }
            )
    raw_list: Any = item.get("arbeitsorte") or item.get("arbeitsort") or []
    for loc in raw_list if isinstance(raw_list, list) else [raw_list]:
        if isinstance(loc, dict):
            koord = loc.get("koordinaten") or {}
            out.append(
                {
                    "ort": loc.get("ort"),
                    "plz": loc.get("plz"),
                    "region": loc.get("region"),
                    "land": loc.get("land"),
                    "lat": koord.get("lat"),
                    "lon": koord.get("lon"),
                }
            )
    for loc in out:
        if loc["plz"] is not None:
            loc["plz"] = str(loc["plz"])
    return out


def normalize_job_item(item: dict[str, Any]) -> dict[str, Any]:
    refnr = job_refnr(item) or ""
    orte = _locations(item)
    first = orte[0] if orte else {}
    return {
        "refnr": refnr,
        "titel": item.get("stellenangebotsTitel") or item.get("titel") or item.get("hauptberuf") or item.get("beruf"),
        "beruf": item.get("hauptberuf") or item.get("beruf"),
        "arbeitgeber": item.get("firma") or item.get("arbeitgeber"),
        "ort": first.get("ort"),
        "plz": first.get("plz"),
        "region": first.get("region"),
        "weitere_orte": len(orte) - 1 if len(orte) > 1 else None,
        "lat": first.get("lat"),
        "lon": first.get("lon"),
        "entfernung_km": item.get("entfernung"),
        "angebotsart": item.get("stellenangebotsart") or item.get("angebotsart"),
        "vollzeit": item.get("arbeitszeitVollzeit"),
        "homeoffice": item.get("homeofficetyp") if item.get("homeofficemoeglich") else None,
        "veroeffentlicht": _period_start(item.get("veroeffentlichungszeitraum"))
        or item.get("aktuelleVeroeffentlichungsdatum"),
        "eintritt": _period_start(item.get("eintrittszeitraum")) or item.get("eintrittsdatum"),
        "geaendert_am": item.get("aenderungsdatum") or item.get("modifikationsTimestamp"),
        "externe_url": item.get("externeUrl"),
        "url": JOB_URL.format(refnr=refnr) if refnr else None,
    }


def _skill_names(fertigkeiten: Any) -> list[str]:
    names: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, str):
            if v.strip() and v not in names:
                names.append(v.strip())
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for k, x in v.items():
                if k in ("hierarchieName",):
                    continue
                walk(x)

    for entry in fertigkeiten or []:
        if isinstance(entry, dict):
            walk(entry.get("auspraegungen"))
        else:
            walk(entry)
    return names


def find_dkz(doc: dict[str, Any]) -> str | None:
    """BERUFENET/DKZ occupation id of a job ad (``hauptDkz`` in v4, other ``*dkz*`` keys tolerated)."""
    for key, value in doc.items():
        if "dkz" in key.lower() and isinstance(value, (str, int)) and str(value).strip().isdigit():
            return str(value).strip()
    return None


def _no_info(value: Any) -> Any:
    return None if value in ("KEINE_ANGABEN", "KEINE_ANGABE", "") else value


def normalize_job_detail(detail: dict[str, Any]) -> dict[str, Any]:
    refnr = job_refnr(detail) or ""
    beschreibung = detail.get("stellenangebotsBeschreibung") or detail.get("stellenbeschreibung")
    partner = detail.get("allianzpartnerName")
    return {
        "refnr": refnr,
        "titel": detail.get("stellenangebotsTitel") or detail.get("titel"),
        "beruf": detail.get("hauptberuf") or detail.get("beruf"),
        "haupt_dkz": find_dkz(detail),
        "arbeitgeber": detail.get("firma") or detail.get("arbeitgeber"),
        "branche": detail.get("branche"),
        "branchengruppe": detail.get("branchengruppe"),
        "angebotsart": detail.get("stellenangebotsart") or detail.get("angebotsart"),
        "arbeitsorte": _locations(detail),
        "arbeitszeitmodelle": detail.get("arbeitszeitmodelle") or [],
        "befristung": detail.get("befristung") or _no_info(detail.get("vertragsdauer")),
        "verguetung": detail.get("verguetung") or detail.get("gehalt") or _no_info(detail.get("verguetungsangabe")),
        "anzahl_offene_stellen": detail.get("anzahlOffeneStellen"),
        "eintritt": _period_start(detail.get("eintrittszeitraum")) or detail.get("eintrittsdatum"),
        "veroeffentlicht": _period_start(detail.get("veroeffentlichungszeitraum"))
        or detail.get("aktuelleVeroeffentlichungsdatum"),
        "erstmals_veroeffentlicht": detail.get("datumErsteVeroeffentlichung")
        or detail.get("ersteVeroeffentlichungsdatum"),
        "geaendert_am": detail.get("aenderungsdatum") or detail.get("modifikationsTimestamp"),
        "zeitarbeit": detail.get("istZeitarbeit") if "istZeitarbeit" in detail else detail.get("zeitarbeit"),
        "private_vermittlung": detail.get("istPrivateArbeitsvermittlung"),
        "fertigkeiten": _skill_names(detail.get("fertigkeiten")),
        "beschreibung": html_to_text(beschreibung) if beschreibung else None,
        "externe_url": detail.get("externeUrl")
        or (detail.get("allianzpartnerUrl") if partner not in (None, "arbeitsagentur.de") else None),
        "url": JOB_URL.format(refnr=refnr) if refnr else None,
    }


def encode_refnr(refnr: str) -> str:
    return quote(base64.b64encode(refnr.encode("utf-8")).decode("ascii"), safe="=")


# ---------------------------------------------------------------- BERUFENET


def normalize_berufenet_list(raw: Any) -> tuple[list[dict[str, Any]], int | None]:
    items: list[Any] = []
    total: int | None = None
    if isinstance(raw, dict):
        embedded = raw.get("_embedded") or {}
        items = embedded.get("berufSucheList") or embedded.get("berufe") or raw.get("berufe") or []
        page = raw.get("page") or {}
        if isinstance(page, dict) and page.get("totalElements") is not None:
            total = int(page["totalElements"])
    elif isinstance(raw, list):
        items = raw
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        bid = it.get("id") or it.get("berufId")
        if bid is None:
            continue
        name = _first_str(
            it, ("kurzBezeichnungNeutral", "bezeichnungNeutral", "kurzBezeichnung", "bezeichnung", "name")
        )
        out.append({"id": str(bid), "name": name, "url": BERUFENET_URL.format(id=bid)})
    return out, total


def _first_str(doc: dict[str, Any], keys: Iterable[str]) -> str | None:
    for k in keys:
        v = doc.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def find_kldb(doc: Any) -> str | None:
    """Locate a KldB 2010 code anywhere in a BERUFENET document (keys containing 'kldb')."""
    found: list[str] = []

    def from_value(v: Any) -> None:
        if isinstance(v, (str, int)):
            text = str(v)
            m = _KLDB_RE.search(text) or _KLDB_ANY_RE.search(text)
            if m:
                found.append(m.group(1))
        elif isinstance(v, dict):
            for k in ("code", "codenr", "codeNr", "schluessel", "kldb2010", "id", "wert"):
                if k in v:
                    from_value(v[k])
                    if found:
                        return
            for x in v.values():
                from_value(x)
        elif isinstance(v, list):
            for x in v:
                from_value(x)

    def walk(v: Any) -> None:
        if found:
            return
        if isinstance(v, dict):
            for k, x in v.items():
                if "kldb" in str(k).lower():
                    from_value(x)
                    if found:
                        return
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(doc)
    return found[0] if found else None


_TITLE_KEYS = (
    "ueberschrift",
    "überschrift",
    "titel",
    "title",
    "name",
    "kurzBezeichnungNeutral",
    "bezeichnungNeutral",
    "bezeichnung",
    "label",
    "kurzBezeichnung",
)
_CONTENT_KEYS = ("inhalt", "content", "text", "beschreibung", "html", "value", "langtext", "infotext", "wert")


def _classify(title: str) -> str | None:
    t = title.lower()
    if "feld" in t and ("tätigkeit" in t or "taetigkeit" in t or "arbeit" in t):
        return "felder"
    if "aufgabe" in t or "tätigkeit" in t or "taetigkeit" in t:
        return "aufgaben"
    return None


def extract_berufenet_tasks(doc: Any, limit: int = 120) -> tuple[list[str], list[str]]:
    """Heuristically extract task statements and fields of activity from a BERUFENET document."""
    tasks: list[str] = []
    fields: list[str] = []

    def add(target: list[str], items: Iterable[str]) -> None:
        for item in items:
            item = item.strip()
            if 3 < len(item) < 600 and item not in target and len(target) < limit:
                target.append(item)

    def content_items(node: dict[str, Any]) -> list[str]:
        items: list[str] = []
        for key in _CONTENT_KEYS:
            v = node.get(key)
            if isinstance(v, str) and v.strip():
                items.extend(
                    list_items(v) or [t for kind, t in html_blocks(v) if kind != "heading"] or [html_to_text(v)]
                )
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, str):
                        items.append(html_to_text(x))
                    elif isinstance(x, dict):
                        t = _first_str(x, _TITLE_KEYS + _CONTENT_KEYS)
                        if t:
                            items.append(html_to_text(t))
        return items

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            title = _first_str(v, _TITLE_KEYS)
            kind = _classify(title) if title else None
            if kind:
                add(tasks if kind == "aufgaben" else fields, content_items(v))
            for k, x in v.items():
                key = str(k).lower()
                if "taetigkeitsfeld" in key or "tätigkeitsfeld" in key:
                    if isinstance(x, list):
                        add(
                            fields,
                            [
                                n
                                for n in (
                                    _first_str(i, _TITLE_KEYS)
                                    if isinstance(i, dict)
                                    else (i if isinstance(i, str) else None)
                                    for i in x
                                )
                                if n
                            ],
                        )
                    continue
                if isinstance(x, str) and "<h" in x and ("Aufgaben" in x or "Tätigkeit" in x):
                    for sec in sections_by_heading(x, ["Aufgaben", "Tätigkeit"]):
                        heading = str(sec["ueberschrift"])
                        punkte = [str(p) for p in sec["punkte"]]
                        add(fields if _classify(heading) == "felder" else tasks, punkte)
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(doc)
    return tasks, fields


def normalize_berufenet_detail(raw: Any, beruf_id: str | None = None) -> dict[str, Any]:
    doc: Any = raw[0] if isinstance(raw, list) and raw else raw
    if not isinstance(doc, dict):
        doc = {}
    bid = str(doc.get("id") or doc.get("berufId") or beruf_id or "")
    tasks, fields = extract_berufenet_tasks(doc)
    beschreibung = None
    for key in ("beschreibung", "kurzbeschreibung", "kurzBeschreibung"):
        if isinstance(doc.get(key), str):
            beschreibung = html_to_text(doc[key], limit=1500)
            break
    return {
        "id": bid,
        "name": _first_str(doc, ("kurzBezeichnungNeutral", "bezeichnungNeutral", "kurzBezeichnung", "bezeichnung")),
        "bezeichnung": _first_str(doc, ("bezeichnungNeutral", "bezeichnung", "bezeichnungMaennlich")),
        "kldb2010": find_kldb(doc),
        "codenr": _first_str(doc, ("codenr", "codeNr", "codeNummer")),
        "aufgaben": tasks,
        "taetigkeitsfelder": fields,
        "beschreibung": beschreibung,
        "url": BERUFENET_URL.format(id=bid) if bid else None,
    }


# ------------------------------------------------------------- Entgeltatlas


def normalize_entgelt(item: dict[str, Any]) -> dict[str, Any]:
    def label(key: str) -> Any:
        v = item.get(key)
        return v.get("bezeichnung") if isinstance(v, dict) else v

    region = item.get("region") if isinstance(item.get("region"), dict) else {}
    return {
        "kldb": item.get("kldb"),
        "region": label("region"),
        "geschlecht": label("gender"),
        "alter": label("ageCategory"),
        "niveau": label("performanceLevel"),
        "branche": label("branche"),
        "median_eur": item.get("entgelt"),
        "q25_eur": item.get("entgeltQ25"),
        "q75_eur": item.get("entgeltQ75"),
        "besetzung": item.get("besetzung"),
        "beitragsbemessungsgrenze_eur": region.get("beitragsBemessungsGrenze") if region else None,
    }


class ArbeitsagenturClient:
    def __init__(self, http: HttpClient, settings: Settings):
        self.http = http
        self.settings = settings
        self._search_path: str | None = None

    async def search_jobs(self, params: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """Returns (raw response, endpoint path used).  Falls back to older endpoint versions."""
        headers = {"X-API-Key": self.settings.ba_jobsuche_key}
        paths = [self._search_path] if self._search_path else list(SEARCH_PATHS)
        last: Exception | None = None
        for path in paths:
            if path is None:
                continue
            try:
                raw = await self.http.get_json(self.settings.ba_jobsuche_base + path, params=params, headers=headers)
            except NotFoundError as exc:
                last = exc
                continue
            except SourceError as exc:
                if exc.status in (405, 410):
                    last = exc
                    continue
                raise
            self._search_path = path
            return (raw if isinstance(raw, dict) else {"stellenangebote": raw}), path
        raise SourceError(f"Kein Jobsuche-Endpunkt erreichbar ({last})")

    async def job_details(self, refnr: str) -> dict[str, Any]:
        """Raises NotFoundError when no endpoint version knows the job ad (i.e. it is gone)."""
        headers = {"X-API-Key": self.settings.ba_jobsuche_key}
        code = encode_refnr(refnr)
        last: NotFoundError | None = None
        for path in DETAIL_PATHS:
            try:
                raw = await self.http.get_json(self.settings.ba_jobsuche_base + path.format(code=code), headers=headers)
            except NotFoundError as exc:
                last = exc
                continue
            if isinstance(raw, dict):
                return raw
        raise last or NotFoundError(f"Stellenanzeige {refnr} nicht gefunden")

    async def berufenet_search(self, suchwoerter: str, page: int = 0) -> Any:
        return await self.http.get_json(
            self.settings.ba_berufenet_base + "/berufe",
            params={"suchwoerter": suchwoerter, "page": page},
            headers={"X-API-Key": self.settings.ba_berufenet_key},
        )

    async def berufenet_beruf(self, beruf_id: str) -> Any:
        return await self.http.get_json(
            f"{self.settings.ba_berufenet_base}/berufe/{quote(str(beruf_id), safe='')}",
            headers={"X-API-Key": self.settings.ba_berufenet_key},
        )

    async def entgelte(self, kldb: str, params: dict[str, int | None]) -> list[dict[str, Any]]:
        """Rows of the Entgeltatlas for a KldB code (3–5 digits); params: l, r, g, a, b."""
        url = f"{self.settings.ba_entgeltatlas_base}/entgelte/{quote(kldb, safe='')}"
        keys = [self.settings.ba_entgeltatlas_key, self.settings.ba_entgeltatlas_fallback_key]
        raw: Any = None
        for i, key in enumerate(k for k in keys if k):
            try:
                raw = await self.http.get_json(url, params=params, headers={"X-API-Key": key})
                break
            except SourceError as exc:
                if exc.status in (401, 403) and i == 0:
                    continue
                raise
        if isinstance(raw, dict):
            raw = raw.get("entgelte") or raw.get("_embedded", {}).get("entgelte") or [raw]
        return [x for x in raw or [] if isinstance(x, dict)]
