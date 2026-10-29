"""Orchestration: fetch from the sources, remember everything in the store, build the graph.

Every fetching operation goes through :meth:`KnowledgeService._run`:

1. an identical request answered within its lifetime (TTL) is served from memory,
2. otherwise the source is asked; each returned record is upserted (new / changed / unchanged),
3. the answer carries a delta against the previous identical request – including records that
   are no longer contained (e.g. job ads that were taken offline),
4. if the source is unreachable, the last remembered state is returned with a warning.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from . import graph as g
from .config import Settings
from .core import (
    SRC_ADZUNA,
    SRC_ARBEITNOW,
    SRC_ATS,
    SRC_BA,
    SRC_BERUFENET,
    SRC_CC,
    SRC_ESCO,
    SRC_HN,
    SRC_KLDB,
    SRC_ONET,
    Item,
    OpResult,
    _compact,
    _int,
    _join,
    parse_since,
    strip_personal,
)
from .http import HttpClient, NotFoundError, SourceError
from .occupations import OccupationMixin
from .sources import adzuna as adz
from .sources import arbeitsagentur as ba
from .sources import ats as atsmod
from .sources import commoncrawl as ccmod
from .sources import esco, onet, signals
from .sources.adzuna import ADZUNA_HINT
from .store import EVENT_CHANGED, EVENT_NEW, EVENT_REAPPEARED, KnowledgeStore, UpsertResult, utcnow
from .textutil import truncate


class KnowledgeService(OccupationMixin):
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        store: KnowledgeStore | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        http: HttpClient | None = None,
    ):
        self.settings = settings or Settings()
        self.store = store or KnowledgeStore(self.settings.db_path)
        self.http = http or HttpClient(
            timeout=self.settings.http_timeout, user_agent=self.settings.user_agent, transport=transport
        )
        self.ba = ba.ArbeitsagenturClient(self.http, self.settings)
        self.esco = esco.EscoClient(self.http, self.settings)
        self.onet = onet.OnetClient(self.http, self.settings)
        self.hn = signals.HackerNewsClient(self.http, self.settings)
        self.arbeitnow = signals.ArbeitnowClient(self.http, self.settings)
        self.cc = ccmod.CommonCrawlClient(self.http, self.settings)
        self.ats = atsmod.AtsClient(self.http, self.settings)
        self.adzuna = adz.AdzunaClient(self.http, self.settings)

    async def aclose(self) -> None:
        await self.http.aclose()
        self.store.close()

    # ------------------------------------------------------------ core engine

    def _ttl(self, kind: str) -> timedelta:
        s = self.settings
        return {
            "jobs": timedelta(hours=s.ttl_jobs_hours),
            "details": timedelta(hours=s.ttl_details_hours),
            "reference": timedelta(days=s.ttl_reference_days),
            "signals": timedelta(hours=s.ttl_signals_hours),
        }[kind]

    async def _run(
        self,
        *,
        source: str,
        kind: str,
        operation: str,
        params: dict[str, Any],
        ttl: timedelta,
        refresh: bool,
        fetch: Callable[[], Awaitable[tuple[list[Item], dict[str, Any]]]],
        on_item: Callable[[Item], None] | None = None,
        hash_ignore: Iterable[str] = (),
    ) -> OpResult:
        last = self.store.last_run(operation, params)
        if last and (self.settings.offline or (not refresh and last.age() < ttl)):
            return OpResult(
                self.store.get_records(source, kind, last.result_keys),
                True,
                last.finished or last.started,
                meta=last.meta,
            )
        if self.settings.offline:
            return OpResult([], True, None, warning="Offline-Modus: Zu dieser Anfrage ist nichts gespeichert.")
        run_id = self.store.begin_run(source, operation, params)
        try:
            items, meta = await fetch()
        except (NotFoundError, atsmod.NotOnPlatform, ValueError, adz.AdzunaNotConfigured) as exc:
            self.store.finish_run(run_id, status="fehler", error=str(exc))
            raise
        except SourceError as exc:
            self.store.finish_run(run_id, status="fehler", error=str(exc))
            if last:
                return OpResult(
                    self.store.get_records(source, kind, last.result_keys),
                    True,
                    last.finished or last.started,
                    warning=f"Quelle nicht erreichbar ({exc}). Geliefert wird der gespeicherte Stand.",
                    meta=last.meta,
                )
            raise
        results: list[UpsertResult] = []
        seen: set[str] = set()
        with self.store.transaction():
            for item in items:
                if item.key in seen:
                    continue
                seen.add(item.key)
                results.append(
                    self.store.upsert_record(
                        source,
                        kind,
                        item.key,
                        item.data,
                        title=item.title,
                        text=item.text,
                        origin=item.origin,
                        run_id=run_id,
                        hash_ignore=hash_ignore,
                    )
                )
                if on_item:
                    on_item(item)
        keys = [r.key for r in results]
        current = set(keys)
        delta = {
            "erstabruf": last is None,
            "neu": [r.key for r in results if r.status == EVENT_NEW],
            "geaendert": [
                {"schluessel": r.key, "version": r.version, "aenderungen": r.changes[:8]}
                for r in results
                if r.status == EVENT_CHANGED
            ],
            "wieder_da": [r.key for r in results if r.status == EVENT_REAPPEARED],
            "unveraendert": sum(1 for r in results if r.status == "unveraendert"),
            "nicht_mehr_enthalten": [k for k in (last.result_keys if last else []) if k not in current],
        }
        self.store.finish_run(run_id, results=results, result_keys=keys, meta=meta)
        return OpResult(self.store.get_records(source, kind, keys), False, utcnow(), delta=delta, meta=meta)

    # --------------------------------------------------------------- job ads

    async def search_jobs(
        self,
        *,
        was: str | None = None,
        wo: str | None = None,
        umkreis: int | None = None,
        seiten: int = 1,
        groesse: int = 25,
        veroeffentlicht_seit: int | None = None,
        angebotsart: str | int | None = "arbeit",
        arbeitszeit: list[str] | None = None,
        befristung: str | None = None,
        berufsfeld: str | None = None,
        arbeitgeber: str | None = None,
        zeitarbeit: bool | None = None,
        aktualisieren: bool = False,
    ) -> dict[str, Any]:
        if not (was or wo or berufsfeld or arbeitgeber):
            raise ValueError("Bitte mindestens 'was', 'wo', 'berufsfeld' oder 'arbeitgeber' angeben.")
        stellen: list[dict[str, Any]] = []
        pages: list[dict[str, Any]] = []
        total = None
        for page in range(1, max(1, min(seiten, 10)) + 1):
            params = ba.build_search_params(
                was=was,
                wo=wo,
                umkreis=umkreis,
                berufsfeld=berufsfeld,
                arbeitgeber=arbeitgeber,
                veroeffentlicht_seit=veroeffentlicht_seit,
                angebotsart=angebotsart,
                befristung=befristung,
                arbeitszeit=arbeitszeit,
                zeitarbeit=zeitarbeit,
                page=page,
                size=groesse,
            )

            async def fetch(params: dict[str, Any] = params) -> tuple[list[Item], dict[str, Any]]:
                raw, path = await self.ba.search_jobs(params)
                items = []
                for it in ba.search_results(raw):
                    ref = ba.job_refnr(it)
                    if not ref:
                        continue
                    norm = ba.normalize_job_item(it)
                    items.append(
                        Item(
                            ref,
                            it,
                            norm["titel"],
                            _join(norm["titel"], norm["beruf"], norm["arbeitgeber"], norm["ort"]),
                            norm["url"],
                        )
                    )
                meta = {
                    "treffer_gesamt": _int(raw.get("maxErgebnisse")),
                    "endpunkt": path,
                    "ort_interpretiert": (raw.get("woOutput") or {}).get("bereinigterOrt"),
                }
                return items, meta

            res = await self._run(
                source=SRC_BA,
                kind="stelle",
                operation="ba.jobsuche",
                params=params,
                ttl=self._ttl("jobs"),
                refresh=aktualisieren,
                fetch=fetch,
                on_item=self._graph_ba_posting,
            )
            total = res.meta.get("treffer_gesamt", total)
            stellen.extend(_compact(ba.normalize_job_item(r.data)) for r in res.records)
            pages.append({"seite": page, **res.memory()})
            if len(res.records) < params["size"]:
                break
        return {
            "quelle": "Bundesagentur für Arbeit – Jobsuche",
            "treffer_gesamt": total,
            "anzahl": len(stellen),
            "stellen": stellen,
            "gedaechtnis": pages[0] if len(pages) == 1 else pages,
        }

    def _graph_ba_posting(self, item: Item) -> None:
        norm = ba.normalize_job_item(item.data)
        pid = g.posting_id("ba", item.key)
        self.store.upsert_node(
            pid,
            "Stellenanzeige",
            norm["titel"],
            _compact(
                {
                    "quelle": "Arbeitsagentur",
                    "url": norm["url"],
                    "veroeffentlicht": norm["veroeffentlicht"],
                    "ort": norm["ort"],
                }
            ),
        )
        if norm["arbeitgeber"]:
            emp = g.employer_id(norm["arbeitgeber"])
            self.store.upsert_node(emp, "Arbeitgeber", norm["arbeitgeber"])
            self.store.upsert_edge(pid, emp, g.AUSGESCHRIEBEN_VON, source=SRC_BA)
        if norm["ort"]:
            reg = g.region_id(norm["ort"])
            self.store.upsert_node(reg, "Region", norm["ort"], _compact({"bundesland": norm["region"]}))
            self.store.upsert_edge(pid, reg, g.IN_REGION, source=SRC_BA)
        if norm["beruf"]:
            bid = f"berufsbezeichnung:{g.slug(norm['beruf'])}"
            self.store.upsert_node(bid, "Beruf", norm["beruf"], {"quelle": "BA-Berufsbezeichnung"})
            self.store.upsert_edge(pid, bid, g.FUER_BERUF, source=SRC_BA)

    async def get_job_details(self, refnr: str, aktualisieren: bool = False) -> dict[str, Any]:
        refnr = refnr.strip()

        async def fetch() -> tuple[list[Item], dict[str, Any]]:
            raw = await self.ba.job_details(refnr)
            data = raw if self.settings.store_personal_data else strip_personal(raw)
            norm = ba.normalize_job_detail(data)
            text = _join(norm["titel"], norm["beruf"], norm["arbeitgeber"], norm["branche"], norm["beschreibung"])
            return [Item(refnr, data, norm["titel"], text, norm["url"])], {}

        try:
            res = await self._run(
                source=SRC_BA,
                kind="stelle_detail",
                operation="ba.jobdetail",
                params={"refnr": refnr},
                ttl=self._ttl("details"),
                refresh=aktualisieren,
                fetch=fetch,
                on_item=self._graph_ba_detail,
            )
        except NotFoundError:
            marked = [self.store.mark_gone(SRC_BA, k, refnr) for k in ("stelle", "stelle_detail")]
            return {
                "refnr": refnr,
                "status": "verschwunden",
                "hinweis": "Die Stellenanzeige ist bei der BA nicht (mehr) abrufbar."
                + (" Im Gedächtnis als 'verschwunden' markiert." if any(marked) else ""),
            }
        if not res.records:
            return {"refnr": refnr, "status": "unbekannt", "gedaechtnis": res.memory()}
        rec = res.records[0]
        detail = ba.normalize_job_detail(rec.data)
        detail["beschreibung"] = truncate(detail.get("beschreibung"), 8000)
        return {"stelle": _compact(detail), "datensatz": rec.meta(), "gedaechtnis": res.memory()}

    def _graph_ba_detail(self, item: Item) -> None:
        d = ba.normalize_job_detail(item.data)
        pid = g.posting_id("ba", item.key)
        self.store.upsert_node(
            pid,
            "Stellenanzeige",
            d["titel"],
            _compact(
                {
                    "quelle": "Arbeitsagentur",
                    "url": d["url"],
                    "verguetung": d["verguetung"],
                    "befristung": d["befristung"],
                    "dkz": d["haupt_dkz"],
                }
            ),
        )
        for name in filter(None, (d["branche"], d["branchengruppe"])):
            bid = g.branche_id(name)
            self.store.upsert_node(bid, "Branche", name)
            self.store.upsert_edge(pid, bid, g.GEHOERT_ZU, source=SRC_BA)
        if d["haupt_dkz"]:
            bnode = g.berufenet_id(d["haupt_dkz"])
            self.store.upsert_node(bnode, "Beruf", d["beruf"], {"quelle": "BERUFENET (DKZ)"})
            self.store.upsert_edge(pid, bnode, g.FUER_BERUF, {"ueber": "hauptDkz"}, source=SRC_BA)
        for skill in d["fertigkeiten"]:
            sid = g.skill_id("ba", g.slug(skill))
            self.store.upsert_node(sid, "Skill", skill, {"quelle": "BA-Stellenanzeige"})
            self.store.upsert_edge(pid, sid, g.ERFORDERT, source=SRC_BA)

    async def search_arbeitnow(
        self,
        *,
        was: str | None = None,
        ort: str | None = None,
        remote_only: bool = False,
        visa_sponsorship: bool = False,
        seiten: int = 1,
        aktualisieren: bool = False,
    ) -> dict[str, Any]:
        treffer: list[dict[str, Any]] = []
        pages = []
        geprueft = 0
        for page in range(1, max(1, min(seiten, 10)) + 1):
            params = {"page": page, "visa_sponsorship": True if visa_sponsorship else None}

            async def fetch(page: int = page) -> tuple[list[Item], dict[str, Any]]:
                raw = await self.arbeitnow.page(page, visa_sponsorship or None)
                items = []
                for job in raw.get("data") or []:
                    if not isinstance(job, dict) or not job.get("slug"):
                        continue
                    text = _join(
                        job.get("title"), job.get("company_name"), job.get("location"), " ".join(job.get("tags") or [])
                    )
                    items.append(Item(str(job["slug"]), job, job.get("title"), text, job.get("url")))
                return items, {"weitere_seiten": bool((raw.get("links") or {}).get("next"))}

            res = await self._run(
                source=SRC_ARBEITNOW,
                kind="stelle",
                operation="arbeitnow.jobs",
                params=params,
                ttl=self._ttl("jobs"),
                refresh=aktualisieren,
                fetch=fetch,
                on_item=self._graph_arbeitnow,
            )
            geprueft += len(res.records)
            for rec in res.records:
                if signals.arbeitnow_matches(rec.data, was, ort, remote_only=remote_only):
                    treffer.append(_compact(signals.normalize_arbeitnow_job(rec.data)))
            pages.append({"seite": page, **res.memory()})
            if not res.meta.get("weitere_seiten"):
                break
        for t in treffer:
            t["beschreibung"] = truncate(t.get("beschreibung"), 600)
        return {
            "quelle": "Arbeitnow (aggregierte ATS-Feeds)",
            "hinweis": "Arbeitnow kennt keine Suchparameter für Begriff/Ort; gefiltert wird lokal über die abgerufenen "
            "Seiten (je bis zu 100 Stellen).",
            "geprueft": geprueft,
            "anzahl": len(treffer),
            "stellen": treffer,
            "gedaechtnis": pages[0] if len(pages) == 1 else pages,
        }

    def _graph_arbeitnow(self, item: Item) -> None:
        job = signals.normalize_arbeitnow_job(item.data)
        pid = g.posting_id("arbeitnow", item.key)
        self.store.upsert_node(
            pid,
            "Stellenanzeige",
            job["titel"],
            _compact({"quelle": "Arbeitnow", "url": job["url"], "remote": job["remote"], "ort": job["ort"]}),
        )
        if job["arbeitgeber"]:
            emp = g.employer_id(job["arbeitgeber"])
            self.store.upsert_node(emp, "Arbeitgeber", job["arbeitgeber"])
            self.store.upsert_edge(pid, emp, g.AUSGESCHRIEBEN_VON, source=SRC_ARBEITNOW)
        if job["ort"]:
            reg = g.region_id(job["ort"])
            self.store.upsert_node(reg, "Region", job["ort"])
            self.store.upsert_edge(pid, reg, g.IN_REGION, source=SRC_ARBEITNOW)

    async def get_ats_jobs(
        self,
        company_slug: str,
        *,
        ats: str | None = None,
        suchbegriff: str | None = None,
        ort: str | None = None,
        max_jobs: int = 200,
        aktualisieren: bool = False,
    ) -> dict[str, Any]:
        target = company_slug.strip()
        workday: dict[str, str] | None = None
        detected = atsmod.detect_from_url(target) if ("." in target or "/" in target) else None
        if detected:
            ats, target = detected["ats"], detected["slug"]
            workday = detected if ats == "workday" else None
        elif ats is None:
            known = self.store.get_record(SRC_ATS, "firma", target.lower())
            if known and isinstance(known.data, dict):
                ats = known.data.get("ats")
        if ats and ats not in atsmod.PLATFORMS:
            raise ValueError(f"Unbekanntes ATS {ats!r}. Unterstützt: {', '.join(atsmod.PLATFORMS)}")
        candidates = [ats] if ats else list(atsmod.DETECT_ORDER)
        versuche: list[dict[str, Any]] = []
        for platform in candidates:
            if platform is None:
                continue
            params = {"ats": platform, "slug": target}

            async def fetch(platform: str = platform) -> tuple[list[Item], dict[str, Any]]:
                jobs = await self.ats.fetch(platform, target, workday=workday, max_jobs=max_jobs)
                items = [
                    Item(
                        f"{platform}:{target}:{j['job_id']}",
                        j,
                        j.get("titel"),
                        _join(j.get("titel"), j.get("abteilung"), j.get("firma"), " ".join(j.get("orte") or [])),
                        j.get("url"),
                    )
                    for j in jobs
                ]
                return items, {"plattform": platform}

            try:
                res = await self._run(
                    source=SRC_ATS,
                    kind="stelle",
                    operation="ats.jobs",
                    params=params,
                    ttl=self._ttl("jobs"),
                    refresh=aktualisieren,
                    fetch=fetch,
                    on_item=self._graph_ats,
                )
            except atsmod.NotOnPlatform:
                versuche.append({"ats": platform, "ergebnis": "nicht vorhanden"})
                continue
            except SourceError as exc:
                versuche.append({"ats": platform, "ergebnis": f"Fehler: {exc}"})
                if ats:
                    raise
                continue
            if not res.records and not ats:
                versuche.append({"ats": platform, "ergebnis": "keine Stellen (oder Firma nicht auf dieser Plattform)"})
                continue
            self.store.upsert_record(SRC_ATS, "firma", target.lower(), {"ats": platform, "slug": target})
            jobs = [r.data for r in res.records]
            if suchbegriff:
                words = suchbegriff.lower().split()
                jobs = [
                    j
                    for j in jobs
                    if all(w in _join(j.get("titel"), j.get("abteilung"), j.get("beschreibung")).lower() for w in words)
                ]
            if ort:
                jobs = [j for j in jobs if any(ort.lower() in (o or "").lower() for o in j.get("orte") or [])]
            out = []
            for j in jobs:
                j = dict(j)
                j["beschreibung"] = truncate(j.get("beschreibung"), 500)
                out.append(_compact(j))
            return {
                "firma": target,
                "ats": platform,
                "gefunden": True,
                "anzahl_gesamt": len(res.records),
                "anzahl": len(out),
                "stellen": out,
                "gedaechtnis": res.memory(),
                **({"versuche": versuche} if versuche else {}),
            }
        return {
            "firma": target,
            "gefunden": False,
            "versuche": versuche,
            "hinweis": "Kein ATS mit offenen Stellen gefunden. Tipp: die Karriereseiten-URL angeben (bei Workday "
            "zwingend), z. B. https://jobs.lever.co/<firma> oder https://<tenant>.wd1.myworkdayjobs.com/<site>.",
        }

    def _graph_ats(self, item: Item) -> None:
        j = item.data
        pid = g.posting_id("ats", item.key)
        self.store.upsert_node(
            pid,
            "Stellenanzeige",
            j.get("titel"),
            _compact(
                {
                    "quelle": f"ATS {j.get('plattform')}",
                    "url": j.get("url"),
                    "abteilung": j.get("abteilung"),
                    "seniority": j.get("seniority"),
                    "anstellungsart": j.get("anstellungsart"),
                    "remote": j.get("remote"),
                }
            ),
        )
        firma = j.get("firma") or j.get("firma_slug")
        if firma:
            emp = g.employer_id(str(firma))
            self.store.upsert_node(emp, "Arbeitgeber", str(firma), {"ats": j.get("plattform")})
            self.store.upsert_edge(pid, emp, g.AUSGESCHRIEBEN_VON, source=SRC_ATS)
        for ort in (j.get("orte") or [])[:5]:
            reg = g.region_id(ort)
            self.store.upsert_node(reg, "Region", ort)
            self.store.upsert_edge(pid, reg, g.IN_REGION, source=SRC_ATS)

    async def adzuna_salary(
        self,
        was: str,
        *,
        standort: list[str] | None = None,
        kategorie: str | None = None,
        monate: int = 12,
        aktualisieren: bool = False,
    ) -> dict[str, Any]:
        if not self.adzuna.configured:
            return {"aktiv": False, "hinweis": ADZUNA_HINT}
        params = {
            "was": was,
            "standort": standort,
            "kategorie": kategorie,
            "monate": monate,
            "land": self.settings.adzuna_country,
        }

        async def fetch() -> tuple[list[Item], dict[str, Any]]:
            hist = await self.adzuna.histogram(was, standort)
            top = await self.adzuna.top_companies(was, standort)
            items = [
                Item(f"histogramm|{was}|{standort}", hist, f"Gehaltsverteilung {was}"),
                Item(f"top_firmen|{was}|{standort}", top, f"Top-Arbeitgeber {was}"),
            ]
            if kategorie:
                items.append(
                    Item(
                        f"verlauf|{kategorie}|{standort}",
                        await self.adzuna.history(kategorie, standort, monate),
                        f"Gehaltsverlauf {kategorie}",
                    )
                )
            return items, {}

        res = await self._run(
            source=SRC_ADZUNA,
            kind="gehalt",
            operation="adzuna.gehalt",
            params=params,
            ttl=self._ttl("details"),
            refresh=aktualisieren,
            fetch=fetch,
        )
        out: dict[str, Any] = {"quelle": "Adzuna (inserierte Gehälter, teils von Adzuna geschätzt)", "was": was}
        for rec in res.records:
            if rec.key.startswith("histogramm|"):
                out["histogramm"] = rec.data.get("histogram")
                out["histogramm_hinweis"] = (
                    "Schlüssel = Gehalt (EUR/Jahr), Wert = Zahl offener Stellen, die mindestens "
                    "so viel zahlen (laut Adzuna-Doku)."
                )
            elif rec.key.startswith("top_firmen|"):
                out["top_arbeitgeber"] = [
                    _compact(
                        {
                            "name": c.get("display_name") or c.get("canonical_name"),
                            "stellen": c.get("count"),
                            "durchschnittsgehalt": c.get("average_salary"),
                        }
                    )
                    for c in (rec.data.get("leaderboard") or [])[:15]
                ]
            elif rec.key.startswith("verlauf|"):
                out["verlauf_monatlich"] = rec.data.get("month")
        out["gedaechtnis"] = res.memory()
        return out

    # ---------------------------------------------------------- automation

    async def find_automation_signals(
        self,
        suchbegriff: str,
        *,
        aufgabe_id: str | None = None,
        zeitraum_tage: int | None = None,
        limit: int = 20,
        nur_kommentare: bool = False,
        aktualisieren: bool = False,
    ) -> dict[str, Any]:
        tags = "comment" if nur_kommentare else "(story,comment)"
        params = {"q": suchbegriff, "tags": tags, "tage": zeitraum_tage, "limit": limit}
        if aufgabe_id:
            aufgabe_id = self._task_ref(aufgabe_id)

        async def fetch() -> tuple[list[Item], dict[str, Any]]:
            raw = await self.hn.search(suchbegriff, tags=tags, hits=limit, since_days=zeitraum_tage)
            items = []
            for hit in raw.get("hits") or []:
                norm = signals.normalize_hn_hit(hit)
                if norm["id"]:
                    items.append(
                        Item(norm["id"], hit, norm["titel"], _join(norm["titel"], norm["text"]), norm["hn_url"])
                    )
            return items, {"treffer_gesamt": raw.get("nbHits")}

        res = await self._run(
            source=SRC_HN,
            kind="signal",
            operation="hn.suche",
            params=params,
            ttl=self._ttl("signals"),
            refresh=aktualisieren,
            fetch=fetch,
            hash_ignore=signals.HN_VOLATILE,
        )
        out = []
        for rank, rec in enumerate(res.records, 1):
            norm = signals.normalize_hn_hit(rec.data)
            node = f"automatisierung:hn:{norm['id']}"
            self.store.upsert_node(
                node,
                "Automatisierung",
                norm["titel"] or truncate(norm["text"], 80),
                _compact({"url": norm["hn_url"], "quelle": "Hacker News", "erstellt": norm["erstellt"]}),
            )
            if aufgabe_id:
                self.store.upsert_edge(
                    aufgabe_id, node, g.AUTOMATISIERBAR_DURCH, {"suchbegriff": suchbegriff, "rang": rank}, source=SRC_HN
                )
            out.append(_compact({**norm, "knoten": node}))
        return {
            "quelle": "Hacker News (Algolia-Suche)",
            "suchbegriff": suchbegriff,
            "treffer_gesamt": res.meta.get("treffer_gesamt"),
            "signale": out,
            "verknuepft_mit": aufgabe_id,
            "hinweis": "Textschnipsel sind Indizien, keine Belege. Für die Bewertung je Aufgabe (z. B. Anteil an der "
            "Wochenarbeitszeit) record_extraction mit 'automatisierungen' nutzen.",
            "gedaechtnis": res.memory(),
        }

    def _task_ref(self, ref: str) -> str:
        """Existing node id, or a task node created from free text; unknown ids are rejected."""
        ref = ref.strip()
        if self.store.get_node(ref):
            return ref
        if re.match(r"^[a-z_]+:", ref):
            raise ValueError(
                f"Unbekannter Knoten {ref!r}. Knoten-IDs liefern get_tasks, search_knowledge oder "
                "graph_neighbors; alternativ den Aufgabentext angeben."
            )
        node = g.task_id("extrahiert", g.short_hash(ref))
        self.store.upsert_node(node, "Aufgabe", ref, {"quelle": "find_automation_signals"})
        return node

    # -------------------------------------------------------- Common Crawl

    async def commoncrawl_lookup(
        self, url_muster: str, *, crawl: str | None = None, limit: int = 20, text_abrufen: int = 0
    ) -> dict[str, Any]:
        crawl_id = crawl
        if not crawl_id:
            crawls = await self._run(
                source=SRC_CC,
                kind="crawl",
                operation="cc.crawls",
                params={},
                ttl=timedelta(days=1),
                refresh=False,
                fetch=self._fetch_crawls,
            )
            if not crawls.records:
                raise SourceError("Keine Common-Crawl-Crawls bekannt.")
            crawl_id = crawls.records[0].key
        params = {"crawl": crawl_id, "url": url_muster, "limit": limit}

        async def fetch() -> tuple[list[Item], dict[str, Any]]:
            rows = await self.cc.query(crawl_id, url_muster, limit=limit, filters=["status:200"])
            return [
                Item(f"{crawl_id}|{r.get('url')}|{r.get('timestamp')}", r, r.get("url"), r.get("url")) for r in rows
            ], {}

        res = await self._run(
            source=SRC_CC,
            kind="capture",
            operation="cc.index",
            params=params,
            ttl=self._ttl("reference"),
            refresh=False,
            fetch=fetch,
        )
        captures = [
            _compact(
                {
                    k: r.data.get(k)
                    for k in ("url", "timestamp", "mime", "status", "languages", "filename", "offset", "length")
                }
            )
            for r in res.records
        ]
        texte = []
        for cap in captures[: max(0, min(text_abrufen, 5))]:
            try:
                record = await self.cc.fetch(str(cap["filename"]), int(cap["offset"]), int(cap["length"]))
            except (SourceError, KeyError, ValueError) as exc:
                texte.append({"url": cap.get("url"), "fehler": str(exc)})
                continue
            key = f"{crawl_id}|{cap.get('url')}|{cap.get('timestamp')}"
            self.store.upsert_record(
                SRC_CC,
                "seite",
                key,
                {"url": cap.get("url"), "text": record["text"]},
                title=cap.get("url"),
                text=record["text"],
            )
            texte.append(
                {"url": cap.get("url"), "status": record.get("status"), "text": truncate(record["text"], 3000)}
            )
        return {
            "crawl": crawl_id,
            "treffer": captures,
            "texte": texte,
            "gedaechtnis": res.memory(),
            "hinweis": "Inhalte gehören den jeweiligen Seitenbetreibern; Nutzungsbedingungen von Common Crawl und "
            "Urheberrecht beachten.",
        }

    async def _fetch_crawls(self) -> tuple[list[Item], dict[str, Any]]:
        crawls = await self.cc.crawls()
        return [Item(str(c.get("id")), c, c.get("name")) for c in crawls if c.get("id")], {}

    # ------------------------------------------------------- reachability

    async def check_sources(self) -> dict[str, Any]:
        """Probe every source once from this machine; any HTTP answer counts as reachable."""
        s = self.settings
        probes: list[tuple[str, str, str, dict[str, Any], dict[str, str]]] = [
            (
                "Arbeitsagentur Jobsuche",
                "GET",
                s.ba_jobsuche_base + ba.SEARCH_PATHS[0],
                {"was": "Test", "size": 1},
                {"X-API-Key": s.ba_jobsuche_key},
            ),
            (
                "BERUFENET",
                "GET",
                s.ba_berufenet_base + "/berufe",
                {"suchwoerter": "Koch", "page": 0},
                {"X-API-Key": s.ba_berufenet_key},
            ),
            ("Entgeltatlas", "GET", s.ba_entgeltatlas_base + "/regionen", {}, {"X-API-Key": s.ba_entgeltatlas_key}),
            ("ESCO", "GET", s.esco_base + "/search", {"text": "test", "limit": 1, "language": "de"}, {}),
            ("O*NET Datenbank", "GET", s.onet_database_page, {}, {}),
            ("Arbeitnow", "GET", s.arbeitnow_url, {"page": 1}, {}),
            ("Hacker News (Algolia)", "GET", s.hn_base + "/search", {"query": "test", "hitsPerPage": 1}, {}),
            ("Common Crawl Index", "GET", s.commoncrawl_index + "/collinfo.json", {}, {}),
            ("Greenhouse", "GET", "https://boards-api.greenhouse.io/v1/boards/stripe/jobs", {}, {}),
            ("Lever", "GET", "https://api.lever.co/v0/postings/palantir", {"mode": "json"}, {}),
            ("Ashby", "GET", "https://api.ashbyhq.com/posting-api/job-board/ramp", {}, {}),
            ("SmartRecruiters", "GET", "https://api.smartrecruiters.com/v1/companies/Visa/postings", {"limit": 1}, {}),
            ("Workable", "GET", "https://apply.workable.com/api/v1/widget/accounts/huggingface", {}, {}),
            ("Recruitee", "GET", "https://helloprint.recruitee.com/api/offers/", {}, {}),
            ("Personio", "GET", "https://personio.jobs.personio.de/xml", {}, {}),
            ("BambooHR", "GET", "https://flyio.bamboohr.com/careers/list", {}, {}),
        ]
        if self.adzuna.configured:
            probes.append(
                (
                    "Adzuna",
                    "GET",
                    f"{s.adzuna_base}/jobs/{s.adzuna_country}/search/1",
                    {"app_id": s.adzuna_app_id, "app_key": s.adzuna_app_key, "results_per_page": 1},
                    {},
                )
            )

        async def probe(
            name: str, method: str, url: str, params: dict[str, Any], headers: dict[str, str]
        ) -> dict[str, Any]:
            start = time.monotonic()
            status: int | None = None
            error = None
            try:
                resp = await asyncio.wait_for(
                    self.http.request(method, url, params=params, headers=headers), timeout=15
                )
                status = resp.status_code
            except SourceError as exc:
                status, error = exc.status, (None if exc.status else str(exc))
            except asyncio.TimeoutError:
                error = "Zeitüberschreitung"
            return _compact(
                {
                    "quelle": name,
                    "url": url,
                    "erreichbar": status is not None,
                    "http_status": status,
                    "latenz_ms": int((time.monotonic() - start) * 1000),
                    "fehler": error,
                }
            )

        results = await asyncio.gather(*(probe(*p) for p in probes))
        if not self.adzuna.configured:
            results.append({"quelle": "Adzuna", "erreichbar": None, "hinweis": "nicht konfiguriert (optional)"})
        return {
            "geprueft_am": utcnow(),
            "quellen": results,
            "erreichbar": sum(1 for r in results if r.get("erreichbar")),
            "nicht_erreichbar": [r["quelle"] for r in results if r.get("erreichbar") is False],
        }

    # ------------------------------------------------------- memory tools

    def remember(
        self, art: str, schluessel: str, daten: Any, *, titel: str | None = None, quelle: str = "eigene"
    ) -> dict[str, Any]:
        source = quelle.strip() or "eigene"
        if source in {SRC_BA, SRC_BERUFENET, SRC_ESCO, SRC_ONET, SRC_KLDB, SRC_ATS}:
            source = f"eigene:{source}"
        res = self.store.upsert_record(source, art, schluessel, daten, title=titel)
        return {
            "quelle": source,
            "art": art,
            "schluessel": schluessel,
            "ergebnis": res.status,
            "version": res.version,
            "aenderungen": res.changes,
        }

    def search_knowledge(
        self, suchbegriff: str, *, art: str | None = None, quelle: str | None = None, limit: int = 20
    ) -> dict[str, Any]:
        hits = self.store.search(suchbegriff, source=quelle, kind=art, limit=limit, mode="and")
        modus = "alle Begriffe"
        if not hits:
            hits = self.store.search(suchbegriff, source=quelle, kind=art, limit=limit, mode="or")
            modus = "mindestens ein Begriff"
        return {
            "suchbegriff": suchbegriff,
            "modus": modus,
            "treffer": [
                {"titel": r.title, "relevanz": round(score, 3), **r.meta(), "url": r.origin} for r, score in hits
            ],
        }

    def get_changes(
        self,
        *,
        seit: str | None = None,
        quelle: str | None = None,
        art: str | None = None,
        ereignis: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        since = parse_since(seit)
        return {
            "seit": since,
            "zusammenfassung": self.store.change_counts(since),
            "aenderungen": self.store.changes(since=since, source=quelle, kind=art, event=ereignis, limit=limit),
        }

    def get_history(self, quelle: str, art: str, schluessel: str) -> dict[str, Any]:
        rec = self.store.get_record(quelle, art, schluessel)
        if rec is None:
            return {
                "gefunden": False,
                "hinweis": "Kein solcher Datensatz im Gedächtnis (search_knowledge hilft beim Finden).",
            }
        return {"gefunden": True, "datensatz": rec.meta(), "versionen": self.store.history(rec.id)}

    def knowledge_stats(self) -> dict[str, Any]:
        return {
            **self.store.stats(),
            "letzte_abrufe": self.store.recent_runs(10),
            "offline_modus": self.settings.offline,
        }

    def graph_neighbors(
        self, knoten: str, *, kantentyp: str | None = None, richtung: str = "beide", limit: int = 50
    ) -> dict[str, Any]:
        node = self.store.get_node(knoten)
        if node is None:
            candidates = self.store.find_nodes(label_like=knoten, limit=15) or self.store.find_nodes(
                id_prefix=knoten, limit=15
            )
            return {"gefunden": False, "kandidaten": candidates}
        return {
            "gefunden": True,
            "knoten": node,
            "kanten": self.store.edges(knoten, type_=kantentyp, direction=richtung, limit=limit),
        }

    def export_knowledge(self, format: str = "json", pfad: str | None = None) -> dict[str, Any]:
        fmt = format.lower()
        if fmt == "archivy":
            from .archivy import export_archivy

            default = self.settings.archivy_dir or Path(self.settings.db_path).expanduser().parent / "archivy"
            target = Path(pfad or default).expanduser()
            return export_archivy(self.store, target)
        nodes, edges = self.store.iter_graph()
        ext = {"json": "json", "cypher": "cypher", "graphml": "graphml"}.get(fmt)
        if not ext:
            raise ValueError("Format: json, cypher (Neo4j), graphml (NetworkX/Gephi) oder archivy")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        target = (
            Path(pfad).expanduser()
            if pfad
            else Path(self.settings.db_path).expanduser().parent / "export" / f"graph-{stamp}.{ext}"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            import json

            target.write_text(
                json.dumps({"knoten": nodes, "kanten": edges}, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        elif fmt == "cypher":
            target.write_text(g.to_cypher(nodes, edges), encoding="utf-8")
        else:
            target.write_text(g.to_graphml(nodes, edges), encoding="utf-8")
        return {"format": fmt, "datei": str(target), "knoten": len(nodes), "kanten": len(edges)}
