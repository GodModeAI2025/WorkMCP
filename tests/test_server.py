from __future__ import annotations

from mcp import Client

from tests import fixtures as fx
from tests.conftest import Router
from workmcp.server import create_server
from workmcp.service import KnowledgeService

EXPECTED_TOOLS = {
    "search_jobs", "get_job_details", "search_arbeitnow", "get_ats_jobs", "adzuna_salary", "search_occupation",
    "get_occupation", "get_tasks", "get_skills", "crosswalk", "get_salary", "get_role_context",
    "find_automation_signals", "commoncrawl_lookup", "import_reference_data", "record_extraction", "remember",
    "search_knowledge", "get_changes", "get_history", "knowledge_stats", "graph_neighbors", "export_knowledge",
    "check_sources",
}  # fmt: skip


async def test_tools_are_listed_with_schemas(service: KnowledgeService) -> None:
    async with Client(create_server(service)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == EXPECTED_TOOLS
    schema = tools["search_jobs"].input_schema
    assert schema["properties"]["was"]["description"].startswith("Jobtitel")
    ats = tools["get_ats_jobs"].input_schema["properties"]["ats"]
    assert "personio" in str(ats)
    assert tools["knowledge_stats"].annotations.read_only_hint is True


async def test_call_through_mcp_remembers_and_reports_delta(service: KnowledgeService, router: Router) -> None:
    router.add("GET", r"jobsuche-service/pc/v6/jobs", fx.JOBSUCHE_V6)
    async with Client(create_server(service)) as client:
        first = await client.call_tool("search_jobs", {"was": "Buchhalter", "wo": "Berlin"})
        assert first.is_error is False
        assert first.structured_content["anzahl"] == 2
        assert first.structured_content["gedaechtnis"]["delta"]["erstabruf"] is True
        second = await client.call_tool("search_jobs", {"was": "Buchhalter", "wo": "Berlin"})
        assert second.structured_content["gedaechtnis"]["aus_speicher"] is True
        stats = await client.call_tool("knowledge_stats", {})
        rows = {(r["quelle"], r["art"]): r["anzahl"] for r in stats.structured_content["datensaetze"]}
        assert rows[("ba_jobsuche", "stelle")] == 2


async def test_anticipated_errors_reach_the_model(service: KnowledgeService) -> None:
    async with Client(create_server(service)) as client:
        res = await client.call_tool("search_jobs", {})
        assert res.is_error is True
        assert "mindestens" in res.content[0].text
        res = await client.call_tool("get_salary", {"kldb": "kein code"})
        assert res.is_error is True and "KldB" in res.content[0].text
        res = await client.call_tool("import_reference_data", {"datensatz": "kldb"})
        assert res.is_error is True and "quelle" in res.content[0].text


async def test_record_extraction_with_nested_models(service: KnowledgeService) -> None:
    async with Client(create_server(service)) as client:
        res = await client.call_tool(
            "record_extraction",
            {
                "bezug": "berufenet:58779",
                "aufgaben": [{"text": "Belege kontieren", "anteil_wochenarbeitszeit": 0.3}],
                "skills": ["DATEV"],
                "automatisierungen": [
                    {"aufgabe": "Belege kontieren", "signal": "https://example.com", "bewertung": 0.8}
                ],
            },
        )
        assert res.is_error is False
        data = res.structured_content
        assert data["aufgaben"][0]["aufgabe"] == "Belege kontieren"
        assert data["automatisierungen"][0]["bewertung"] == 0.8
        neighbors = await client.call_tool("graph_neighbors", {"knoten": "berufenet:58779"})
        types = {e["typ"] for e in neighbors.structured_content["kanten"]}
        assert {"TEIL_VON", "ERFORDERT"} <= types


async def test_prompt_is_available(service: KnowledgeService) -> None:
    async with Client(create_server(service)) as client:
        prompts = await client.list_prompts()
        assert [p.name for p in prompts.prompts] == ["rollen_analyse"]
        prompt = await client.get_prompt("rollen_analyse", {"rolle": "Buchhalter", "ort": "Köln"})
        text = prompt.messages[0].content.text
        assert "get_role_context" in text and "Köln" in text
