from __future__ import annotations

import gzip
import io

import pytest
from openpyxl import Workbook

from tests import fixtures as fx
from workmcp.sources import arbeitsagentur as ba
from workmcp.sources import commoncrawl as cc
from workmcp.sources import esco, onet, signals, tables
from workmcp.textutil import html_to_text, list_items, sections_by_heading

# --------------------------------------------------------------- Jobsuche


def test_search_results_supports_v6_and_v4() -> None:
    assert [ba.job_refnr(i) for i in ba.search_results(fx.JOBSUCHE_V6)] == ["10000-1184867112-S", "10001-1002716922-S"]
    assert [ba.job_refnr(i) for i in ba.search_results(fx.JOBSUCHE_V4)] == ["10000-1184867113-S"]
    assert ba.search_results({}) == []


def test_normalize_job_item_v6() -> None:
    job = ba.normalize_job_item(fx.JOBSUCHE_V6["ergebnisliste"][0])
    assert job["refnr"] == "10000-1184867112-S"
    assert job["titel"] == "Buchhalter (m/w/d)"
    assert job["arbeitgeber"] == "Muster GmbH"
    assert job["ort"] == "Berlin" and job["plz"] == "10115"
    assert job["veroeffentlicht"] == "2026-10-20"
    assert job["url"] == "https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-1184867112-S"


def test_normalize_job_item_v4() -> None:
    job = ba.normalize_job_item(fx.JOBSUCHE_V4["stellenangebote"][0])
    assert job["titel"] == "Elektriker (m/w/d)"
    assert job["beruf"] == "Elektroinstallateur/in"
    assert job["plz"] == "90537" and job["region"] == "Bayern"
    assert job["lat"] == 49.37
    assert job["geaendert_am"] == "2026-07-25T13:12:33.913"


def test_normalize_job_detail_old_and_new_formats() -> None:
    old = ba.normalize_job_detail(fx.JOBDETAIL_V4_OLD)
    assert old["haupt_dkz"] == "9907"
    assert old["branche"] == "Elektroinstallation"
    assert old["fertigkeiten"] == ["Elektroinstallation", "Wartung"]
    assert "- Installation" in old["beschreibung"]

    new = ba.normalize_job_detail(fx.JOBDETAIL_NEW)
    assert new["refnr"] == "10000-1184867112-S"
    assert new["arbeitgeber"] == "Muster GmbH"
    assert new["verguetung"] is None  # KEINE_ANGABEN
    assert new["befristung"] == "UNBEFRISTET"
    assert new["erstmals_veroeffentlicht"] == "2026-10-20"
    assert new["externe_url"] is None
    assert new["arbeitsorte"][0]["ort"] == "Berlin"


def test_encode_refnr_matches_documented_example() -> None:
    assert ba.encode_refnr("10001-1002716922-S") == "MTAwMDEtMTAwMjcxNjkyMi1T"


def test_build_search_params() -> None:
    params = ba.build_search_params(
        was="Koch",
        wo="Köln",
        umkreis=25,
        arbeitszeit=["vollzeit", "homeoffice"],
        befristung="unbefristet",
        zeitarbeit=False,
        size=500,
    )
    assert params == {
        "was": "Koch",
        "wo": "Köln",
        "umkreis": 25,
        "angebotsart": 1,
        "page": 1,
        "size": 100,
        "arbeitszeit": "vz;ho",
        "befristung": "2",
        "zeitarbeit": "false",
    }
    assert "umkreis" not in ba.build_search_params(was="Koch", umkreis=25)
    assert ba.build_search_params(angebotsart="ausbildung")["angebotsart"] == 4
    with pytest.raises(ValueError):
        ba.build_search_params(angebotsart="urlaub")


# ---------------------------------------------------------------- BERUFENET


def test_normalize_berufenet_list() -> None:
    items, total = ba.normalize_berufenet_list(fx.BERUFENET_LIST)
    assert total == 2
    assert items[0] == {
        "id": "58779",
        "name": "Buchhalter/in",
        "url": "https://web.arbeitsagentur.de/berufenet/beruf/58779",
    }


def test_normalize_berufenet_detail_extracts_kldb_tasks_fields() -> None:
    beruf = ba.normalize_berufenet_detail(fx.BERUFENET_DETAIL)
    assert beruf["id"] == "58779"
    assert beruf["kldb2010"] == "72213"
    assert "Belege kontieren und buchen" in beruf["aufgaben"]
    assert "Konten abstimmen" in beruf["aufgaben"]
    assert "Sie prüfen Rechnungen und überwachen Zahlungseingänge." in beruf["aufgaben"]
    assert all("Weiterbildung" not in a for a in beruf["aufgaben"])
    assert beruf["taetigkeitsfelder"] == ["Rechnungswesen", "Controlling"]


def test_find_kldb_variants() -> None:
    assert ba.find_kldb({"kldb2010": "B 91244-11300"}) == "91244"
    assert ba.find_kldb({"x": {"kldb": {"codenr": "B 43413"}}}) == "43413"
    assert ba.find_kldb({"name": "ohne"}) is None


def test_normalize_entgelt() -> None:
    row = ba.normalize_entgelt(fx.ENTGELTE[0])
    assert row["median_eur"] == 3954 and row["q25_eur"] == 3312 and row["niveau"] == "Fachkraft"
    assert row["beitragsbemessungsgrenze_eur"] == 8050


def test_resolve_code_names_and_numbers() -> None:
    assert ba.resolve_code("Berlin", ba.ENTGELT_REGIONEN, "Region") == 14
    assert ba.resolve_code("nrw", ba.ENTGELT_REGIONEN, "Region") == 8
    assert ba.resolve_code("7", ba.ENTGELT_REGIONEN, "Region") == 7
    assert ba.resolve_code("Experte", ba.ENTGELT_NIVEAUS, "Niveau") == 4
    assert ba.resolve_code(None, ba.ENTGELT_NIVEAUS, "Niveau") is None


# ---------------------------------------------------------------------- ESCO


def test_esco_search_and_occupation() -> None:
    results, total = esco.normalize_search(fx.ESCO_SEARCH, "de")
    assert total == 1 and results[0]["uri"] == fx.ESCO_OCC_URI
    occ = esco.normalize_occupation(fx.ESCO_OCCUPATION, "de")
    assert occ["titel"] == "Buchhalter/Buchhalterin"
    assert occ["isco_code"] == "2411"
    assert occ["beschreibung"] == "Buchhalter analysieren Finanzunterlagen."
    assert [s["uri"] for s in occ["essential_skills"]] == [fx.ESCO_SKILL_1, fx.ESCO_SKILL_2]
    assert occ["optional_skills"][0]["titel"] == "Steuerrecht"
    assert occ["alternative_titel"] == ["Bilanzbuchhalter", "Finanzbuchhalterin"]


def test_esco_isco_group() -> None:
    group = esco.normalize_isco_group(fx.ESCO_ISCO_GROUP, "de")
    assert group["code"] == "2411"
    assert len(group["berufe"]) == 2


def test_esco_isco_from_links_only() -> None:
    doc = {"_links": {"broaderIscoGroup": {"uri": "http://data.europa.eu/esco/isco/C2512"}}}
    assert esco.isco_code_of(doc) == "2512"


# ---------------------------------------------------------------------- O*NET


def test_onet_parse_tasks_and_occupations() -> None:
    tasks = [onet.task_record(r) for r in onet.parse_tsv(fx.ONET_TASKS)]
    assert tasks[0] is not None
    key, data, _title = tasks[0]
    assert key == "13-2011.00#1"
    assert data["task_type"] == "Core" and data["incumbents_responding"] == 110
    occs = [onet.occupation_record(r) for r in onet.parse_tsv(fx.ONET_OCCUPATIONS)]
    assert occs[1] is not None and occs[1][0] == "15-1252.00"


def test_onet_detect_version() -> None:
    html = '<a href="/dl_files/database/db_30_3_text.zip">x</a> <a href="/dl_files/database/db_31_0_excel.zip">y</a>'
    assert onet.detect_version_from_html(html) == "31_0"
    assert onet.detect_version_from_html("nothing") is None


def test_onet_read_local_zip(tmp_path) -> None:
    import zipfile

    archive = tmp_path / "db.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("db_31_0_text/Task Statements.txt", fx.ONET_TASKS)
    files = onet.read_local(archive, ["Task Statements.txt", "Occupation Data.txt"])
    assert list(files) == ["Task Statements.txt"]


# --------------------------------------------------------------------- tables


def _xlsx(rows: list[list[object]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_kldb_xlsx_with_title_rows() -> None:
    content = _xlsx(
        [
            ["Klassifikation der Berufe 2010 – überarbeitete Fassung 2020"],
            [],
            ["Schlüssel KldB 2010, V. 2020", "Ebene", "Titel"],
            ["4", 1, "Naturwissenschaft, Geografie und Informatik"],
            ["43", 2, "Informatik-, Informations- und Kommunikationstechnologieberufe"],
            ["434", 3, "Softwareentwicklung und Programmierung"],
            ["4341", 4, "Berufe in der Softwareentwicklung"],
            ["43413", 5, "Berufe in der Softwareentwicklung - komplexe Spezialistentätigkeiten"],
            [1104, 5, "Führung Militär (Zahl ohne führende Null)"],
        ]
    )
    rows = tables.read_table(content, "kldb.xlsx")
    parsed = {r["code"]: r for r in tables.parse_kldb(rows)}
    assert parsed["434"]["ebene_name"] == "Berufsgruppe"
    assert parsed["43413"]["anforderungsniveau"] == "Spezialist"
    assert "01104" in parsed  # zero-padded via the level column


def test_parse_kldb_isco_csv() -> None:
    csv_text = (
        "KldB 2010 (5-Steller);Bezeichnung KldB 2010;ISCO-08 (4-Steller);Bezeichnung ISCO-08;"
        "Umsteigeschlüssel eindeutig\n"
        "43413;Softwareentwicklung - Spezialist;2512;Software developers;1\n"
        "72213;Rechnungswesen - Fachkraft;3313;Accounting associate professionals;0\n"
        "72213;Rechnungswesen - Fachkraft;4311;Accounting and bookkeeping clerks;0\n"
    )
    rows = tables.read_table(csv_text.encode("utf-8"), "umsteiger.csv")
    parsed = tables.parse_kldb_isco(rows)
    assert {(p["kldb"], p["isco"]) for p in parsed} == {("43413", "2512"), ("72213", "3313"), ("72213", "4311")}
    assert parsed[0]["kldb_titel"] == "Softwareentwicklung - Spezialist"
    assert parsed[0]["hinweis"] == "1"


def test_parse_esco_onet_by_value_shape() -> None:
    rows = [
        ["ESCO URI", "ESCO Title", "O*NET Id", "O*NET Title", "Type of Match"],
        [fx.ESCO_OCC_URI, "accountant", "13-2011.00", "Accountants and Auditors", "exactMatch"],
        [
            "http://data.europa.eu/esco/occupation/ccc",
            "software developer",
            "15-1252.00",
            "Software Developers",
            "closeMatch",
        ],
        ["http://data.europa.eu/esco/occupation/ddd", "x", "15-1252.00", "Software Developers", "broadMatch"],
        ["not a uri", "x", "nope", "", ""],
    ]
    parsed = tables.parse_esco_onet(rows)
    assert len(parsed) == 3
    assert parsed[0] == {
        "esco_uri": fx.ESCO_OCC_URI,
        "onet_soc": "13-2011.00",
        "esco_titel": "accountant",
        "onet_titel": "Accountants and Auditors",
        "art": "exactMatch",
    }


def test_read_table_rejects_old_xls() -> None:
    with pytest.raises(ValueError):
        tables.read_table(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest", "alt.xls")


# -------------------------------------------------------------- HN, Arbeitnow


def test_hn_normalize() -> None:
    hit = signals.normalize_hn_hit(fx.HN_SEARCH["hits"][0])
    assert hit["typ"] == "comment"
    assert hit["text"] == "We automated our invoice processing with an LLM pipeline."
    assert hit["hn_url"] == "https://news.ycombinator.com/item?id=4242"


def test_arbeitnow_normalize_and_filter() -> None:
    job = fx.ARBEITNOW_PAGE["data"][0]
    norm = signals.normalize_arbeitnow_job(job)
    assert norm["arbeitgeber"] == "Startup GmbH" and norm["erstellt"].startswith("2025")
    assert signals.arbeitnow_matches(job, "python", "berlin")
    assert signals.arbeitnow_matches(job, "python", "remote")
    assert not signals.arbeitnow_matches(job, "java", None)
    assert not signals.arbeitnow_matches(fx.ARBEITNOW_PAGE["data"][1], None, "remote")


# --------------------------------------------------------------- Common Crawl


def test_commoncrawl_parse_cdx_and_warc() -> None:
    lines = '{"url": "https://example.com/jobs/1", "filename": "f.warc.gz", "offset": "10", "length": "20"}\nbad\n'
    assert cc.parse_cdx_lines(lines)[0]["filename"] == "f.warc.gz"
    record = (
        b"WARC/1.0\r\nWARC-Type: response\r\nWARC-Target-URI: https://example.com/jobs/1\r\n\r\n"
        b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        b"<html><body><h1>Buchhalter (m/w/d)</h1><ul><li>Belege buchen</li></ul></body></html>"
    )
    parsed = cc.parse_warc_record(gzip.compress(record))
    assert parsed["status"] == 200
    assert parsed["warc"]["warc-target-uri"] == "https://example.com/jobs/1"
    assert "Belege buchen" in parsed["html"]


# ------------------------------------------------------------------ textutil


def test_textutil_helpers() -> None:
    markup = "<h2>Aufgaben</h2><ul><li>A</li><li>B &amp; C</li></ul><h2>Zugang</h2><p>Studium</p>"
    assert list_items(markup) == ["A", "B & C"]
    assert html_to_text(markup) == "Aufgaben\n- A\n- B & C\nZugang\nStudium"
    assert sections_by_heading(markup, ["aufgaben"]) == [{"ueberschrift": "Aufgaben", "punkte": ["A", "B & C"]}]
    assert list_items("- eins\n• zwei\n\n") == ["eins", "zwei"]
