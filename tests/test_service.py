from __future__ import annotations

import copy
import gzip
import json

import httpx
import pytest

from tests import fixtures as fx
from tests.conftest import Router
from workmcp.service import KnowledgeService, parse_since, strip_personal

JOBS = r"rest\.arbeitsagentur\.de/jobboerse/jobsuche-service/pc/v6/jobs"
DETAILS = r"jobsuche-service/pc/v4/jobdetails/"
BERUFENET_LIST = r"infosysbub/bnet/pc/v1/berufe\?"
BERUFENET_DETAIL = r"infosysbub/bnet/pc/v1/berufe/58779"
ESCO_SEARCH = r"ec\.europa\.eu/esco/api/search"
ESCO_OCC = r"ec\.europa\.eu/esco/api/resource/occupation"
ESCO_CONCEPT = r"ec\.europa\.eu/esco/api/resource/concept"
ENTGELT = r"infosysbub/entgeltatlas/pc/v1/entgelte/"


# ------------------------------------------------------------------- jobs


async def test_search_jobs_memory_delta_and_ttl(service: KnowledgeService, router: Router) -> None:
    state = {"resp": copy.deepcopy(fx.JOBSUCHE_V6)}
    router.add("GET", JOBS, lambda _r: state["resp"])

    first = await service.search_jobs(was="Buchhalter", wo="Berlin")
    assert first["treffer_gesamt"] == 2 and first["anzahl"] == 2
    assert first["gedaechtnis"]["aus_speicher"] is False
    assert first["gedaechtnis"]["delta"]["erstabruf"] is True
    assert len(first["gedaechtnis"]["delta"]["neu"]) == 2

    second = await service.search_jobs(was="Buchhalter", wo="Berlin")
    assert second["gedaechtnis"]["aus_speicher"] is True
    assert router.count(JOBS) == 1  # served from memory within the TTL

    changed = copy.deepcopy(fx.JOBSUCHE_V6)
    changed["ergebnisliste"][0]["stellenangebotsTitel"] = "Buchhalter (m/w/d) – Teilzeit"
    changed["ergebnisliste"].pop(1)
    changed["ergebnisliste"].append({"referenznummer": "10002-1000000001-S", "stellenangebotsTitel": "Neu"})
    state["resp"] = changed
    third = await service.search_jobs(was="Buchhalter", wo="Berlin", aktualisieren=True)
    delta = third["gedaechtnis"]["delta"]
    assert delta["neu"] == ["10002-1000000001-S"]
    assert delta["geaendert"][0]["schluessel"] == "10000-1184867112-S"
    assert delta["geaendert"][0]["version"] == 2
    assert delta["nicht_mehr_enthalten"] == ["10001-1002716922-S"]
    history = service.get_history("ba_jobsuche", "stelle", "10000-1184867112-S")
    assert [v["version"] for v in history["versionen"]] == [1, 2]
    assert service.graph_neighbors("stelle:ba:10000-1184867112-S")["gefunden"] is True


async def test_search_jobs_falls_back_to_memory_when_source_down(service: KnowledgeService, router: Router) -> None:
    state = {"down": False}

    def handler(request: httpx.Request) -> object:
        if state["down"]:
            raise httpx.ConnectError("Netz weg", request=request)
        return fx.JOBSUCHE_V6

    router.add("GET", JOBS, handler)
    await service.search_jobs(was="Buchhalter")
    state["down"] = True
    res = await service.search_jobs(was="Buchhalter", aktualisieren=True)
    assert res["anzahl"] == 2
    assert res["gedaechtnis"]["aus_speicher"] is True
    assert "nicht erreichbar" in res["gedaechtnis"]["warnung"]


async def test_search_jobs_endpoint_fallback_to_v4(service: KnowledgeService, router: Router) -> None:
    router.add("GET", JOBS, httpx.Response(404))
    router.add("GET", r"jobsuche-service/pc/v4/app/jobs", fx.JOBSUCHE_V4)
    res = await service.search_jobs(was="Elektriker")
    assert res["stellen"][0]["refnr"] == "10000-1184867113-S"


async def test_search_jobs_requires_a_filter(service: KnowledgeService) -> None:
    with pytest.raises(ValueError):
        await service.search_jobs()


async def test_job_details_privacy_graph_and_gone(service: KnowledgeService, router: Router) -> None:
    detail = copy.deepcopy(fx.JOBDETAIL_V4_OLD)
    detail["kontaktdaten"] = {"name": "Erika Mustermann", "telefon": "0123"}
    detail["ansprechpartner"] = [{"name": "Max"}]
    router.add("GET", DETAILS, detail)
    res = await service.get_job_details("10000-1184867113-S")
    assert res["stelle"]["branche"] == "Elektroinstallation"
    rec = service.store.get_record("ba_jobsuche", "stelle_detail", "10000-1184867113-S")
    assert rec is not None and "kontaktdaten" not in rec.data and "ansprechpartner" not in rec.data
    edges = service.graph_neighbors("stelle:ba:10000-1184867113-S")["kanten"]
    types = {(e["typ"], e["knoten"]) for e in edges}
    assert ("GEHOERT_ZU", "branche:elektroinstallation") in types
    assert ("FUER_BERUF", "berufenet:9907") in types
    assert ("ERFORDERT", "skill:ba:wartung") in types

    router.add("GET", DETAILS, httpx.Response(404))
    gone = await service.get_job_details("10000-1184867113-S", aktualisieren=True)
    assert gone["status"] == "verschwunden"
    assert service.get_changes(ereignis="verschwunden")["aenderungen"][0]["schluessel"] == "10000-1184867113-S"


def test_strip_personal_and_parse_since() -> None:
    assert strip_personal({"a": 1, "kontaktDaten": {"x": 1}, "liste": [{"eMail": "x", "b": 2}]}) == {
        "a": 1,
        "liste": [{"b": 2}],
    }
    assert parse_since("24h") < parse_since("1h")  # type: ignore[operator]
    assert parse_since("2026-10-01").startswith("2026-10-01T00:00:00")  # type: ignore[union-attr]
    with pytest.raises(ValueError):
        parse_since("gestern")


async def test_search_arbeitnow_filters_locally(service: KnowledgeService, router: Router) -> None:
    router.add("GET", r"arbeitnow\.com/api/job-board-api", fx.ARBEITNOW_PAGE)
    res = await service.search_arbeitnow(remote_only=True)
    assert res["geprueft"] == 2 and res["anzahl"] == 1
    assert res["stellen"][0]["arbeitgeber"] == "Startup GmbH"
    res = await service.search_arbeitnow(was="koch", ort="münchen")
    assert [s["titel"] for s in res["stellen"]] == ["Koch (m/w/d)"]


# -------------------------------------------------------------------- ATS


async def test_ats_detection_and_memory(service: KnowledgeService, router: Router) -> None:
    router.add("GET", r"boards-api\.greenhouse\.io", httpx.Response(404))
    router.add("GET", r"api\.lever\.co", httpx.Response(404))
    router.add(
        "GET",
        r"api\.ashbyhq\.com/posting-api/job-board/acme",
        {
            "jobs": [
                {
                    "id": "j1",
                    "title": " Data Engineer ",
                    "department": "Engineering",
                    "location": "Berlin",
                    "secondaryLocations": [{"location": "Remote (DE)"}],
                    "isRemote": True,
                    "employmentType": "FullTime",
                    "jobUrl": "https://jobs.ashbyhq.com/acme/j1",
                    "descriptionHtml": "<p>Pipelines bauen</p>",
                }
            ]
        },
    )
    res = await service.get_ats_jobs("acme")
    assert res["gefunden"] is True and res["ats"] == "ashby"
    assert res["stellen"][0]["titel"] == "Data Engineer"
    assert res["stellen"][0]["orte"] == ["Berlin", "Remote (DE)"]
    assert [v["ats"] for v in res["versuche"]] == ["greenhouse", "lever"]

    calls_before = router.count(r"greenhouse|lever")
    again = await service.get_ats_jobs("acme", aktualisieren=True)
    assert again["ats"] == "ashby"
    assert router.count(r"greenhouse|lever") == calls_before  # remembered platform, no re-detection


async def test_ats_from_url_and_personio_redirect(service: KnowledgeService, router: Router) -> None:
    router.add(
        "GET",
        r"api\.lever\.co/v0/postings/palantir",
        [
            {
                "id": "p1",
                "text": "Backend Engineer",
                "categories": {"department": "Eng", "location": "London", "commitment": "Full-time"},
                "workplaceType": "hybrid",
                "createdAt": 1753564800000,
                "hostedUrl": "https://jobs.lever.co/palantir/p1",
            }
        ],
    )
    res = await service.get_ats_jobs("https://jobs.lever.co/palantir")
    assert res["ats"] == "lever" and res["stellen"][0]["veroeffentlicht"].startswith("2025-07-26")

    router.add(
        "GET", r"nope\.jobs\.personio\.de/xml", httpx.Response(307, headers={"location": "https://www.personio.com/"})
    )
    router.add("GET", r"www\.personio\.com", "<html>Marketing</html>")
    miss = await service.get_ats_jobs("nope", ats="personio")
    assert miss["gefunden"] is False and miss["versuche"][0]["ergebnis"] == "nicht vorhanden"


async def test_ats_personio_xml(service: KnowledgeService, router: Router) -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?><workzag-jobs><position><id>1834171</id>
    <subcompany>Muster SE</subcompany><office>München</office><additionalOffices><office>Berlin, Hamburg</office>
    </additionalOffices><department>Finance</department><recruitingCategory>Accounting</recruitingCategory>
    <name>Buchhalter (m/w/d)</name><employmentType>permanent</employmentType><seniority>experienced</seniority>
    <schedule>full-time</schedule><yearsOfExperience>2-5</yearsOfExperience>
    <jobDescriptions><jobDescription><name>Aufgaben</name><value><![CDATA[<ul><li>Kreditoren buchen</li></ul>]]>
    </value></jobDescription></jobDescriptions><createdAt>2026-10-01T10:00:00+00:00</createdAt></position>
    </workzag-jobs>"""
    router.add("GET", r"muster\.jobs\.personio\.de/xml", xml)
    res = await service.get_ats_jobs("muster", ats="personio")
    job = res["stellen"][0]
    assert job["seniority"] == "experienced" and job["erfahrung"] == "2-5"
    assert job["orte"] == ["München", "Berlin", "Hamburg"]
    assert "Kreditoren buchen" in job["beschreibung"]


async def test_adzuna_optional(service: KnowledgeService, router: Router) -> None:
    res = await service.adzuna_salary("data engineer")
    assert res["aktiv"] is False
    service.settings.adzuna_app_id, service.settings.adzuna_app_key = "id", "key"
    router.add("GET", r"api\.adzuna\.com/v1/api/jobs/de/histogram", {"histogram": {"40000": 120, "60000": 80}})
    router.add(
        "GET",
        r"api\.adzuna\.com/v1/api/jobs/de/top_companies",
        {"leaderboard": [{"canonical_name": "acme", "count": 12, "average_salary": 61000}]},
    )
    res = await service.adzuna_salary("data engineer")
    assert res["histogramm"] == {"40000": 120, "60000": 80}
    assert res["top_arbeitgeber"][0] == {"name": "acme", "stellen": 12, "durchschnittsgehalt": 61000}


# ------------------------------------------------------------ occupations


def _occupation_routes(router: Router) -> None:
    router.add("GET", BERUFENET_LIST, fx.BERUFENET_LIST)
    router.add("GET", BERUFENET_DETAIL, fx.BERUFENET_DETAIL)
    router.add(
        "GET",
        r"infosysbub/bnet/pc/v1/berufe/9069",
        [{"id": 9069, "kurzBezeichnungNeutral": "Finanzbuchhalter/in", "kldb2010": "B 72213"}],
    )
    router.add("GET", ESCO_SEARCH, fx.ESCO_SEARCH)
    router.add("GET", ESCO_OCC, fx.ESCO_OCCUPATION)
    router.add("GET", ESCO_CONCEPT, fx.ESCO_ISCO_GROUP)


async def test_search_occupation_and_berufenet_tasks(service: KnowledgeService, router: Router) -> None:
    _occupation_routes(router)
    res = await service.search_occupation("Buchhalter", quellen=["berufenet", "esco"])
    first = res["berufenet"]["berufe"][0]
    assert first["kldb2010"] == "72213" and first["aufgaben"] >= 3
    assert res["esco"]["berufe"][0]["uri"] == fx.ESCO_OCC_URI
    tasks = service.store.find_records(source="berufenet", kind="aufgabe")
    assert any(t.data["text"] == "Konten abstimmen" for t in tasks)
    edges = service.graph_neighbors("berufenet:58779")["kanten"]
    assert any(e["typ"] == "KLASSIFIZIERT_ALS" and e["knoten"] == "kldb:72213" for e in edges)
    hierarchy = service.graph_neighbors("kldb:72213", kantentyp="UNTERGRUPPE_VON", richtung="ausgehend")["kanten"]
    assert hierarchy[0]["knoten"] == "kldb:7221"


async def test_get_skills_from_esco(service: KnowledgeService, router: Router) -> None:
    _occupation_routes(router)
    res = await service.get_skills(fx.ESCO_OCC_URI)
    esco = res["esco"][0]
    assert esco["isco"] == "2411"
    assert [s["titel"] for s in esco["essential"]] == ["Buchführungsvorschriften anwenden", "Finanzberichte erstellen"]
    assert esco["optional"][0]["titel"] == "Steuerrecht"
    edges = service.graph_neighbors(f"esco:{fx.ESCO_OCC_URI}", kantentyp="ERFORDERT")["kanten"]
    assert len(edges) == 3


async def _import_reference(service: KnowledgeService, tmp_path, tasks: str = fx.ONET_TASKS) -> dict:
    onet_dir = tmp_path / "onet"
    onet_dir.mkdir(exist_ok=True)
    (onet_dir / "Occupation Data.txt").write_text(fx.ONET_OCCUPATIONS, encoding="utf-8")
    (onet_dir / "Task Statements.txt").write_text(tasks, encoding="utf-8")
    result = await service.import_reference_data("onet", quelle=str(onet_dir), alternativtitel=False)
    (tmp_path / "umsteiger.csv").write_text(
        "KldB 2010 (5-Steller);Bezeichnung KldB;ISCO-08 (4-Steller);Bezeichnung ISCO\n"
        "72213;Rechnungswesen - Fachkraft;2411;Accountants\n"
        "72213;Rechnungswesen - Fachkraft;4311;Bookkeeping clerks\n"
        "43413;Softwareentwicklung;2512;Software developers\n",
        encoding="utf-8",
    )
    await service.import_reference_data("kldb_isco", quelle=str(tmp_path / "umsteiger.csv"))
    (tmp_path / "crosswalk.csv").write_text(
        "esco_uri,esco_title,onet_id,onet_title,match\n"
        f"{fx.ESCO_OCC_URI},accountant,13-2011.00,Accountants and Auditors,exactMatch\n"
        "http://data.europa.eu/esco/occupation/x,a,13-2011.00,Accountants and Auditors,closeMatch\n"
        "http://data.europa.eu/esco/occupation/y,b,15-1252.00,Software Developers,closeMatch\n",
        encoding="utf-8",
    )
    await service.import_reference_data("esco_onet", quelle=str(tmp_path / "crosswalk.csv"))
    return result


async def test_onet_import_versioning_and_tasks(service: KnowledgeService, router: Router, tmp_path) -> None:
    _occupation_routes(router)
    first = await _import_reference(service, tmp_path)
    assert first["aufgaben"]["neu"] == 4 and first["berufe"]["neu"] == 2
    changed = fx.ONET_TASKS.replace("Prepare detailed reports on audit findings.", "Prepare audit reports.")
    changed = "\n".join(line for line in changed.splitlines() if "\t3\t" not in line) + "\n"
    second = await _import_reference(service, tmp_path, tasks=changed)
    assert second["aufgaben"]["geaendert"] == 1
    assert second["aufgaben"]["verschwunden"] == 1
    assert second["aufgaben"]["unveraendert"] == 2

    by_soc = await service.get_tasks("onet:13-2011.00", quellen=["onet"])
    tasks = by_soc["aufgaben"]["onet"][0]["aufgaben"]
    assert [t["typ"] for t in tasks] == ["Core", "Core"]  # supplemental task 3 vanished
    by_esco = await service.get_tasks(fx.ESCO_OCC_URI, quellen=["onet"])
    assert by_esco["aufgaben"]["onet"][0]["soc"] == "13-2011.00"
    by_text = await service.get_tasks("Buchhalter")
    assert by_text["aufgaben"]["berufenet"][0]["aufgaben"]
    assert by_text["zuordnung"]["kldb"][0]["code"] == "72213"


async def test_crosswalk_multi_hop(service: KnowledgeService, router: Router, tmp_path) -> None:
    _occupation_routes(router)
    await _import_reference(service, tmp_path)
    res = await service.crosswalk("72213", "kldb", "onet")
    assert res["pfad"] == ["kldb", "isco", "esco", "onet"]
    assert {r["code"] for r in res["ergebnisse"]} == {"13-2011.00"}
    back = await service.crosswalk("13-2011.00", "onet", "kldb")
    assert {r["code"] for r in back["ergebnisse"]} == {"72213"}
    bn = await service.crosswalk("58779", "berufenet", "isco")
    assert {r["code"] for r in bn["ergebnisse"]} == {"2411", "4311"}
    with pytest.raises(ValueError):
        await service.crosswalk("1", "kldb", "foo")


async def test_get_salary_filters_and_key_fallback(service: KnowledgeService, router: Router) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("X-API-Key") == "infosysbub-ega":
            return httpx.Response(403, text="forbidden")
        return httpx.Response(200, json=fx.ENTGELTE)

    router.add("GET", ENTGELT, handler)
    res = await service.get_salary("B 72213", niveau="fachkraft")
    assert res["kldb"] == "72213"
    assert len(res["werte"]) == 1 and res["werte"][0]["median_eur"] == 3954
    assert res["unterdrueckt"] == 0  # the second row belongs to another branch and is filtered out
    edges = service.graph_neighbors("kldb:72213", kantentyp="HAT_ENTGELT")["kanten"]
    assert edges and edges[0]["knoten_typ"] == "Entgelt"
    with pytest.raises(ValueError):
        await service.get_salary("abc")


async def test_role_context_combines_sources(service: KnowledgeService, router: Router) -> None:
    _occupation_routes(router)
    router.add("GET", ENTGELT, fx.ENTGELTE)
    router.add("GET", JOBS, fx.JOBSUCHE_V6)
    ctx = await service.get_role_context("Buchhalter", ort="Berlin")
    assert ctx["berufenet"]["name"] == "Buchhalter/in"
    assert "Konten abstimmen" in ctx["berufenet"]["aufgaben"]
    assert ctx["esco"]["essential_skills"][0] == "Buchführungsvorschriften anwenden"
    assert ctx["entgelt"]["region"] == "Berlin"
    assert ctx["markt"]["offene_stellen_ba"] == 2


# ------------------------------------------------------ signals & memory


async def test_automation_signals_link_and_volatile_fields(service: KnowledgeService, router: Router) -> None:
    state = {"resp": copy.deepcopy(fx.HN_SEARCH)}
    router.add("GET", r"hn\.algolia\.com/api/v1/search", lambda _r: state["resp"])
    with pytest.raises(ValueError):
        await service.find_automation_signals("x", aufgabe_id="aufgabe:onet:unbekannt")
    service.store.upsert_node("aufgabe:onet:13-2011.00#1", "Aufgabe", "Prepare detailed reports on audit findings.")
    res = await service.find_automation_signals("automated invoice processing", aufgabe_id="aufgabe:onet:13-2011.00#1")
    assert len(res["signale"]) == 2
    edges = service.graph_neighbors("aufgabe:onet:13-2011.00#1", kantentyp="AUTOMATISIERBAR_DURCH")["kanten"]
    assert {e["knoten"] for e in edges} == {"automatisierung:hn:4242", "automatisierung:hn:4300"}
    bumped = copy.deepcopy(fx.HN_SEARCH)
    bumped["hits"][1]["points"] = 999
    state["resp"] = bumped
    again = await service.find_automation_signals(
        "automated invoice processing", aktualisieren=True, aufgabe_id="aufgabe:onet:13-2011.00#1"
    )
    assert again["gedaechtnis"]["delta"]["geaendert"] == []  # points are volatile, not a content change
    free = await service.find_automation_signals("automated invoice processing", aufgabe_id="Rechnungen prüfen")
    assert free["verknuepft_mit"].startswith("aufgabe:extrahiert:")


async def test_record_extraction_versions_and_suggestions(service: KnowledgeService, router: Router, tmp_path) -> None:
    _occupation_routes(router)
    await _import_reference(service, tmp_path)
    res = service.record_extraction(
        "10000-1184867112-S",
        aufgaben=[{"text": "Prepare reports on audit findings", "anteil_wochenarbeitszeit": 0.2}],
        skills=["Steuerrecht"],
        automatisierungen=[
            {"aufgabe": "Prepare reports on audit findings", "signal": "https://example.com/auto", "bewertung": 0.7}
        ],
    )
    assert res["bezug"] == "stelle:ba:10000-1184867112-S"
    assert res["extraktion"]["ergebnis"] == "neu"
    suggestions = res["aufgaben"][0]["kanonische_vorschlaege"]
    assert suggestions and suggestions[0]["knoten"] == "aufgabe:onet:13-2011.00#1"
    assert res["automatisierungen"][0]["bewertung"] == 0.7
    edges = service.graph_neighbors("stelle:ba:10000-1184867112-S", kantentyp="STELLT_AN")["kanten"]
    assert edges[0]["eigenschaften"]["anteil_wochenarbeitszeit"] == 0.2
    again = service.record_extraction("10000-1184867112-S", aufgaben=[{"text": "Andere Aufgabe"}])
    assert again["extraktion"]["ergebnis"] == "geaendert" and again["extraktion"]["version"] == 2


async def test_remember_history_changes_and_search(service: KnowledgeService) -> None:
    r1 = service.remember("rollenprofil", "fibu-1", {"titel": "Finanzbuchhalter", "team": "FiBu"}, titel="FiBu")
    r2 = service.remember("rollenprofil", "fibu-1", {"titel": "Finanzbuchhalter", "team": "Accounting"})
    assert (r1["ergebnis"], r2["ergebnis"], r2["version"]) == ("neu", "geaendert", 2)
    hist = service.get_history("eigene", "rollenprofil", "fibu-1")
    assert hist["versionen"][1]["aenderungen"] == [{"feld": "team", "alt": "FiBu", "neu": "Accounting"}]
    changes = service.get_changes(seit="1h")
    assert changes["zusammenfassung"] == {"neu": 1, "geaendert": 1}
    assert service.search_knowledge("Accounting")["treffer"][0]["schluessel"] == "fibu-1"
    assert service.remember("x", "y", {"a": 1}, quelle="onet")["quelle"] == "eigene:onet"


async def test_offline_mode_serves_memory_only(service: KnowledgeService, router: Router) -> None:
    router.add("GET", JOBS, fx.JOBSUCHE_V6)
    await service.search_jobs(was="Buchhalter")
    service.settings.offline = True
    calls = len(router.calls)
    cached = await service.search_jobs(was="Buchhalter", aktualisieren=True)
    assert cached["anzahl"] == 2 and len(router.calls) == calls
    unknown = await service.search_jobs(was="Koch")
    assert unknown["anzahl"] == 0 and "Offline" in unknown["gedaechtnis"]["warnung"]


async def test_export_formats(service: KnowledgeService, router: Router, tmp_path) -> None:
    _occupation_routes(router)
    await service.get_skills(fx.ESCO_OCC_URI)
    await service.search_occupation("Buchhalter", quellen=["berufenet"])
    for fmt in ("json", "cypher", "graphml"):
        out = service.export_knowledge(fmt, str(tmp_path / f"graph.{fmt}"))
        assert out["knoten"] > 0
    data = json.loads((tmp_path / "graph.json").read_text(encoding="utf-8"))
    assert any(n["typ"] == "Skill" for n in data["knoten"])
    assert "MERGE (a)-[r:ERFORDERT]->(b)" in (tmp_path / "graph.cypher").read_text(encoding="utf-8")
    arch = service.export_knowledge("archivy", str(tmp_path / "archivy"))
    notes = sorted((tmp_path / "archivy" / "WorkMCP").glob("*.md"))
    assert arch["notizen"] == len(notes) >= 3
    text = notes[0].read_text(encoding="utf-8")
    assert text.startswith("---\ndate: ") and "\ntype: note\n" in text and "id: 9000" in text
    again = service.export_knowledge("archivy", str(tmp_path / "archivy"))
    assert again["notizen"] == arch["notizen"]
    assert sorted((tmp_path / "archivy" / "WorkMCP").glob("*.md")) == notes  # stable ids, no duplicates


async def test_check_sources_reports_reachability(service: KnowledgeService, router: Router) -> None:
    def down(request: httpx.Request) -> object:
        raise httpx.ConnectError("blockiert", request=request)

    router.add("GET", r"esco", down)
    router.add("GET", r"arbeitsagentur\.de", {"ok": True})
    res = await service.check_sources()
    by_name = {r["quelle"]: r for r in res["quellen"]}
    assert by_name["ESCO"]["erreichbar"] is False
    assert by_name["Arbeitsagentur Jobsuche"]["erreichbar"] is True
    assert by_name["Greenhouse"]["http_status"] == 404  # any HTTP answer means reachable
    assert by_name["Adzuna"]["erreichbar"] is None
    assert "ESCO" in res["nicht_erreichbar"]


async def test_commoncrawl_lookup_with_text(service: KnowledgeService, router: Router) -> None:
    router.add(
        "GET",
        r"index\.commoncrawl\.org/collinfo\.json",
        [{"id": "CC-MAIN-2026-30", "name": "August 2026"}, {"id": "CC-MAIN-2026-26", "name": "Juli"}],
    )
    router.add(
        "GET",
        r"index\.commoncrawl\.org/CC-MAIN-2026-30-index",
        '{"url": "https://example.com/karriere/1", "timestamp": "20260801", "status": "200", '
        '"filename": "crawl-data/x.warc.gz", "offset": "0", "length": "100"}\n',
    )
    record = (
        b"WARC/1.0\r\nWARC-Type: response\r\n\r\nHTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n"
        b"<h1>Buchhalter</h1><ul><li>Belege buchen</li></ul>"
    )
    router.add(
        "GET", r"data\.commoncrawl\.org/crawl-data/x\.warc\.gz", httpx.Response(206, content=gzip.compress(record))
    )
    res = await service.commoncrawl_lookup("example.com/karriere/*", text_abrufen=1)
    assert res["crawl"] == "CC-MAIN-2026-30"
    assert res["treffer"][0]["url"] == "https://example.com/karriere/1"
    assert "Belege buchen" in res["texte"][0]["text"]
    assert service.store.get_record("commoncrawl", "seite", "CC-MAIN-2026-30|https://example.com/karriere/1|20260801")
