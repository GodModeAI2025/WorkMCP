"""Public job-board APIs of applicant tracking systems (no authentication).

Endpoints, response shapes and quirks follow the live-verified reference
https://github.com/conorscode/ats-api-reference (verified 2026-08-04):

* Greenhouse      GET  boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true   (HTML double-encoded)
* Lever           GET  api.lever.co/v0/postings/{slug}?mode=json                      (bare array, ms timestamps)
* Ashby           GET  api.ashbyhq.com/posting-api/job-board/{slug}                   (titles need trimming)
* Workday         POST {tenant}.{shard}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs (only from a board URL)
* SmartRecruiters GET  api.smartrecruiters.com/v1/companies/{id}/postings             (offset paging, no text)
* Workable        GET  apply.workable.com/api/v1/widget/accounts/{slug}?details=true
* Recruitee       GET  {slug}.recruitee.com/api/offers/
* Personio        GET  {slug}.jobs.personio.de/xml                                    (XML, 307 for non-customers)
* BambooHR        GET  {slug}.bamboohr.com/careers/list                               (302 for non-customers)
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from ..config import Settings
from ..http import HttpClient, NotFoundError, SourceError
from ..textutil import html_to_text

PLATFORMS = (
    "greenhouse",
    "lever",
    "ashby",
    "workable",
    "recruitee",
    "personio",
    "smartrecruiters",
    "bamboohr",
    "workday",
)
# order used when the platform is unknown (Workday cannot be guessed from a slug)
DETECT_ORDER = ("greenhouse", "lever", "ashby", "workable", "recruitee", "personio", "smartrecruiters", "bamboohr")

_WORKDAY_RE = re.compile(r"^(?P<tenant>[\w-]+)\.(?P<shard>wd\d+)\.myworkdayjobs\.com$")


class NotOnPlatform(SourceError):
    """The company does not use this ATS (404 or redirect to the vendor's marketing site)."""


def detect_from_url(url: str) -> dict[str, str] | None:
    """Platform and identifiers from a careers-board URL, e.g. https://jobs.lever.co/palantir."""
    parts = urlsplit(url if "://" in url else f"https://{url}")
    host = (parts.hostname or "").lower()
    segs = [s for s in parts.path.split("/") if s]
    first = segs[0] if segs else ""
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io", "boards-api.greenhouse.io"):
        slug = segs[2] if host == "boards-api.greenhouse.io" and len(segs) > 2 else first
        return {"ats": "greenhouse", "slug": slug} if slug else None
    if host in ("jobs.lever.co", "api.lever.co"):
        slug = segs[2] if host == "api.lever.co" and len(segs) > 2 else first
        return {"ats": "lever", "slug": slug} if slug else None
    if host in ("jobs.ashbyhq.com",):
        return {"ats": "ashby", "slug": first} if first else None
    if host in ("apply.workable.com",):
        return {"ats": "workable", "slug": first} if first else None
    if host in ("jobs.smartrecruiters.com", "careers.smartrecruiters.com"):
        return {"ats": "smartrecruiters", "slug": first} if first else None
    if host.endswith(".recruitee.com"):
        return {"ats": "recruitee", "slug": host.split(".")[0]}
    if host.endswith(".jobs.personio.de") or host.endswith(".jobs.personio.com"):
        return {"ats": "personio", "slug": host.split(".")[0]}
    if host.endswith(".bamboohr.com"):
        return {"ats": "bamboohr", "slug": host.split(".")[0]}
    m = _WORKDAY_RE.match(host)
    if m:
        site = next((s for s in segs if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", s)), "")
        if site:
            return {
                "ats": "workday",
                "slug": f"{m['tenant']}/{site}",
                "tenant": m["tenant"],
                "shard": m["shard"],
                "site": site,
            }
    return None


def _iso_from_ms(value: Any) -> str | None:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
    return value if isinstance(value, str) else None


def _clean(text: str | None, limit: int = 6000) -> str | None:
    return html_to_text(text, limit=limit) if text else None


def _job(platform: str, slug: str, job_id: Any, **fields: Any) -> dict[str, Any]:
    orte = [o for o in (fields.pop("orte", None) or []) if o]
    return {
        "plattform": platform,
        "firma_slug": slug,
        "job_id": str(job_id),
        "titel": (fields.pop("titel", None) or "").strip() or None,
        "orte": list(dict.fromkeys(orte)),
        **fields,
    }


def normalize_greenhouse(raw: dict[str, Any], slug: str) -> list[dict[str, Any]]:
    out = []
    for j in raw.get("jobs") or []:
        content = j.get("content")
        if isinstance(content, str):
            content = html.unescape(html.unescape(content))  # double entity-encoded
        out.append(
            _job(
                "greenhouse",
                slug,
                j.get("id"),
                titel=j.get("title"),
                firma=j.get("company_name"),
                abteilung=", ".join(d.get("name", "") for d in j.get("departments") or [] if isinstance(d, dict))
                or None,
                orte=[(j.get("location") or {}).get("name")]
                + [o.get("name") for o in j.get("offices") or [] if isinstance(o, dict)],
                url=j.get("absolute_url"),
                veroeffentlicht=j.get("first_published"),
                aktualisiert=j.get("updated_at"),
                beschreibung=_clean(content),
            )
        )
    return out


def normalize_lever(raw: Any, slug: str) -> list[dict[str, Any]]:
    out = []
    for j in raw if isinstance(raw, list) else []:
        cat = j.get("categories") or {}
        workplace = j.get("workplaceType")
        out.append(
            _job(
                "lever",
                slug,
                j.get("id"),
                titel=j.get("text"),
                abteilung=cat.get("department"),
                team=cat.get("team"),
                orte=list(cat.get("allLocations") or []) or [cat.get("location")],
                remote=True if workplace == "remote" else (False if workplace in ("onsite", "on-site") else None),
                arbeitsmodell=workplace,
                anstellungsart=cat.get("commitment"),
                url=j.get("hostedUrl"),
                bewerbungs_url=j.get("applyUrl"),
                veroeffentlicht=_iso_from_ms(j.get("createdAt")),
                beschreibung=_clean(j.get("descriptionPlain") or j.get("description")),
            )
        )
    return out


def normalize_ashby(raw: dict[str, Any], slug: str) -> list[dict[str, Any]]:
    out = []
    for j in raw.get("jobs") or []:
        comp = j.get("compensation") or {}
        out.append(
            _job(
                "ashby",
                slug,
                j.get("id"),
                titel=j.get("title"),
                abteilung=j.get("department"),
                team=j.get("team"),
                orte=[j.get("location")]
                + [s.get("location") for s in j.get("secondaryLocations") or [] if isinstance(s, dict)],
                remote=j.get("isRemote"),
                arbeitsmodell=j.get("workplaceType"),
                anstellungsart=j.get("employmentType"),
                gehalt=comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary"),
                url=j.get("jobUrl"),
                bewerbungs_url=j.get("applyUrl"),
                veroeffentlicht=j.get("publishedAt"),
                beschreibung=_clean(j.get("descriptionPlain") or j.get("descriptionHtml")),
            )
        )
    return out


def normalize_workable(raw: dict[str, Any], slug: str) -> list[dict[str, Any]]:
    out = []
    for j in raw.get("jobs") or []:
        ort = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
        out.append(
            _job(
                "workable",
                slug,
                j.get("shortcode") or j.get("id"),
                titel=j.get("title"),
                firma=raw.get("name"),
                abteilung=j.get("department"),
                orte=[ort],
                remote=j.get("telecommuting"),
                anstellungsart=j.get("employment_type"),
                url=j.get("url") or j.get("shortlink"),
                bewerbungs_url=j.get("application_url"),
                veroeffentlicht=j.get("published_on"),
                beschreibung=_clean(j.get("description")),
            )
        )
    return out


def normalize_recruitee(raw: dict[str, Any], slug: str) -> list[dict[str, Any]]:
    out = []
    for j in raw.get("offers") or []:
        locs = [
            ", ".join(x for x in (loc.get("city"), loc.get("country")) if x)
            for loc in j.get("locations") or []
            if isinstance(loc, dict)
        ]
        text = " ".join(x for x in (j.get("description"), j.get("requirements")) if isinstance(x, str))
        out.append(
            _job(
                "recruitee",
                slug,
                j.get("id") or j.get("guid"),
                titel=j.get("title"),
                firma=j.get("company_name"),
                abteilung=j.get("department"),
                orte=locs or [j.get("city")],
                remote=j.get("remote"),
                anstellungsart=j.get("employment_type_code"),
                erfahrung=j.get("experience_code"),
                url=j.get("careers_url"),
                veroeffentlicht=j.get("published_at"),
                beschreibung=_clean(text),
            )
        )
    return out


def normalize_smartrecruiters(raw: dict[str, Any], slug: str) -> list[dict[str, Any]]:
    out = []
    for j in raw.get("content") or []:
        loc = j.get("location") or {}

        def label(key: str, j: dict[str, Any] = j) -> Any:
            v = j.get(key)
            return v.get("label") if isinstance(v, dict) else v

        out.append(
            _job(
                "smartrecruiters",
                slug,
                j.get("id"),
                titel=j.get("name"),
                firma=(j.get("company") or {}).get("name"),
                abteilung=label("department"),
                orte=[loc.get("fullLocation") or ", ".join(x for x in (loc.get("city"), loc.get("country")) if x)],
                remote=loc.get("remote"),
                anstellungsart=label("typeOfEmployment"),
                seniority=label("experienceLevel"),
                url=f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}" if j.get("id") else None,
                veroeffentlicht=j.get("releasedDate"),
            )
        )
    return out


def normalize_bamboohr(raw: dict[str, Any], slug: str) -> list[dict[str, Any]]:
    out = []
    for j in raw.get("result") or []:
        loc = j.get("location") or {}
        out.append(
            _job(
                "bamboohr",
                slug,
                j.get("id"),
                titel=j.get("jobOpeningName"),
                abteilung=j.get("departmentLabel"),
                orte=[", ".join(x for x in (loc.get("city"), loc.get("state")) if x)],
                remote=j.get("isRemote"),
                anstellungsart=j.get("employmentStatusLabel"),
                url=f"https://{slug}.bamboohr.com/careers/{j.get('id')}" if j.get("id") else None,
            )
        )
    return out


def normalize_personio(xml_text: str, slug: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceError(f"Personio-Feed von {slug} ist kein gültiges XML: {exc}") from exc
    if root.tag != "workzag-jobs":
        raise NotOnPlatform(f"{slug} ist kein Personio-Karriereportal")
    out = []
    for pos in root.findall("position"):

        def text(tag: str, pos: ET.Element = pos) -> str | None:
            el = pos.find(tag)
            return el.text.strip() if el is not None and el.text and el.text.strip() else None

        offices = [text("office")] + [o.text.strip() for o in pos.findall("additionalOffices/office") if o.text]
        orte = [part.strip() for o in offices if o for part in o.split(",")]
        beschreibung = " ".join(
            f"{d.findtext('name') or ''}: {d.findtext('value') or ''}"
            for d in pos.findall("jobDescriptions/jobDescription")
        )
        out.append(
            _job(
                "personio",
                slug,
                text("id"),
                titel=text("name"),
                firma=text("subcompany"),
                abteilung=text("department"),
                kategorie=text("recruitingCategory"),
                orte=orte,
                anstellungsart=text("employmentType"),
                seniority=text("seniority"),
                arbeitszeit=text("schedule"),
                erfahrung=text("yearsOfExperience"),
                beruf=text("occupation") or text("occupationCategory"),
                schlagworte=text("keywords"),
                url=f"https://{slug}.jobs.personio.de/job/{text('id')}" if text("id") else None,
                veroeffentlicht=text("createdAt"),
                beschreibung=_clean(beschreibung) if beschreibung.strip(": ") else None,
            )
        )
    return out


def normalize_workday(raw: dict[str, Any], tenant: str, shard: str, site: str) -> list[dict[str, Any]]:
    slug = f"{tenant}/{site}"
    out = []
    for j in raw.get("jobPostings") or []:
        path = j.get("externalPath") or ""
        bullets = j.get("bulletFields") or []
        out.append(
            _job(
                "workday",
                slug,
                path.rsplit("_", 1)[-1] if "_" in path else path or j.get("title"),
                titel=j.get("title"),
                orte=[j.get("locationsText")],
                veroeffentlicht_text=j.get("postedOn"),
                referenz=bullets[-1] if bullets else None,
                url=f"https://{tenant}.{shard}.myworkdayjobs.com/{site}{path}" if path else None,
            )
        )
    return out


class AtsClient:
    def __init__(self, http: HttpClient, settings: Settings):
        self.http = http
        self.settings = settings

    async def fetch(
        self, ats: str, slug: str, *, workday: dict[str, str] | None = None, max_jobs: int = 500
    ) -> list[dict[str, Any]]:
        """Normalized open jobs of one company on one ATS.  Raises NotOnPlatform if the slug is unknown."""
        try:
            return await self._fetch(ats, slug, workday, max_jobs)
        except NotFoundError as exc:
            raise NotOnPlatform(f"{slug} nicht bei {ats} gefunden") from exc

    async def _fetch(self, ats: str, slug: str, workday: dict[str, str] | None, max_jobs: int) -> list[dict[str, Any]]:
        get = self.http.get_json
        if ats == "greenhouse":
            raw = await get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"})
            return normalize_greenhouse(raw, slug)
        if ats == "lever":
            return normalize_lever(await get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}), slug)
        if ats == "ashby":
            raw = await get(
                f"https://api.ashbyhq.com/posting-api/job-board/{slug}", params={"includeCompensation": "true"}
            )
            return normalize_ashby(raw, slug)
        if ats == "workable":
            raw = await get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}", params={"details": "true"})
            return normalize_workable(raw, slug)
        if ats == "recruitee":
            return normalize_recruitee(await get(f"https://{slug}.recruitee.com/api/offers/"), slug)
        if ats == "smartrecruiters":
            jobs: list[dict[str, Any]] = []
            offset = 0
            while len(jobs) < max_jobs:
                raw = await get(
                    f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
                    params={"limit": 100, "offset": offset},
                )
                page = normalize_smartrecruiters(raw, slug)
                jobs.extend(page)
                offset += len(page)
                if not page or offset >= int(raw.get("totalFound") or 0):
                    break
            return jobs[:max_jobs]
        if ats == "personio":
            resp = await self.http.request("GET", f"https://{slug}.jobs.personio.de/xml")
            if resp.history or urlsplit(str(resp.url)).hostname != f"{slug}.jobs.personio.de":
                raise NotOnPlatform(f"{slug} ist kein Personio-Kunde (Weiterleitung auf {resp.url})")
            return normalize_personio(resp.text, slug)
        if ats == "bamboohr":
            resp = await self.http.request("GET", f"https://{slug}.bamboohr.com/careers/list")
            if resp.history or urlsplit(str(resp.url)).hostname != f"{slug}.bamboohr.com":
                raise NotOnPlatform(f"{slug} ist kein BambooHR-Kunde (Weiterleitung auf {resp.url})")
            return normalize_bamboohr(resp.json(), slug)
        if ats == "workday":
            if not workday:
                raise ValueError(
                    "Workday braucht die Karriereseiten-URL (Tenant, Shard und Site lassen sich nicht "
                    "aus dem Firmennamen ableiten), z. B. https://intel.wd1.myworkdayjobs.com/External"
                )
            base = f"https://{workday['tenant']}.{workday['shard']}.myworkdayjobs.com/wday/cxs/{workday['tenant']}"
            jobs = []
            offset, total = 0, None
            while len(jobs) < max_jobs:
                resp = await self.http.request(
                    "POST", f"{base}/{workday['site']}/jobs", json={"limit": 20, "offset": offset, "searchText": ""}
                )
                raw = resp.json()
                if total is None:
                    total = int(raw.get("total") or 0)
                page = normalize_workday(raw, workday["tenant"], workday["shard"], workday["site"])
                jobs.extend(page)
                offset += len(page)
                if not page or offset >= total:
                    break
            return jobs[:max_jobs]
        raise ValueError(f"Unbekanntes ATS {ats!r}. Unterstützt: {', '.join(PLATFORMS)}")
