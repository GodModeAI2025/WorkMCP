"""MCP tool layer (official MCP Python SDK 2.x, ``MCPServer``)."""

from __future__ import annotations

import functools
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from . import __version__
from .config import Settings
from .http import SourceError
from .service import KnowledgeService
from .sources.adzuna import AdzunaNotConfigured

INSTRUCTIONS = """\
WorkMCP liefert Kontext für einen deutschen Job-Graphen: Stellenanzeigen (BA-Jobsuche, Arbeitnow, ATS-Karriereseiten),
Berufe und Aufgaben (BERUFENET, KldB 2010, ESCO, O*NET), Gehälter (Entgeltatlas, optional Adzuna) und
Automatisierungssignale (Hacker News).

Gedächtnis: Jeder Abruf wird lokal gespeichert. Wiederholte Anfragen kommen innerhalb der Gültigkeitsdauer aus dem
Speicher; neue Abrufe ergänzen neue und geänderte Datensätze (mit Versionen) und melden im Feld "gedaechtnis.delta",
was neu, geändert oder nicht mehr enthalten ist. get_changes zeigt den Verlauf, get_history alle Versionen eines
Datensatzes, aktualisieren=true erzwingt einen frischen Abruf.

Typischer Ablauf: get_role_context(rolle) für den Überblick → get_tasks / get_skills / get_salary für Details →
find_automation_signals für Automatisierungsindizien → record_extraction, um extrahierte Aufgaben/Skills/
Bewertungen im Graphen zu speichern. Einmalig import_reference_data('onet') für O*NET-Aufgaben ausführen;
KldB-Systematik, KldB→ISCO-Umsteigeschlüssel und ESCO↔O*NET-Crosswalk werden als Datei/URL importiert.

Rechtlicher Hinweis: Nutzungsbedingungen und Lizenzen der Quellen sind von den Nutzenden selbst zu prüfen
(z. B. O*NET CC BY 4.0 mit Namensnennung; BA-Endpunkte sind keine offiziell zugesicherte API). Keine Rechtsberatung.
"""

READ_LOCAL = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
FETCH = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
WRITE_LOCAL = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

_F = TypeVar("_F", bound=Callable[..., Awaitable[Any]])


def _guard(fn: _F) -> _F:
    """Turn anticipated failures into ToolError so the model sees the message (not a generic crash)."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except (ValueError, SourceError, FileNotFoundError, AdzunaNotConfigured) as exc:
            raise ToolError(str(exc)) from exc

    return wrapper  # type: ignore[return-value]


class AufgabeIn(BaseModel):
    text: str = Field(description="Aufgabe in eigenen Worten, z. B. 'Eingangsrechnungen prüfen und kontieren'")
    anteil_wochenarbeitszeit: float | None = Field(None, description="Geschätzter Anteil an der Wochenarbeitszeit, 0–1")
    kanonisch: str | None = Field(
        None, description="Knoten-ID einer kanonischen Aufgabe (O*NET/BERUFENET), falls bekannt"
    )


class AutomatisierungIn(BaseModel):
    aufgabe: str = Field(description="Knoten-ID oder Text der Aufgabe")
    signal: str = Field(description="Knoten-ID eines Signals (automatisierung:...) oder URL einer Quelle")
    bewertung: float | None = Field(None, description="Automatisierbarkeit 0–1")
    anteil_wochenarbeitszeit: float | None = Field(None, description="Anteil der Aufgabe an der Wochenarbeitszeit, 0–1")
    notiz: str | None = None


class _Holder:
    def __init__(self, service: KnowledgeService | None, settings: Settings | None):
        self._service = service
        self._settings = settings
        self._owned = service is None

    def get(self) -> KnowledgeService:
        if self._service is None:
            self._service = KnowledgeService(self._settings)
        return self._service

    async def close(self) -> None:
        if self._owned and self._service is not None:
            await self._service.aclose()
            self._service = None


def create_server(service: KnowledgeService | None = None, settings: Settings | None = None) -> MCPServer:
    holder = _Holder(service, settings)

    @asynccontextmanager
    async def lifespan(_app: MCPServer) -> AsyncIterator[dict[str, Any]]:
        try:
            yield {}
        finally:
            await holder.close()

    mcp: MCPServer = MCPServer(
        "workmcp",
        title="WorkMCP – Job-Graph Deutschland",
        description="Stellen, Berufe, Aufgaben, Skills, Gehälter und Automatisierungssignale mit Gedächtnis",
        instructions=INSTRUCTIONS,
        version=__version__,
        website_url="https://github.com/GodModeAI2025/WorkMCP",
        lifespan=lifespan,
    )

    def svc() -> KnowledgeService:
        return holder.get()

    # ------------------------------------------------------------ job ads

    @mcp.tool(annotations=FETCH)
    @_guard
    async def search_jobs(
        was: Annotated[str | None, Field(description="Jobtitel/Stichwort, z. B. 'Buchhalter'")] = None,
        wo: Annotated[str | None, Field(description="Ort oder PLZ, z. B. 'Berlin'")] = None,
        umkreis: Annotated[int | None, Field(description="Umkreis in km um 'wo'")] = None,
        seiten: Annotated[int, Field(ge=1, le=10, description="Anzahl Ergebnisseiten")] = 1,
        groesse: Annotated[int, Field(ge=1, le=100, description="Treffer pro Seite")] = 25,
        veroeffentlicht_seit: Annotated[
            int | None, Field(ge=0, le=100, description="Nur Stellen der letzten N Tage")
        ] = None,
        angebotsart: Annotated[
            str, Field(description="arbeit, ausbildung, praktikum oder selbstaendigkeit")
        ] = "arbeit",
        arbeitszeit: Annotated[
            list[str] | None, Field(description="vollzeit, teilzeit, schicht, homeoffice, minijob")
        ] = None,
        befristung: Annotated[str | None, Field(description="befristet oder unbefristet")] = None,
        berufsfeld: Annotated[str | None, Field(description="Berufsfeld, z. B. 'Informatik'")] = None,
        arbeitgeber: Annotated[str | None, Field(description="Arbeitgebername")] = None,
        zeitarbeit: Annotated[
            bool | None, Field(description="Zeitarbeitsfirmen einbeziehen (Standard der BA: ja)")
        ] = None,
        aktualisieren: Annotated[bool, Field(description="Frisch abrufen statt Speicher zu nutzen")] = False,
    ) -> dict[str, Any]:
        """Stellensuche in der Jobbörse der Bundesagentur für Arbeit (größter Stellenbestand in Deutschland).

        Speichert jede Anzeige im Gedächtnis und meldet im Delta neue, geänderte und nicht mehr enthaltene
        Anzeigen gegenüber der letzten identischen Suche. Details mit get_job_details(refnr)."""
        return await svc().search_jobs(
            was=was,
            wo=wo,
            umkreis=umkreis,
            seiten=seiten,
            groesse=groesse,
            veroeffentlicht_seit=veroeffentlicht_seit,
            angebotsart=angebotsart,
            arbeitszeit=arbeitszeit,
            befristung=befristung,
            berufsfeld=berufsfeld,
            arbeitgeber=arbeitgeber,
            zeitarbeit=zeitarbeit,
            aktualisieren=aktualisieren,
        )

    @mcp.tool(annotations=FETCH)
    @_guard
    async def get_job_details(
        refnr: Annotated[str, Field(description="Referenznummer aus search_jobs, z. B. '10000-1184867112-S'")],
        aktualisieren: bool = False,
    ) -> dict[str, Any]:
        """Volltext und Details einer BA-Stellenanzeige (Beschreibung, Branche, Fertigkeiten, Vergütung).

        Nicht mehr vorhandene Anzeigen werden im Gedächtnis als 'verschwunden' markiert. Kontaktpersonen werden
        vor dem Speichern entfernt (Datenminimierung)."""
        return await svc().get_job_details(refnr, aktualisieren)

    @mcp.tool(annotations=FETCH)
    @_guard
    async def search_arbeitnow(
        was: Annotated[
            str | None, Field(description="Stichwörter (alle müssen vorkommen), z. B. 'python backend'")
        ] = None,
        remote_only: Annotated[bool, Field(description="Nur Remote-Stellen")] = False,
        ort: Annotated[str | None, Field(description="Ort, z. B. 'Berlin'")] = None,
        visa_sponsorship: Annotated[bool, Field(description="Nur Stellen mit Visa-Sponsoring")] = False,
        seiten: Annotated[int, Field(ge=1, le=10, description="Seiten à bis zu 100 Stellen")] = 1,
        aktualisieren: bool = False,
    ) -> dict[str, Any]:
        """Stellen von Arbeitnow (kostenlos, ohne Schlüssel; aggregiert ATS-Feeds wie Greenhouse, Personio, Recruitee).

        Gefiltert wird lokal über die abgerufenen Seiten; alle abgerufenen Stellen werden gespeichert."""
        return await svc().search_arbeitnow(
            was=was,
            ort=ort,
            remote_only=remote_only,
            visa_sponsorship=visa_sponsorship,
            seiten=seiten,
            aktualisieren=aktualisieren,
        )

    @mcp.tool(annotations=FETCH)
    @_guard
    async def get_ats_jobs(
        company_slug: Annotated[
            str,
            Field(
                description="Firmenkennung (z. B. 'personio') oder Karriereseiten-URL "
                "(z. B. 'https://jobs.lever.co/palantir', bei Workday zwingend die URL)"
            ),
        ],
        ats: Annotated[
            Literal[
                "greenhouse",
                "lever",
                "ashby",
                "workable",
                "recruitee",
                "personio",
                "smartrecruiters",
                "bamboohr",
                "workday",
            ]
            | None,
            Field(description="ATS, falls bekannt; sonst wird automatisch erkannt"),
        ] = None,
        suchbegriff: Annotated[str | None, Field(description="Filter auf Titel/Abteilung/Beschreibung")] = None,
        ort: Annotated[str | None, Field(description="Filter auf Standort")] = None,
        max_jobs: Annotated[int, Field(ge=1, le=2000)] = 200,
        aktualisieren: bool = False,
    ) -> dict[str, Any]:
        """Offene Stellen direkt aus dem Bewerbermanagement eines Arbeitgebers (öffentliche Job-Board-APIs ohne Login).

        Unterstützt Greenhouse, Lever, Ashby, Workable, Recruitee, Personio (XML), SmartRecruiters, BambooHR und
        Workday. Liefert Primärdaten wie Abteilung, Seniority, Anstellungsart. Das Delta zeigt neue und
        geschlossene Stellen seit dem letzten Abruf."""
        return await svc().get_ats_jobs(
            company_slug, ats=ats, suchbegriff=suchbegriff, ort=ort, max_jobs=max_jobs, aktualisieren=aktualisieren
        )

    @mcp.tool(annotations=FETCH)
    @_guard
    async def adzuna_salary(
        was: Annotated[str, Field(description="Jobtitel/Stichwort, z. B. 'data engineer'")],
        standort: Annotated[
            list[str] | None, Field(description="Standortpfad wie bei Adzuna, z. B. ['Deutschland', 'Berlin']")
        ] = None,
        kategorie: Annotated[
            str | None, Field(description="Adzuna-Kategorie-Tag für den Gehaltsverlauf, z. B. 'it-jobs'")
        ] = None,
        monate: Annotated[int, Field(ge=1, le=36)] = 12,
        aktualisieren: bool = False,
    ) -> dict[str, Any]:
        """Gehaltsverteilung (Histogramm), Top-Arbeitgeber und optional Gehaltsverlauf aus Adzuna-Inseraten.

        Optional: braucht einen kostenlosen Adzuna-Developer-Key (WORKMCP_ADZUNA_APP_ID/_APP_KEY). Für amtliche
        Medianentgelte nach Beruf get_salary (Entgeltatlas) verwenden."""
        return await svc().adzuna_salary(
            was, standort=standort, kategorie=kategorie, monate=monate, aktualisieren=aktualisieren
        )

    # --------------------------------------------------------- occupations

    @mcp.tool(annotations=FETCH)
    @_guard
    async def search_occupation(
        query: Annotated[str, Field(description="Berufsbezeichnung, z. B. 'Buchhalter'")],
        kldb_code: Annotated[str | None, Field(description="Optional: KldB-2010-Code zum Nachschlagen")] = None,
        quellen: Annotated[
            list[Literal["berufenet", "esco", "kldb", "onet"]] | None, Field(description="Standard: alle")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        sprache: Annotated[str | None, Field(description="Sprache für ESCO, Standard 'de'")] = None,
        aktualisieren: bool = False,
    ) -> dict[str, Any]:
        """Berufe finden: BERUFENET (mit KldB-Zuordnung), ESCO-Berufe, KldB-Systematik und O*NET-Titel."""
        return await svc().search_occupation(
            query, kldb_code=kldb_code, quellen=quellen, limit=limit, sprache=sprache, aktualisieren=aktualisieren
        )

    @mcp.tool(annotations=FETCH)
    @_guard
    async def get_occupation(
        beruf_id: Annotated[
            str, Field(description="berufenet:<id>, kldb:<code>, isco:<code>, onet:<soc> oder ESCO-URI")
        ],
        sprache: str | None = None,
        aktualisieren: bool = False,
    ) -> dict[str, Any]:
        """Profil eines Berufs bzw. einer Berufsklasse mit Klassifikation, Aufgaben, Skills und Verknüpfungen."""
        return await svc().get_occupation(beruf_id, sprache=sprache, aktualisieren=aktualisieren)

    @mcp.tool(annotations=FETCH)
    @_guard
    async def get_tasks(
        beruf: Annotated[str, Field(description="Freitext, berufenet:<id>, kldb:<code>, onet:<soc> oder ESCO-URI")],
        quellen: Annotated[list[Literal["onet", "berufenet"]] | None, Field(description="Standard: beide")] = None,
        nur_kern: Annotated[bool, Field(description="Nur O*NET-Kernaufgaben (Core)")] = False,
        limit: Annotated[int, Field(ge=1, le=200)] = 40,
        sprache: str | None = None,
    ) -> dict[str, Any]:
        """Kanonische Aufgabenliste eines Berufs: O*NET Task Statements (Core/Supplemental) und BERUFENET-Tätigkeiten.

        Die Zuordnung läuft über BERUFENET→KldB→ISCO→ESCO→O*NET (Crosswalks müssen importiert sein)."""
        return await svc().get_tasks(beruf, quellen=quellen, nur_kern=nur_kern, limit=limit, sprache=sprache)

    @mcp.tool(annotations=FETCH)
    @_guard
    async def get_skills(
        beruf: Annotated[str, Field(description="Freitext, ESCO-URI, kldb:<code> oder berufenet:<id>")],
        relation: Annotated[Literal["alle", "essential", "optional"], Field(description="ESCO-Relation")] = "alle",
        sprache: str | None = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 40,
    ) -> dict[str, Any]:
        """Skills eines Berufs: ESCO essential/optional plus Häufigkeiten aus gespeicherten BA-Stellenanzeigen."""
        return await svc().get_skills(beruf, relation=relation, sprache=sprache, limit=limit)

    @mcp.tool(annotations=FETCH)
    @_guard
    async def crosswalk(
        code: Annotated[
            str,
            Field(
                description="Code im Ausgangssystem (KldB 5-stellig, ISCO 4-stellig, ESCO-URI, O*NET-SOC, BERUFENET-ID)"
            ),
        ],
        von: Annotated[Literal["kldb", "isco", "esco", "onet", "berufenet"], Field(description="Ausgangssystem")],
        nach: Annotated[Literal["kldb", "isco", "esco", "onet", "berufenet"], Field(description="Zielsystem")],
        sprache: str | None = None,
    ) -> dict[str, Any]:
        """Übersetzt Berufscodes zwischen KldB 2010, ISCO-08, ESCO, O*NET und BERUFENET (auch über mehrere Stufen)."""
        return await svc().crosswalk(code, von, nach, sprache=sprache)

    @mcp.tool(annotations=FETCH)
    @_guard
    async def get_salary(
        kldb: Annotated[str, Field(description="KldB-2010-Code mit 3–5 Ziffern, z. B. '72213'")],
        region: Annotated[str | None, Field(description="z. B. 'Deutschland', 'Bayern', 'München'")] = None,
        niveau: Annotated[str | None, Field(description="helfer, fachkraft, spezialist oder experte")] = None,
        geschlecht: Annotated[str | None, Field(description="gesamt, männer oder frauen")] = None,
        alter: Annotated[str | None, Field(description="gesamt, unter 25, 25 bis unter 55, ab 55")] = None,
        branche: Annotated[str | None, Field(description="z. B. 'information und kommunikation'")] = None,
        aktualisieren: bool = False,
    ) -> dict[str, Any]:
        """Amtliche Medianentgelte (mit Quartilen) nach Beruf aus dem Entgeltatlas der BA."""
        return await svc().get_salary(
            kldb,
            region=region,
            niveau=niveau,
            geschlecht=geschlecht,
            alter=alter,
            branche=branche,
            aktualisieren=aktualisieren,
        )

    @mcp.tool(annotations=FETCH)
    @_guard
    async def get_role_context(
        rolle: Annotated[str, Field(description="Rolle/Beruf, z. B. 'Buchhalter'")],
        ort: Annotated[str | None, Field(description="Optional: Ort/Bundesland für Marktsignal und Gehalt")] = None,
        sprache: str | None = None,
        mit_signalen: Annotated[bool, Field(description="Zusätzlich Automatisierungssignale abrufen")] = False,
    ) -> dict[str, Any]:
        """Rollenkontext in einem Aufruf: Zuordnung, Aufgaben (BERUFENET/O*NET), Skills (ESCO), Gehalt (Entgeltatlas)
        und Marktsignal (offene Stellen laut BA)."""
        return await svc().get_role_context(rolle, ort=ort, sprache=sprache, mit_signalen=mit_signalen)

    @mcp.tool(annotations=FETCH)
    @_guard
    async def find_automation_signals(
        suchbegriff: Annotated[
            str, Field(description="Englisch funktioniert am besten, z. B. 'automated invoice processing'")
        ],
        aufgabe_id: Annotated[
            str | None, Field(description="Optional: Aufgaben-Knoten, der mit den Signalen verknüpft wird")
        ] = None,
        zeitraum_tage: Annotated[int | None, Field(ge=1, description="Nur Beiträge der letzten N Tage")] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
        nur_kommentare: bool = False,
        aktualisieren: bool = False,
    ) -> dict[str, Any]:
        """Automatisierungssignale aus Hacker News (Berichte, wie Tätigkeiten automatisiert wurden)."""
        return await svc().find_automation_signals(
            suchbegriff,
            aufgabe_id=aufgabe_id,
            zeitraum_tage=zeitraum_tage,
            limit=limit,
            nur_kommentare=nur_kommentare,
            aktualisieren=aktualisieren,
        )

    @mcp.tool(annotations=FETCH)
    @_guard
    async def commoncrawl_lookup(
        url_muster: Annotated[str, Field(description="URL-Muster für den Index, z. B. 'example.com/karriere/*'")],
        crawl: Annotated[str | None, Field(description="Crawl-ID wie 'CC-MAIN-2026-30', Standard: neuester")] = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 20,
        text_abrufen: Annotated[
            int, Field(ge=0, le=5, description="Für die ersten N Treffer den Seitentext laden")
        ] = 0,
    ) -> dict[str, Any]:
        """Common-Crawl-Index nach archivierten Seiten (z. B. Karriereseiten) durchsuchen und optional Text laden."""
        return await svc().commoncrawl_lookup(url_muster, crawl=crawl, limit=limit, text_abrufen=text_abrufen)

    @mcp.tool(annotations=FETCH)
    @_guard
    async def import_reference_data(
        datensatz: Annotated[
            Literal["onet", "kldb", "kldb_isco", "esco_onet"],
            Field(
                description="onet = O*NET-Berufe und Task Statements; kldb = KldB-2010-Systematik; "
                "kldb_isco = Umsteigeschlüssel KldB→ISCO-08; esco_onet = ESCO↔O*NET-Crosswalk"
            ),
        ],
        quelle: Annotated[
            str | None, Field(description="URL oder lokaler Pfad (xlsx/csv/zip/Ordner); bei onet optional")
        ] = None,
        onet_version: Annotated[str | None, Field(description="z. B. '31_0'; Standard: automatisch erkannt")] = None,
        alternativtitel: Annotated[bool, Field(description="O*NET Alternate Titles mit importieren")] = True,
    ) -> dict[str, Any]:
        """Referenzdaten importieren bzw. aktualisieren. Wiederholte Importe ergänzen neue/geänderte Einträge und
        markieren entfallene (z. B. zwischen O*NET-Releases)."""
        return await svc().import_reference_data(
            datensatz, quelle=quelle, onet_version=onet_version, alternativtitel=alternativtitel
        )

    # -------------------------------------------------------------- memory

    @mcp.tool(annotations=WRITE_LOCAL)
    @_guard
    async def record_extraction(
        bezug: Annotated[
            str, Field(description="Knoten-ID (z. B. 'stelle:ba:<refnr>', 'berufenet:<id>') oder BA-refnr")
        ],
        aufgaben: Annotated[list[AufgabeIn] | None, Field(description="Extrahierte Aufgaben")] = None,
        skills: Annotated[list[str] | None, Field(description="Extrahierte Skills")] = None,
        automatisierungen: Annotated[
            list[AutomatisierungIn] | None, Field(description="Bewertete Automatisierungsmöglichkeiten je Aufgabe")
        ] = None,
        quelle: Annotated[str, Field(description="Herkunft, z. B. 'llm' oder 'experte:<name>'")] = "llm",
    ) -> dict[str, Any]:
        """Vom Modell oder von Fachexperten extrahierte Aufgaben, Skills und Automatisierungsbewertungen versioniert
        im Graphen speichern. Liefert Vorschläge passender kanonischer Aufgaben (Deduplizierung)."""
        return svc().record_extraction(
            bezug,
            aufgaben=[a.model_dump() for a in aufgaben or []],
            skills=skills,
            automatisierungen=[a.model_dump() for a in automatisierungen or []],
            quelle=quelle,
        )

    @mcp.tool(annotations=WRITE_LOCAL)
    @_guard
    async def remember(
        art: Annotated[str, Field(description="Art des Eintrags, z. B. 'rollenprofil', 'feedback', 'notiz'")],
        schluessel: Annotated[str, Field(description="Eindeutiger Schlüssel innerhalb der Art")],
        daten: Annotated[dict[str, Any], Field(description="Beliebige strukturierte Daten")],
        titel: str | None = None,
        quelle: Annotated[
            str, Field(description="Herkunft, z. B. 'eigene', 'kunde:<name>', 'experte:<name>'")
        ] = "eigene",
    ) -> dict[str, Any]:
        """Eigene Daten (interne Rollenprofile, Expertenfeedback) versioniert im Gedächtnis speichern oder ergänzen."""
        return svc().remember(art, schluessel, daten, titel=titel, quelle=quelle)

    @mcp.tool(annotations=READ_LOCAL)
    @_guard
    async def search_knowledge(
        suchbegriff: Annotated[str, Field(description="Volltextsuche über alles Gespeicherte")],
        art: Annotated[str | None, Field(description="z. B. 'stelle', 'aufgabe', 'beruf', 'kldb', 'signal'")] = None,
        quelle: Annotated[str | None, Field(description="z. B. 'ba_jobsuche', 'onet', 'berufenet', 'ats'")] = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 20,
    ) -> dict[str, Any]:
        """Offline-Suche im Gedächtnis (auch zur Zuordnung freier Aufgabentexte zu kanonischen Aufgaben)."""
        return svc().search_knowledge(suchbegriff, art=art, quelle=quelle, limit=limit)

    @mcp.tool(annotations=READ_LOCAL)
    @_guard
    async def get_changes(
        seit: Annotated[str | None, Field(description="z. B. '24h', '7d', '2026-10-01'")] = None,
        quelle: str | None = None,
        art: str | None = None,
        ereignis: Annotated[Literal["neu", "geaendert", "verschwunden", "wieder_da"] | None, Field()] = None,
        limit: Annotated[int, Field(ge=1, le=500)] = 50,
    ) -> dict[str, Any]:
        """Änderungsprotokoll des Gedächtnisses: was ist neu, geändert, verschwunden oder wieder aufgetaucht."""
        return svc().get_changes(seit=seit, quelle=quelle, art=art, ereignis=ereignis, limit=limit)

    @mcp.tool(annotations=READ_LOCAL)
    @_guard
    async def get_history(
        quelle: Annotated[str, Field(description="z. B. 'ba_jobsuche'")],
        art: Annotated[str, Field(description="z. B. 'stelle_detail'")],
        schluessel: Annotated[str, Field(description="z. B. die refnr")],
    ) -> dict[str, Any]:
        """Alle gespeicherten Versionen eines Datensatzes mit feldgenauen Änderungen."""
        return svc().get_history(quelle, art, schluessel)

    @mcp.tool(annotations=READ_LOCAL)
    @_guard
    async def knowledge_stats() -> dict[str, Any]:
        """Überblick über das Gedächtnis: Datensätze je Quelle, Versionen, Graph-Knoten/-Kanten, letzte Abrufe."""
        return svc().knowledge_stats()

    @mcp.tool(annotations=READ_LOCAL)
    @_guard
    async def graph_neighbors(
        knoten: Annotated[str, Field(description="Knoten-ID (z. B. 'kldb:72213') oder Teil eines Labels")],
        kantentyp: Annotated[
            str | None, Field(description="z. B. ERFORDERT, TEIL_VON, ENTSPRICHT, AUTOMATISIERBAR_DURCH")
        ] = None,
        richtung: Literal["beide", "ausgehend", "eingehend"] = "beide",
        limit: Annotated[int, Field(ge=1, le=500)] = 50,
    ) -> dict[str, Any]:
        """Nachbarn eines Knotens im Job-Graphen (Berufe, Aufgaben, Skills, Stellen, Branchen, Regionen ...)."""
        return svc().graph_neighbors(knoten, kantentyp=kantentyp, richtung=richtung, limit=limit)

    @mcp.tool(annotations=WRITE_LOCAL)
    @_guard
    async def export_knowledge(
        format: Annotated[
            Literal["json", "cypher", "graphml", "archivy"],
            Field(description="cypher = Neo4j, graphml = NetworkX/Gephi, archivy = Notizen für Archivy"),
        ] = "json",
        pfad: Annotated[str | None, Field(description="Zieldatei bzw. -ordner (Standard neben der Datenbank)")] = None,
    ) -> dict[str, Any]:
        """Graph exportieren: JSON, Neo4j-Cypher, GraphML oder als Archivy-Wissensdatenbank (Markdown-Notizen)."""
        return svc().export_knowledge(format, pfad)

    @mcp.tool(annotations=FETCH)
    @_guard
    async def check_sources() -> dict[str, Any]:
        """Erreichbarkeit aller Datenquellen von diesem Rechner aus prüfen (HTTP-Status und Latenz je Quelle)."""
        return await svc().check_sources()

    # ------------------------------------------------------------- prompts

    @mcp.prompt()
    def rollen_analyse(rolle: str, ort: str = "") -> str:
        """Leitfaden: Rolle → Aufgaben → Automatisierungspotenzial (mit Quellen und Gedächtnis)."""
        where = f" in {ort}" if ort else ""
        return (
            f"Analysiere die Rolle '{rolle}'{where} mit den WorkMCP-Tools:\n"
            f"1. get_role_context(rolle='{rolle}'{f', ort={ort!r}' if ort else ''}) für Zuordnung, Aufgaben, Skills, "
            "Gehalt und Marktsignal.\n"
            "2. get_tasks für die vollständige Aufgabenliste (O*NET Core zuerst), get_skills für ESCO-Skills.\n"
            "3. Für die 5 zeitintensivsten Aufgaben find_automation_signals (englische Suchbegriffe) aufrufen.\n"
            "4. Ergebnis mit record_extraction speichern (Aufgaben mit geschätztem Anteil an der Wochenarbeitszeit, "
            "Automatisierungen mit Bewertung 0–1 und Quelle).\n"
            "5. Am Ende Quellen nennen (BA/BERUFENET, ESCO, O*NET CC BY 4.0, Entgeltatlas) und Unsicherheiten "
            "kennzeichnen. Keine Rechtsberatung."
        )

    return mcp
