"""Occupation layer: BERUFENET, ESCO, O*NET, KldB 2010, crosswalks, salaries, role context and imports."""

from __future__ import annotations

import itertools
import re
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import graph as g
from .config import Settings
from .core import (
    CROSSWALK_GRAPH,
    SRC_BERUFENET,
    SRC_ENTGELT,
    SRC_ESCO,
    SRC_ESCO_ONET,
    SRC_EXTRACTION,
    SRC_KLDB,
    SRC_KLDB_ISCO,
    SRC_ONET,
    SYSTEMS,
    Item,
    OpResult,
    Resolution,
    _compact,
    _join,
)
from .http import HttpClient, SourceError
from .sources import arbeitsagentur as ba
from .sources import esco, onet, tables
from .store import KnowledgeStore, Record, UpsertResult
from .textutil import truncate

if TYPE_CHECKING:
    from datetime import timedelta

_KLDB_CODE_RE = re.compile(r"(?<!\d)(\d{3,5})(?!\d)")
CORE_ORDER = {"Core": 0, "Supplemental": 1}


def _task_node_for(rec: Record) -> str:
    return g.task_id(rec.source, rec.key)


class OccupationMixin:
    settings: Settings
    store: KnowledgeStore
    http: HttpClient
    ba: ba.ArbeitsagenturClient
    esco: esco.EscoClient
    onet: onet.OnetClient

    if TYPE_CHECKING:
        _run: Callable[..., Awaitable[OpResult]]
        _ttl: Callable[[str], timedelta]
        search_jobs: Callable[..., Awaitable[dict[str, Any]]]
        find_automation_signals: Callable[..., Awaitable[dict[str, Any]]]

    # ----------------------------------------------------------- fetchers

    def _lang(self, sprache: str | None) -> str:
        return (sprache or self.settings.language or "de").lower()

    async def _berufenet_search(self, query: str, refresh: bool = False) -> OpResult:
        async def fetch() -> tuple[list[Item], dict[str, Any]]:
            raw = await self.ba.berufenet_search(query)
            items, total = ba.normalize_berufenet_list(raw)
            return [Item(i["id"], i, i["name"], i["name"], i["url"]) for i in items], {"treffer_gesamt": total}

        return await self._run(
            source=SRC_BERUFENET,
            kind="beruf_treffer",
            operation="berufenet.suche",
            params={"q": query},
            ttl=self._ttl("reference"),
            refresh=refresh,
            fetch=fetch,
        )

    async def _berufenet_beruf(self, bid: str, refresh: bool = False) -> tuple[dict[str, Any], OpResult]:
        async def fetch() -> tuple[list[Item], dict[str, Any]]:
            raw = await self.ba.berufenet_beruf(bid)
            norm = ba.normalize_berufenet_detail(raw, bid)
            text = _join(norm["name"], " ".join(norm["aufgaben"]), " ".join(norm["taetigkeitsfelder"]))
            return [Item(bid, raw, norm["name"], text, norm["url"])], {}

        res = await self._run(
            source=SRC_BERUFENET,
            kind="beruf",
            operation="berufenet.beruf",
            params={"id": bid},
            ttl=self._ttl("reference"),
            refresh=refresh,
            fetch=fetch,
            on_item=self._graph_berufenet,
        )
        norm = ba.normalize_berufenet_detail(res.records[0].data, bid) if res.records else {}
        return norm, res

    def _graph_berufenet(self, item: Item) -> None:
        norm = ba.normalize_berufenet_detail(item.data, item.key)
        node = g.berufenet_id(item.key)
        self.store.upsert_node(
            node,
            "Beruf",
            norm["name"],
            _compact(
                {
                    "quelle": "BERUFENET",
                    "url": norm["url"],
                    "kldb2010": norm["kldb2010"],
                    "taetigkeitsfelder": norm["taetigkeitsfelder"][:20],
                }
            ),
        )
        if norm["kldb2010"]:
            self._ensure_kldb_node(norm["kldb2010"])
            self.store.upsert_edge(node, g.kldb_id(norm["kldb2010"]), g.KLASSIFIZIERT_ALS, source=SRC_BERUFENET)
        keep = set()
        for text in norm["aufgaben"]:
            key = f"{item.key}#{g.short_hash(text)}"
            keep.add(key)
            self.store.upsert_record(
                SRC_BERUFENET, "aufgabe", key, {"beruf_id": item.key, "beruf": norm["name"], "text": text}, title=text
            )
            tid = g.task_id(SRC_BERUFENET, key)
            self.store.upsert_node(tid, "Aufgabe", text, {"quelle": "BERUFENET"})
            self.store.upsert_edge(tid, node, g.TEIL_VON, source=SRC_BERUFENET)
        for old_key in self.store.keys(SRC_BERUFENET, "aufgabe", status="aktiv", key_prefix=f"{item.key}#"):
            if old_key not in keep:
                self.store.mark_gone(SRC_BERUFENET, "aufgabe", old_key)

    def _ensure_kldb_node(self, code: str) -> None:
        rec = self.store.get_record(SRC_KLDB, "kldb", code)
        label = rec.title if rec else None
        level = len(code)
        self.store.upsert_node(
            g.kldb_id(code),
            "Klassifikation",
            label,
            _compact(
                {
                    "system": "KldB 2010",
                    "ebene": tables.KLDB_LEVELS.get(level),
                    "anforderungsniveau": tables.KLDB_NIVEAUS.get(code[4]) if level == 5 else None,
                }
            ),
        )
        child = code
        for parent in g.kldb_parents(code):
            prec = self.store.get_record(SRC_KLDB, "kldb", parent)
            self.store.upsert_node(
                g.kldb_id(parent),
                "Klassifikation",
                prec.title if prec else None,
                {"system": "KldB 2010", "ebene": tables.KLDB_LEVELS.get(len(parent))},
            )
            self.store.upsert_edge(g.kldb_id(child), g.kldb_id(parent), g.UNTERGRUPPE_VON, source=SRC_KLDB)
            child = parent

    async def _esco_search(
        self, text: str, lang: str, *, type_: str = "occupation", limit: int = 10, refresh: bool = False
    ) -> OpResult:
        async def fetch() -> tuple[list[Item], dict[str, Any]]:
            raw = await self.esco.search(text, type_=type_, language=lang, limit=limit)
            results, total = esco.normalize_search(raw, lang)
            return [Item(f"{r['uri']}@{lang}", r, r["titel"], r["titel"], r["uri"]) for r in results], {
                "treffer_gesamt": total
            }

        return await self._run(
            source=SRC_ESCO,
            kind=f"{'beruf' if type_ == 'occupation' else 'skill'}_treffer",
            operation="esco.suche",
            params={"q": text, "typ": type_, "sprache": lang, "limit": limit},
            ttl=self._ttl("reference"),
            refresh=refresh,
            fetch=fetch,
        )

    async def _esco_occupation(self, uri: str, lang: str, refresh: bool = False) -> tuple[dict[str, Any], OpResult]:
        async def fetch() -> tuple[list[Item], dict[str, Any]]:
            raw = await self.esco.resource(uri, kind="occupation", language=lang)
            norm = esco.normalize_occupation(raw, lang)
            text = _join(
                norm["titel"],
                " ".join(norm["alternative_titel"]),
                norm["beschreibung"],
                " ".join(s["titel"] or "" for s in norm["essential_skills"]),
            )
            return [Item(f"{uri}@{lang}", raw, norm["titel"], text, uri)], {}

        res = await self._run(
            source=SRC_ESCO,
            kind="beruf",
            operation="esco.beruf",
            params={"uri": uri, "sprache": lang},
            ttl=self._ttl("reference"),
            refresh=refresh,
            fetch=fetch,
            on_item=lambda it: self._graph_esco_occupation(it, lang),
        )
        norm = esco.normalize_occupation(res.records[0].data, lang) if res.records else {}
        return norm, res

    def _graph_esco_occupation(self, item: Item, lang: str) -> None:
        norm = esco.normalize_occupation(item.data, lang)
        uri = str(norm["uri"] or item.key.rsplit("@", 1)[0])
        node = g.esco_id(uri)
        self.store.upsert_node(
            node, "Beruf", norm["titel"], _compact({"quelle": "ESCO", "code": norm["code"], "isco": norm["isco_code"]})
        )
        if norm["isco_code"]:
            self.store.upsert_node(g.isco_id(norm["isco_code"]), "Klassifikation", None, {"system": "ISCO-08"})
            self.store.upsert_edge(node, g.isco_id(norm["isco_code"]), g.KLASSIFIZIERT_ALS, source=SRC_ESCO)
        for relation, skills in (("essential", norm["essential_skills"]), ("optional", norm["optional_skills"])):
            for s in skills:
                sid = g.skill_id(SRC_ESCO, s["uri"])
                self.store.upsert_node(sid, "Skill", s["titel"], {"quelle": "ESCO", "uri": s["uri"]})
                self.store.upsert_edge(node, sid, g.ERFORDERT, {"relation": relation}, source=SRC_ESCO)

    async def _esco_isco(self, code: str, lang: str, refresh: bool = False) -> tuple[dict[str, Any], OpResult]:
        uri = esco.isco_uri(code)

        async def fetch() -> tuple[list[Item], dict[str, Any]]:
            raw = await self.esco.resource(uri, kind="concept", language=lang)
            norm = esco.normalize_isco_group(raw, lang)
            return [Item(f"{code}@{lang}", raw, norm["titel"], norm["titel"], uri)], {}

        res = await self._run(
            source=SRC_ESCO,
            kind="isco_gruppe",
            operation="esco.isco",
            params={"code": code, "sprache": lang},
            ttl=self._ttl("reference"),
            refresh=refresh,
            fetch=fetch,
        )
        norm = esco.normalize_isco_group(res.records[0].data, lang) if res.records else {}
        if norm:
            self.store.upsert_node(g.isco_id(code), "Klassifikation", norm.get("titel"), {"system": "ISCO-08"})
            for occ in norm.get("berufe") or []:
                self.store.upsert_node(g.esco_id(occ["uri"]), "Beruf", occ["titel"], {"quelle": "ESCO"})
                self.store.upsert_edge(g.esco_id(occ["uri"]), g.isco_id(code), g.KLASSIFIZIERT_ALS, source=SRC_ESCO)
        return norm, res

    # ------------------------------------------------------- local lookups

    def _kldb_label(self, code: str | None) -> str | None:
        if not code:
            return None
        rec = self.store.get_record(SRC_KLDB, "kldb", code)
        return rec.title if rec else None

    def _mapping(self, source: str, field: str, value: str) -> list[dict[str, Any]]:
        return [
            r.data
            for r in self.store.find_records(
                source=source, kind="mapping", json_equals=(field, value), status="aktiv", limit=100
            )
        ]

    def _onet_tasks(self, soc: str, nur_kern: bool = False, limit: int = 50) -> list[dict[str, Any]]:
        recs = self.store.find_records(
            source=SRC_ONET, kind="aufgabe", key_prefix=f"{soc}#", status="aktiv", limit=2000
        )
        tasks = [r for r in recs if not nur_kern or r.data.get("task_type") == "Core"]
        tasks.sort(
            key=lambda r: (
                CORE_ORDER.get(r.data.get("task_type") or "", 2),
                -(r.data.get("incumbents_responding") or 0),
            )
        )
        return [
            {
                "knoten": _task_node_for(r),
                "aufgabe": r.data["task"],
                "typ": r.data.get("task_type"),
                "task_id": r.data.get("task_id"),
            }
            for r in tasks[:limit]
        ]

    def _onet_title(self, soc: str) -> str | None:
        rec = self.store.get_record(SRC_ONET, "beruf", soc)
        return rec.title if rec else None

    def _has(self, source: str, kind: str) -> bool:
        return self.store.count_records(source, kind) > 0

    # ------------------------------------------------------------ resolve

    async def resolve(self, beruf: str, sprache: str | None = None, *, expand: bool = True) -> Resolution:
        """Map an occupation reference (free text or prefixed code) to codes in all systems."""
        lang = self._lang(sprache)
        r = Resolution(eingabe=beruf)
        text = beruf.strip()
        low = text.lower()
        if low.startswith("berufenet:"):
            r.add("berufenet", text.split(":", 1)[1].strip())
        elif low.startswith("kldb:") or re.fullmatch(r"\d{3,5}", text):
            r.add("kldb", text.split(":", 1)[-1].strip())
        elif low.startswith("isco:"):
            r.add("isco", text.split(":", 1)[1].strip())
        elif low.startswith("onet:") or onet.SOC_RE.match(text):
            r.add("onet", onet.normalize_soc(text.split(":", 1)[-1] if low.startswith("onet:") else text))
        elif low.startswith("esco:") or text.startswith(esco.OCCUPATION_PREFIX):
            r.add("esco", text[5:] if low.startswith("esco:") else text)
        else:
            try:
                res = await self._berufenet_search(text)
                if res.records:
                    r.add("berufenet", res.records[0].key, res.records[0].title)
            except SourceError as exc:
                r.hinweise.append(f"BERUFENET nicht erreichbar: {exc}")
            try:
                res = await self._esco_search(text, lang, limit=3)
                if res.records:
                    hit = res.records[0].data
                    r.add("esco", hit["uri"], hit.get("titel"))
            except SourceError as exc:
                r.hinweise.append(f"ESCO nicht erreichbar: {exc}")
            for rec, _score in self.store.search(text, source=SRC_ONET, kind="beruf", limit=1, mode="and"):
                r.add("onet", rec.key, rec.title)
        if not expand:
            return r
        for bid in list(r.berufenet):
            try:
                norm, _ = await self._berufenet_beruf(bid)
            except SourceError as exc:
                r.hinweise.append(f"BERUFENET {bid}: {exc}")
                continue
            r.labels.setdefault(f"berufenet:{bid}", norm.get("name") or "")
            r.add("kldb", norm.get("kldb2010"), self._kldb_label(norm.get("kldb2010")))
        for code in list(r.kldb):
            for m in self._mapping(SRC_KLDB_ISCO, "kldb", code):
                r.add("isco", m["isco"], m.get("isco_titel"))
        for uri in list(r.esco):
            for m in self._mapping(SRC_ESCO_ONET, "esco_uri", uri):
                r.add("onet", m["onet_soc"], m.get("onet_titel") or self._onet_title(m["onet_soc"]))
            try:
                norm, _ = await self._esco_occupation(uri, lang)
                r.labels.setdefault(f"esco:{uri}", norm.get("titel") or "")
                r.add("isco", norm.get("isco_code"))
            except SourceError as exc:
                r.hinweise.append(f"ESCO {uri}: {exc}")
        if not r.esco and r.isco:
            for code in r.isco[:2]:
                try:
                    norm, _ = await self._esco_isco(code, lang)
                except SourceError as exc:
                    r.hinweise.append(f"ESCO ISCO {code}: {exc}")
                    continue
                for occ in (norm.get("berufe") or [])[:3]:
                    r.add("esco", occ["uri"], occ.get("titel"))
                    for m in self._mapping(SRC_ESCO_ONET, "esco_uri", occ["uri"]):
                        r.add("onet", m["onet_soc"], m.get("onet_titel") or self._onet_title(m["onet_soc"]))
        if r.kldb and not self._has(SRC_KLDB_ISCO, "mapping"):
            r.hinweise.append("KldB→ISCO-Umsteigeschlüssel nicht importiert: import_reference_data('kldb_isco', ...).")
        if r.esco and not self._has(SRC_ESCO_ONET, "mapping"):
            r.hinweise.append("ESCO↔O*NET-Crosswalk nicht importiert: import_reference_data('esco_onet', ...).")
        return r

    # --------------------------------------------------------------- tools

    async def search_occupation(
        self,
        query: str,
        *,
        kldb_code: str | None = None,
        quellen: Sequence[str] | None = None,
        limit: int = 10,
        sprache: str | None = None,
        details: int = 3,
        aktualisieren: bool = False,
    ) -> dict[str, Any]:
        lang = self._lang(sprache)
        wanted = {q.lower() for q in (quellen or ["berufenet", "esco", "kldb", "onet"])}
        out: dict[str, Any] = {"suchbegriff": query}
        hinweise: list[str] = []
        if "berufenet" in wanted:
            try:
                res = await self._berufenet_search(query, aktualisieren)
                berufe = []
                for i, rec in enumerate(res.records[:limit]):
                    entry = dict(rec.data)
                    if i < details:
                        try:
                            norm, _ = await self._berufenet_beruf(entry["id"])
                            entry.update(
                                _compact(
                                    {
                                        "kldb2010": norm.get("kldb2010"),
                                        "kldb_titel": self._kldb_label(norm.get("kldb2010")),
                                        "aufgaben": len(norm.get("aufgaben") or []),
                                    }
                                )
                            )
                        except SourceError as exc:
                            entry["fehler"] = str(exc)
                    berufe.append(entry)
                out["berufenet"] = {
                    "treffer_gesamt": res.meta.get("treffer_gesamt"),
                    "berufe": berufe,
                    "gedaechtnis": res.memory(),
                }
            except SourceError as exc:
                hinweise.append(f"BERUFENET nicht erreichbar: {exc}")
        if "esco" in wanted:
            try:
                res = await self._esco_search(query, lang, limit=limit, refresh=aktualisieren)
                out["esco"] = {
                    "treffer_gesamt": res.meta.get("treffer_gesamt"),
                    "berufe": [_compact(r.data) for r in res.records],
                    "gedaechtnis": res.memory(),
                }
            except SourceError as exc:
                hinweise.append(f"ESCO nicht erreichbar: {exc}")
        if "kldb" in wanted:
            entries: list[dict[str, Any]] = []
            if kldb_code:
                known = self.store.get_record(SRC_KLDB, "kldb", kldb_code)
                entries.append(
                    {"code": kldb_code, "titel": known.title if known else None, "bekannt": known is not None}
                )
            for rec, score in self.store.search(query, source=SRC_KLDB, kind="kldb", limit=limit, mode="or"):
                entries.append(
                    {
                        "code": rec.key,
                        "titel": rec.title,
                        "ebene": rec.data.get("ebene_name"),
                        "relevanz": round(score, 3),
                    }
                )
            out["kldb"] = entries
            if not self._has(SRC_KLDB, "kldb"):
                hinweise.append(
                    "KldB-2010-Systematik nicht importiert (import_reference_data('kldb', <xlsx/csv>)). "
                    "KldB-Codes aus BERUFENET werden trotzdem angezeigt."
                )
        if "onet" in wanted:
            if self._has(SRC_ONET, "beruf"):
                out["onet"] = [
                    {"soc": r.key, "titel": r.title, "relevanz": round(s, 3)}
                    for r, s in self.store.search(query, source=SRC_ONET, kind="beruf", limit=limit, mode="or")
                ]
            else:
                hinweise.append("O*NET nicht importiert (import_reference_data('onet')). O*NET-Titel sind englisch.")
        if hinweise:
            out["hinweise"] = hinweise
        return out

    async def get_occupation(
        self, beruf_id: str, *, sprache: str | None = None, aktualisieren: bool = False
    ) -> dict[str, Any]:
        lang = self._lang(sprache)
        res = await self.resolve(beruf_id, lang, expand=False)
        if res.berufenet:
            bid = res.berufenet[0]
            norm, op = await self._berufenet_beruf(bid, aktualisieren)
            return {
                "system": "BERUFENET",
                "beruf": norm,
                "kldb_titel": self._kldb_label(norm.get("kldb2010")),
                "datensatz": op.records[0].meta() if op.records else None,
                "gedaechtnis": op.memory(),
            }
        if res.esco:
            uri = res.esco[0]
            norm, op = await self._esco_occupation(uri, lang, aktualisieren)
            norm = dict(norm)
            norm["onet"] = self._mapping(SRC_ESCO_ONET, "esco_uri", uri)
            return {"system": "ESCO", "beruf": norm, "gedaechtnis": op.memory()}
        if res.onet:
            soc = res.onet[0]
            rec = self.store.get_record(SRC_ONET, "beruf", soc)
            return {
                "system": "O*NET",
                "beruf": rec.data if rec else {"soc": soc},
                "aufgaben": self._onet_tasks(soc, limit=15),
                "esco": self._mapping(SRC_ESCO_ONET, "onet_soc", soc),
                "hinweis": None if rec else "O*NET nicht importiert: import_reference_data('onet').",
            }
        if res.kldb:
            code = res.kldb[0]
            rec = self.store.get_record(SRC_KLDB, "kldb", code)
            self._ensure_kldb_node(code)
            node = g.kldb_id(code)
            return {
                "system": "KldB 2010",
                "kldb": rec.data if rec else {"code": code, "titel": None},
                "hierarchie": [{"code": p, "titel": self._kldb_label(p)} for p in g.kldb_parents(code)],
                "isco": self._mapping(SRC_KLDB_ISCO, "kldb", code),
                "berufenet_berufe": [
                    e for e in self.store.edges(node, direction="eingehend", type_=g.KLASSIFIZIERT_ALS)
                ],
                "entgelte": [e for e in self.store.edges(node, direction="ausgehend", type_=g.HAT_ENTGELT)],
            }
        if res.isco:
            code = res.isco[0]
            norm, op = await self._esco_isco(code, lang, aktualisieren)
            return {
                "system": "ISCO-08",
                "isco": norm,
                "kldb": self._mapping(SRC_KLDB_ISCO, "isco", code),
                "gedaechtnis": op.memory(),
            }
        return {
            "gefunden": False,
            "hinweis": "Kein Code erkannt. Formate: berufenet:<id>, kldb:<code>, isco:<code>, "
            "onet:<soc>, ESCO-URI – oder search_occupation für Freitext.",
        }

    async def get_tasks(
        self,
        beruf: str,
        *,
        quellen: Sequence[str] | None = None,
        nur_kern: bool = False,
        limit: int = 40,
        sprache: str | None = None,
    ) -> dict[str, Any]:
        wanted = {q.lower() for q in (quellen or ["onet", "berufenet"])}
        res = await self.resolve(beruf, sprache)
        aufgaben: dict[str, Any] = {}
        hinweise = list(res.hinweise)
        if "onet" in wanted:
            if not self._has(SRC_ONET, "aufgabe"):
                hinweise.append("O*NET-Aufgaben nicht importiert: import_reference_data('onet').")
            onet_out = []
            for soc in res.onet[:3]:
                onet_out.append(
                    {"soc": soc, "titel": self._onet_title(soc), "aufgaben": self._onet_tasks(soc, nur_kern, limit)}
                )
            aufgaben["onet"] = onet_out
            if not res.onet:
                hinweise.append(
                    "Keine O*NET-Zuordnung gefunden (O*NET-SOC-Code, englischen Titel oder ESCO-URI mit "
                    "importiertem Crosswalk angeben)."
                )
        if "berufenet" in wanted:
            bn_out = []
            for bid in res.berufenet[:2]:
                try:
                    norm, _ = await self._berufenet_beruf(bid)
                except SourceError as exc:
                    hinweise.append(f"BERUFENET {bid}: {exc}")
                    continue
                tasks = self.store.find_records(
                    source=SRC_BERUFENET, kind="aufgabe", key_prefix=f"{bid}#", status="aktiv", limit=limit
                )
                bn_out.append(
                    {
                        "id": bid,
                        "name": norm.get("name"),
                        "url": norm.get("url"),
                        "aufgaben": [{"knoten": _task_node_for(t), "aufgabe": t.data["text"]} for t in tasks],
                        "taetigkeitsfelder": norm.get("taetigkeitsfelder"),
                    }
                )
                if not tasks:
                    hinweise.append(f"BERUFENET {bid}: keine Aufgabenliste erkannt (Antwortformat prüfen).")
            aufgaben["berufenet"] = bn_out
        return {
            "beruf": beruf,
            "zuordnung": res.as_dict(),
            "aufgaben": aufgaben,
            **({"hinweise": hinweise} if hinweise else {}),
        }

    async def get_skills(
        self, beruf: str, *, relation: str = "alle", sprache: str | None = None, limit: int = 40
    ) -> dict[str, Any]:
        lang = self._lang(sprache)
        rel = relation.lower()
        if rel not in ("alle", "essential", "optional"):
            raise ValueError("relation: 'essential', 'optional' oder 'alle'")
        res = await self.resolve(beruf, lang)
        berufe = []
        for uri in res.esco[:2]:
            try:
                norm, op = await self._esco_occupation(uri, lang)
            except SourceError as exc:
                res.hinweise.append(f"ESCO {uri}: {exc}")
                continue
            entry: dict[str, Any] = {"uri": uri, "titel": norm.get("titel"), "isco": norm.get("isco_code")}
            if rel in ("alle", "essential"):
                entry["essential"] = norm.get("essential_skills", [])[:limit]
            if rel in ("alle", "optional"):
                entry["optional"] = norm.get("optional_skills", [])[:limit]
            entry["gedaechtnis"] = op.memory()
            berufe.append(entry)
        counter: Counter[str] = Counter()
        for rec, _ in self.store.search(beruf, source="ba_jobsuche", kind="stelle_detail", limit=200, mode="or"):
            counter.update(ba.normalize_job_detail(rec.data).get("fertigkeiten") or [])
        out: dict[str, Any] = {"beruf": beruf, "zuordnung": res.as_dict(), "esco": berufe}
        if counter:
            out["aus_stellenanzeigen"] = [{"skill": s, "anzeigen": n} for s, n in counter.most_common(25)]
        if res.hinweise:
            out["hinweise"] = res.hinweise
        return out

    async def crosswalk(self, code: str, von: str, nach: str, *, sprache: str | None = None) -> dict[str, Any]:
        lang = self._lang(sprache)
        src, dst = von.lower(), nach.lower()
        if src not in SYSTEMS or dst not in SYSTEMS:
            raise ValueError(f"Systeme: {', '.join(SYSTEMS)}")
        path = self._crosswalk_path(src, dst)
        if not path:
            return {"gefunden": False, "hinweis": f"Kein Weg von {src} nach {dst}."}
        current: list[tuple[str, str | None]] = [(code.strip(), None)]
        steps = []
        hinweise: list[str] = []
        for a, b in itertools.pairwise(path):
            nxt: dict[str, str | None] = {}
            for value, _label in current[:25]:
                try:
                    for c, lbl in await self._crosswalk_step(a, b, value, lang):
                        nxt.setdefault(c, lbl)
                except SourceError as exc:
                    hinweise.append(f"{a}→{b} {value}: {exc}")
            current = list(nxt.items())
            steps.append({"von": a, "nach": b, "anzahl": len(current)})
            if not current:
                hinweise.append(self._crosswalk_hint(a, b))
                break
        return {
            "code": code,
            "von": src,
            "nach": dst,
            "pfad": path,
            "schritte": steps,
            "ergebnisse": [{"code": c, "titel": lbl} for c, lbl in current],
            **({"hinweise": hinweise} if hinweise else {}),
        }

    def _crosswalk_path(self, src: str, dst: str) -> list[str]:
        queue = [[src]]
        seen = {src}
        while queue:
            path = queue.pop(0)
            if path[-1] == dst:
                return path
            for nxt in CROSSWALK_GRAPH.get(path[-1], ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append([*path, nxt])
        return []

    def _crosswalk_hint(self, a: str, b: str) -> str:
        if {a, b} == {"kldb", "isco"}:
            return "KldB↔ISCO braucht den importierten Umsteigeschlüssel: import_reference_data('kldb_isco', ...)."
        if {a, b} == {"esco", "onet"}:
            return "ESCO↔O*NET braucht den importierten Crosswalk: import_reference_data('esco_onet', ...)."
        if (a, b) == ("kldb", "berufenet"):
            return "KldB→BERUFENET kennt nur bereits abgerufene BERUFENET-Berufe (vorher search_occupation nutzen)."
        return f"Keine Zuordnung {a}→{b} gefunden."

    async def _crosswalk_step(self, a: str, b: str, value: str, lang: str) -> list[tuple[str, str | None]]:
        if (a, b) == ("kldb", "isco"):
            return [(m["isco"], m.get("isco_titel")) for m in self._mapping(SRC_KLDB_ISCO, "kldb", value)]
        if (a, b) == ("isco", "kldb"):
            return [
                (m["kldb"], m.get("kldb_titel") or self._kldb_label(m["kldb"]))
                for m in self._mapping(SRC_KLDB_ISCO, "isco", value)
            ]
        if (a, b) == ("isco", "esco"):
            norm, _ = await self._esco_isco(value, lang)
            return [(o["uri"], o.get("titel")) for o in norm.get("berufe") or []]
        if (a, b) == ("esco", "isco"):
            norm, _ = await self._esco_occupation(value, lang)
            return [(norm["isco_code"], None)] if norm.get("isco_code") else []
        if (a, b) == ("esco", "onet"):
            return [
                (m["onet_soc"], m.get("onet_titel") or self._onet_title(m["onet_soc"]))
                for m in self._mapping(SRC_ESCO_ONET, "esco_uri", value)
            ]
        if (a, b) == ("onet", "esco"):
            return [(m["esco_uri"], m.get("esco_titel")) for m in self._mapping(SRC_ESCO_ONET, "onet_soc", value)]
        if (a, b) == ("berufenet", "kldb"):
            norm, _ = await self._berufenet_beruf(value)
            code = norm.get("kldb2010")
            return [(code, self._kldb_label(code))] if code else []
        if (a, b) == ("kldb", "berufenet"):
            return [
                (e["knoten"].split(":", 1)[1], e["knoten_label"])
                for e in self.store.edges(g.kldb_id(value), type_=g.KLASSIFIZIERT_ALS, direction="eingehend")
                if str(e["knoten"]).startswith("berufenet:")
            ]
        return []

    async def get_salary(
        self,
        kldb: str,
        *,
        region: str | int | None = None,
        niveau: str | int | None = None,
        geschlecht: str | int | None = None,
        alter: str | int | None = None,
        branche: str | int | None = None,
        aktualisieren: bool = False,
    ) -> dict[str, Any]:
        m = _KLDB_CODE_RE.search(kldb)
        if not m:
            raise ValueError(f"Kein KldB-Code (3–5 Ziffern) erkannt: {kldb!r}")
        code = m.group(1)
        params = {
            "l": ba.resolve_code(niveau, ba.ENTGELT_NIVEAUS, "Anforderungsniveau"),
            "r": ba.resolve_code(region, ba.ENTGELT_REGIONEN, "Region"),
            "g": ba.resolve_code(geschlecht, ba.ENTGELT_GESCHLECHT, "Geschlecht"),
            "a": ba.resolve_code(alter, ba.ENTGELT_ALTER, "Altersgruppe"),
            "b": ba.resolve_code(branche, ba.ENTGELT_BRANCHEN, "Branche"),
        }

        def row_key(row: dict[str, Any]) -> str:
            def ident(k: str) -> Any:
                v = row.get(k)
                return v.get("id") if isinstance(v, dict) else v

            return (
                f"{row.get('kldb') or code}|r={ident('region')}|l={ident('performanceLevel')}|g={ident('gender')}"
                f"|a={ident('ageCategory')}|b={ident('branche')}"
            )

        async def fetch() -> tuple[list[Item], dict[str, Any]]:
            rows = await self.ba.entgelte(code, params)
            return [Item(row_key(r), r, f"Entgelt {code}") for r in rows], {}

        res = await self._run(
            source=SRC_ENTGELT,
            kind="entgelt",
            operation="entgeltatlas",
            params={"kldb": code, **params},
            ttl=self._ttl("reference"),
            refresh=aktualisieren,
            fetch=fetch,
        )
        wanted_b = params["b"] or 1
        rows, unterdrueckt = [], 0
        for rec in res.records:
            branche_info = rec.data.get("branche")
            if isinstance(branche_info, dict) and branche_info.get("id") not in (None, wanted_b):
                continue
            norm = ba.normalize_entgelt(rec.data)
            if (norm.get("median_eur") or 0) < 0:
                unterdrueckt += 1
                continue
            rows.append(_compact(norm))
            node = f"entgelt:{rec.key}"
            self.store.upsert_node(node, "Entgelt", f"{norm.get('median_eur')} € Median", _compact(norm))
            self._ensure_kldb_node(code)
            self.store.upsert_edge(g.kldb_id(code), node, g.HAT_ENTGELT, source=SRC_ENTGELT)
        return {
            "kldb": code,
            "kldb_titel": self._kldb_label(code),
            "werte": rows,
            "unterdrueckt": unterdrueckt,
            "hinweis": "Bruttomonatsentgelte sozialversicherungspflichtig Vollzeitbeschäftigter (Median und Quartile), "
            "Statistik der BA (Entgeltatlas). Werte an der Beitragsbemessungsgrenze sind gekappt; Quelle angeben.",
            "gedaechtnis": res.memory(),
        }

    async def get_role_context(
        self, rolle: str, *, ort: str | None = None, sprache: str | None = None, mit_signalen: bool = False
    ) -> dict[str, Any]:
        """One call that returns role, tasks, skills, salary and market signal (learned from berufsgraph)."""
        lang = self._lang(sprache)
        res = await self.resolve(rolle, lang)
        ctx: dict[str, Any] = {"rolle": rolle, "ort": ort, "zuordnung": res.as_dict()}
        hinweise = list(res.hinweise)
        if res.berufenet:
            try:
                norm, _ = await self._berufenet_beruf(res.berufenet[0])
                ctx["berufenet"] = {
                    "id": norm.get("id"),
                    "name": norm.get("name"),
                    "url": norm.get("url"),
                    "aufgaben": norm.get("aufgaben", [])[:20],
                    "taetigkeitsfelder": norm.get("taetigkeitsfelder", [])[:10],
                }
            except SourceError as exc:
                hinweise.append(f"BERUFENET: {exc}")
        if res.esco:
            try:
                norm, _ = await self._esco_occupation(res.esco[0], lang)
                ctx["esco"] = {
                    "uri": res.esco[0],
                    "titel": norm.get("titel"),
                    "isco": norm.get("isco_code"),
                    "essential_skills": [s["titel"] for s in norm.get("essential_skills", [])[:20]],
                    "optional_skills": [s["titel"] for s in norm.get("optional_skills", [])[:10]],
                }
            except SourceError as exc:
                hinweise.append(f"ESCO: {exc}")
        if res.onet:
            ctx["onet"] = [
                {
                    "soc": soc,
                    "titel": self._onet_title(soc),
                    "kernaufgaben": [t["aufgabe"] for t in self._onet_tasks(soc, True, 10)],
                }
                for soc in res.onet[:2]
            ]
        kldb5 = next((c for c in res.kldb if len(c) == 5), None)
        if kldb5:
            region = None
            if ort and ort.strip().lower() in ba.ENTGELT_REGIONEN:
                region = ort
            try:
                sal = await self.get_salary(kldb5, region=region)
                ctx["entgelt"] = {
                    "kldb": kldb5,
                    "region": region or "Deutschland",
                    "werte": sal["werte"][:4],
                    "hinweis": sal["hinweis"],
                }
            except (SourceError, ValueError) as exc:
                hinweise.append(f"Entgeltatlas: {exc}")
        try:
            market = await self.search_jobs(was=rolle, wo=ort, groesse=1)
            ctx["markt"] = {"offene_stellen_ba": market.get("treffer_gesamt"), "quelle": "BA-Jobsuche"}
        except (SourceError, ValueError) as exc:
            hinweise.append(f"Jobsuche: {exc}")
        if mit_signalen:
            try:
                sig = await self.find_automation_signals(rolle, limit=5)
                ctx["automatisierungssignale"] = [
                    {"titel": s.get("titel"), "text": truncate(s.get("text"), 200), "url": s.get("hn_url")}
                    for s in sig["signale"]
                ]
            except SourceError as exc:
                hinweise.append(f"Hacker News: {exc}")
        if hinweise:
            ctx["hinweise"] = hinweise
        return ctx

    # ------------------------------------------------------- extraction

    def record_extraction(
        self,
        bezug: str,
        *,
        aufgaben: list[dict[str, Any]] | None = None,
        skills: list[str] | None = None,
        automatisierungen: list[dict[str, Any]] | None = None,
        quelle: str = "llm",
    ) -> dict[str, Any]:
        node_id = self._node_ref(bezug)
        node = self.store.get_node(node_id)
        is_posting = node_id.startswith("stelle:")
        if node is None:
            self.store.upsert_node(node_id, "Stellenanzeige" if is_posting else "Beruf", bezug, {"quelle": quelle})
        payload = {
            "aufgaben": aufgaben or [],
            "skills": skills or [],
            "automatisierungen": automatisierungen or [],
            "quelle": quelle,
        }
        result: UpsertResult = self.store.upsert_record(
            SRC_EXTRACTION, "extraktion", node_id, payload, title=f"Extraktion für {node_id}"
        )
        task_out = []
        for a in aufgaben or []:
            text = str(a.get("text") or "").strip()
            if not text:
                continue
            tid = g.task_id("extrahiert", g.short_hash(text))
            self.store.upsert_node(tid, "Aufgabe", text, {"quelle": quelle})
            props = _compact({"anteil_wochenarbeitszeit": a.get("anteil_wochenarbeitszeit"), "quelle": quelle})
            if is_posting:
                self.store.upsert_edge(node_id, tid, g.STELLT_AN, props, source=SRC_EXTRACTION)
            else:
                self.store.upsert_edge(tid, node_id, g.TEIL_VON, props, source=SRC_EXTRACTION)
            if a.get("kanonisch"):
                self.store.upsert_edge(
                    tid, str(a["kanonisch"]), g.ENTSPRICHT, {"quelle": quelle}, source=SRC_EXTRACTION
                )
            vorschlaege = [
                {"knoten": _task_node_for(rec), "aufgabe": rec.title, "quelle": rec.source, "relevanz": round(score, 3)}
                for rec, score in self.store.search(text, kind="aufgabe", limit=3, mode="or")
            ]
            task_out.append({"knoten": tid, "aufgabe": text, "kanonische_vorschlaege": vorschlaege})
        skill_out = []
        for s in skills or []:
            name = s.strip()
            if not name:
                continue
            sid = g.skill_id("extrahiert", g.slug(name))
            self.store.upsert_node(sid, "Skill", name, {"quelle": quelle})
            self.store.upsert_edge(node_id, sid, g.ERFORDERT, {"quelle": quelle}, source=SRC_EXTRACTION)
            matches = [
                n
                for n in self.store.find_nodes(type_="Skill", label_like=name, limit=10)
                if (n["label"] or "").lower() == name.lower() and n["id"] != sid
            ]
            for m in matches:
                self.store.upsert_edge(
                    sid, m["id"], g.ENTSPRICHT, {"quelle": "Namensgleichheit"}, source=SRC_EXTRACTION
                )
            skill_out.append({"knoten": sid, "skill": name, "entspricht": [m["id"] for m in matches]})
        auto_out = []
        for a in automatisierungen or []:
            task_ref = str(a.get("aufgabe") or "").strip()
            signal_ref = str(a.get("signal") or "").strip()
            if not task_ref or not signal_ref:
                continue
            tid = task_ref if self.store.get_node(task_ref) else g.task_id("extrahiert", g.short_hash(task_ref))
            if not self.store.get_node(tid):
                self.store.upsert_node(tid, "Aufgabe", task_ref, {"quelle": quelle})
            sig = (
                signal_ref
                if signal_ref.startswith("automatisierung:")
                else f"automatisierung:extern:{g.short_hash(signal_ref)}"
            )
            if not self.store.get_node(sig):
                self.store.upsert_node(sig, "Automatisierung", a.get("notiz") or signal_ref, {"url": signal_ref})
            props = _compact(
                {
                    "bewertung": a.get("bewertung"),
                    "notiz": a.get("notiz"),
                    "quelle": quelle,
                    "anteil_wochenarbeitszeit": a.get("anteil_wochenarbeitszeit"),
                }
            )
            self.store.upsert_edge(tid, sig, g.AUTOMATISIERBAR_DURCH, props, source=SRC_EXTRACTION)
            auto_out.append({"aufgabe": tid, "automatisierung": sig, **props})
        return {
            "bezug": node_id,
            "extraktion": {"ergebnis": result.status, "version": result.version, "aenderungen": result.changes[:10]},
            "aufgaben": task_out,
            "skills": skill_out,
            "automatisierungen": auto_out,
        }

    def _node_ref(self, ref: str) -> str:
        text = ref.strip()
        if re.fullmatch(r"\d{4,6}-\d{6,12}-S", text):
            return g.posting_id("ba", text)
        if text.startswith("ba:"):
            return g.posting_id("ba", text[3:])
        return text

    # ----------------------------------------------------------- imports

    async def _load_source(self, quelle: str) -> tuple[bytes, str]:
        if quelle.startswith(("http://", "https://")):
            return await self.http.get_bytes(quelle), quelle.split("?", 1)[0].rsplit("/", 1)[-1]
        path = Path(quelle).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Datei nicht gefunden: {path}")
        return path.read_bytes(), path.name

    async def import_reference_data(
        self,
        datensatz: str,
        *,
        quelle: str | None = None,
        onet_version: str | None = None,
        alternativtitel: bool = True,
    ) -> dict[str, Any]:
        ds = datensatz.lower().replace("-", "_")
        if ds == "onet":
            return await self._import_onet(quelle, onet_version, alternativtitel)
        defaults = {
            "kldb": self.settings.kldb_source,
            "kldb_isco": self.settings.kldb_isco_source,
            "esco_onet": self.settings.esco_onet_source,
        }
        if ds not in defaults:
            raise ValueError("Datensatz: onet, kldb, kldb_isco oder esco_onet")
        src = quelle or defaults[ds]
        if not src:
            raise ValueError(f"Für '{ds}' bitte 'quelle' angeben (URL oder lokaler Pfad zu .xlsx/.csv); siehe README.")
        content, name = await self._load_source(src)
        rows = tables.read_table(content, name)
        run_id = self.store.begin_run(ds, f"import.{ds}", {"quelle": src})
        results: list[UpsertResult] = []
        with self.store.transaction():
            if ds == "kldb":
                parsed = tables.parse_kldb(rows)
                codes = {p["code"] for p in parsed}
                for p in parsed:
                    results.append(
                        self.store.upsert_record(
                            SRC_KLDB, "kldb", p["code"], p, title=p["titel"], run_id=run_id, origin=src
                        )
                    )
                    self.store.upsert_node(
                        g.kldb_id(p["code"]),
                        "Klassifikation",
                        p["titel"],
                        _compact(
                            {
                                "system": "KldB 2010",
                                "ebene": p["ebene_name"],
                                "anforderungsniveau": p["anforderungsniveau"],
                            }
                        ),
                    )
                    parent = next((c for c in g.kldb_parents(p["code"]) if c in codes), None)
                    if parent:
                        self.store.upsert_edge(
                            g.kldb_id(p["code"]), g.kldb_id(parent), g.UNTERGRUPPE_VON, source=SRC_KLDB
                        )
            elif ds == "kldb_isco":
                parsed = tables.parse_kldb_isco(rows)
                for p in parsed:
                    key = f"{p['kldb']}->{p['isco']}"
                    results.append(
                        self.store.upsert_record(SRC_KLDB_ISCO, "mapping", key, p, title=key, run_id=run_id, origin=src)
                    )
                    self.store.upsert_node(
                        g.kldb_id(p["kldb"]), "Klassifikation", p.get("kldb_titel"), {"system": "KldB 2010"}
                    )
                    self.store.upsert_node(
                        g.isco_id(p["isco"]), "Klassifikation", p.get("isco_titel"), {"system": "ISCO-08"}
                    )
                    self.store.upsert_edge(
                        g.kldb_id(p["kldb"]),
                        g.isco_id(p["isco"]),
                        g.ENTSPRICHT,
                        _compact({"hinweis": p.get("hinweis"), "quelle": "Umsteigeschlüssel BA"}),
                        source=SRC_KLDB_ISCO,
                    )
            else:
                parsed = tables.parse_esco_onet(rows)
                for p in parsed:
                    key = f"{p['esco_uri']}->{p['onet_soc']}"
                    results.append(
                        self.store.upsert_record(SRC_ESCO_ONET, "mapping", key, p, title=key, run_id=run_id, origin=src)
                    )
                    self.store.upsert_node(g.esco_id(p["esco_uri"]), "Beruf", p.get("esco_titel"), {"quelle": "ESCO"})
                    self.store.upsert_node(g.onet_id(p["onet_soc"]), "Beruf", p.get("onet_titel"), {"quelle": "O*NET"})
                    self.store.upsert_edge(
                        g.esco_id(p["esco_uri"]),
                        g.onet_id(p["onet_soc"]),
                        g.ENTSPRICHT,
                        _compact({"art": p.get("art"), "quelle": "ESCO–O*NET-Crosswalk"}),
                        source=SRC_ESCO_ONET,
                    )
        self.store.finish_run(run_id, results=results)
        if not results:
            return {
                "datensatz": ds,
                "importiert": 0,
                "fehler": "Keine passenden Zeilen erkannt. Bitte Datei und "
                "Spalten prüfen (KldB: Schlüssel + Titel; Umsteiger: KldB 5-Steller + ISCO 4-Steller; Crosswalk: "
                "ESCO-URI + O*NET-SOC-Code).",
            }
        return {"datensatz": ds, "quelle": src, **self._counts(results)}

    async def _import_onet(self, quelle: str | None, version: str | None, alternativtitel: bool) -> dict[str, Any]:
        wanted = [onet.FILES["berufe"], onet.FILES["aufgaben"]] + (
            [onet.FILES["alternativtitel"]] if alternativtitel else []
        )
        if quelle and not quelle.startswith(("http://", "https://")):
            files = onet.read_local(quelle, wanted)
            version_used = version or "lokal"
        elif quelle:
            content, _ = await self._load_source(quelle)
            files = onet.read_zip(content, wanted)
            version_used = version or "url"
        else:
            version_used = version or self.settings.onet_version or await self.onet.detect_version() or "31_0"
            files = await self.onet.download(version_used, wanted)
        if onet.FILES["aufgaben"] not in files or onet.FILES["berufe"] not in files:
            raise SourceError("O*NET-Dateien 'Occupation Data' und 'Task Statements' nicht gefunden.")
        alt = (
            onet.alternate_title_rows(onet.parse_tsv(files[onet.FILES["alternativtitel"]]))
            if onet.FILES["alternativtitel"] in files
            else {}
        )
        run_id = self.store.begin_run(SRC_ONET, "import.onet", {"version": version_used})
        occ_results: list[UpsertResult] = []
        task_results: list[UpsertResult] = []
        with self.store.transaction():
            for row in onet.parse_tsv(files[onet.FILES["berufe"]]):
                occ = onet.occupation_record(row)
                if not occ:
                    continue
                key, data, title = occ
                if alt.get(key):
                    data["alternativtitel"] = alt[key][:40]
                occ_results.append(
                    self.store.upsert_record(
                        SRC_ONET,
                        "beruf",
                        key,
                        data,
                        title=title,
                        run_id=run_id,
                        text=_join(title, " ".join(data.get("alternativtitel", [])), data.get("beschreibung")),
                    )
                )
                self.store.upsert_node(g.onet_id(key), "Beruf", title, {"quelle": "O*NET", "version": version_used})
            new_keys = set()
            for row in onet.parse_tsv(files[onet.FILES["aufgaben"]]):
                task = onet.task_record(row)
                if not task:
                    continue
                key, data, title = task
                new_keys.add(key)
                task_results.append(
                    self.store.upsert_record(SRC_ONET, "aufgabe", key, data, title=title, run_id=run_id)
                )
                tid = g.task_id(SRC_ONET, key)
                self.store.upsert_node(tid, "Aufgabe", title, {"quelle": "O*NET"})
                self.store.upsert_edge(
                    tid,
                    g.onet_id(data["soc"]),
                    g.TEIL_VON,
                    _compact({"task_type": data["task_type"], "incumbents_responding": data["incumbents_responding"]}),
                    source=SRC_ONET,
                )
            gone = 0
            for key in self.store.keys(SRC_ONET, "aufgabe", status="aktiv"):
                if key not in new_keys and self.store.mark_gone(SRC_ONET, "aufgabe", key, run_id=run_id):
                    gone += 1
        self.store.finish_run(run_id, results=occ_results + task_results)
        return {
            "datensatz": "onet",
            "version": version_used,
            "berufe": self._counts(occ_results),
            "aufgaben": {**self._counts(task_results), "verschwunden": gone},
            "lizenz": "O*NET-Datenbank von USDOL/ETA, CC BY 4.0 – Namensnennung erforderlich.",
        }

    @staticmethod
    def _counts(results: list[UpsertResult]) -> dict[str, int]:
        c = Counter(r.status for r in results)
        return {
            "gesamt": len(results),
            "neu": c.get("neu", 0),
            "geaendert": c.get("geaendert", 0),
            "unveraendert": c.get("unveraendert", 0),
            "wieder_da": c.get("wieder_da", 0),
        }
