from __future__ import annotations

import time

from workmcp.store import (
    EVENT_CHANGED,
    EVENT_GONE,
    EVENT_NEW,
    EVENT_REAPPEARED,
    KnowledgeStore,
    diff,
    fts_query,
)


def test_new_changed_unchanged_versions(store: KnowledgeStore) -> None:
    r1 = store.upsert_record("ba", "stelle", "R1", {"titel": "Buchhalter", "ort": "Berlin"}, title="Buchhalter")
    assert r1.status == EVENT_NEW and r1.version == 1

    r2 = store.upsert_record("ba", "stelle", "R1", {"ort": "Berlin", "titel": "Buchhalter"}, title="Buchhalter")
    assert r2.status == "unveraendert" and r2.version == 1

    r3 = store.upsert_record("ba", "stelle", "R1", {"titel": "Buchhalter (m/w/d)", "ort": "Berlin"})
    assert r3.status == EVENT_CHANGED and r3.version == 2
    assert r3.changes == [{"feld": "titel", "alt": "Buchhalter", "neu": "Buchhalter (m/w/d)"}]

    rec = store.get_record("ba", "stelle", "R1")
    assert rec is not None
    assert rec.version == 2 and rec.fetch_count == 3
    assert rec.data["titel"] == "Buchhalter (m/w/d)"
    assert rec.title == "Buchhalter"  # title kept when the update passes none

    history = store.history(rec.id)
    assert [h["version"] for h in history] == [1, 2]
    assert history[0]["gueltig_bis"] is not None and history[1]["gueltig_bis"] is None
    assert history[1]["aenderungen"][0]["feld"] == "titel"

    events = [c["ereignis"] for c in store.changes()]
    assert events == [EVENT_CHANGED, EVENT_NEW]


def test_hash_ignore_skips_volatile_fields(store: KnowledgeStore) -> None:
    store.upsert_record("hn", "signal", "1", {"text": "We automated invoices", "points": 5}, hash_ignore=["points"])
    res = store.upsert_record(
        "hn", "signal", "1", {"text": "We automated invoices", "points": 99}, hash_ignore=["points"]
    )
    assert res.status == "unveraendert"


def test_gone_and_reappeared(store: KnowledgeStore) -> None:
    store.upsert_record("ba", "stelle", "R9", {"titel": "Lagerist"})
    assert store.mark_gone("ba", "stelle", "R9") is True
    assert store.mark_gone("ba", "stelle", "R9") is False
    rec = store.get_record("ba", "stelle", "R9")
    assert rec is not None and rec.status == "verschwunden"
    res = store.upsert_record("ba", "stelle", "R9", {"titel": "Lagerist"})
    assert res.status == EVENT_REAPPEARED
    assert [c["ereignis"] for c in store.changes()][:2] == [EVENT_REAPPEARED, EVENT_GONE]


def test_get_records_keeps_order_and_skips_missing(store: KnowledgeStore) -> None:
    for k in ("a", "b", "c"):
        store.upsert_record("s", "k", k, {"v": k})
    recs = store.get_records("s", "k", ["c", "x", "a"])
    assert [r.key for r in recs] == ["c", "a"]


def test_find_records_by_prefix_and_json(store: KnowledgeStore) -> None:
    store.upsert_record("onet", "aufgabe", "15-1252.00#1", {"soc": "15-1252.00", "task_type": "Core"})
    store.upsert_record("onet", "aufgabe", "15-1252.00#2", {"soc": "15-1252.00", "task_type": "Supplemental"})
    store.upsert_record("onet", "aufgabe", "15-1253.00#3", {"soc": "15-1253.00", "task_type": "Core"})
    assert len(store.find_records(source="onet", kind="aufgabe", key_prefix="15-1252.00#")) == 2
    core = store.find_records(source="onet", json_equals=("task_type", "Core"))
    assert {r.key for r in core} == {"15-1252.00#1", "15-1253.00#3"}


def test_fulltext_search_with_umlauts(store: KnowledgeStore) -> None:
    store.upsert_record(
        "berufenet",
        "beruf",
        "1",
        {"name": "Bäcker/in"},
        title="Bäcker/in",
        text="Teig herstellen, Brot backen, Öfen bedienen",
    )
    store.upsert_record(
        "berufenet",
        "beruf",
        "2",
        {"name": "Buchhalter/in"},
        title="Buchhalter/in",
        text="Rechnungen prüfen, Konten abstimmen",
    )
    hits = store.search("Backer")
    assert hits and hits[0][0].key == "1"
    hits = store.search("Rechnung prüfen", mode="or")
    assert hits and hits[0][0].key == "2"
    # changed content is re-indexed
    store.upsert_record(
        "berufenet",
        "beruf",
        "2",
        {"name": "Buchhalter/in", "v": 2},
        title="Buchhalter/in",
        text="Jahresabschluss erstellen",
    )
    assert not store.search("Rechnungen")
    assert store.search("Jahresabschluss")


def test_fetch_runs_and_last_run(store: KnowledgeStore) -> None:
    params = {"was": "Koch", "wo": "Köln", "seite": 1}
    run = store.begin_run("ba", "jobsuche", params)
    results = [store.upsert_record("ba", "stelle", k, {"k": k}) for k in ("A", "B")]
    store.finish_run(run, results=results)
    last = store.last_run("jobsuche", {"wo": "Köln", "was": "Koch", "seite": 1, "ignored": None})
    assert last is not None and last.result_keys == ["A", "B"]
    assert last.age().total_seconds() < 60
    assert store.recent_runs()[0]["neu"] == 2


def test_graph_nodes_edges_merge(store: KnowledgeStore) -> None:
    store.upsert_node("beruf:kldb:43413", "Beruf", "Softwareentwicklung", {"ebene": 5})
    store.upsert_node("beruf:kldb:43413", "Beruf", None, {"niveau": "Spezialist"})
    node = store.get_node("beruf:kldb:43413")
    assert node is not None
    assert node["label"] == "Softwareentwicklung"
    assert node["eigenschaften"] == {"ebene": 5, "niveau": "Spezialist"}

    store.upsert_node("klass:isco:2512", "Klassifikation", "Software developers")
    store.upsert_edge("beruf:kldb:43413", "klass:isco:2512", "ENTSPRICHT", {"quelle": "BA"}, source="kldb_isco")
    store.upsert_edge("beruf:kldb:43413", "klass:isco:2512", "ENTSPRICHT", {"eindeutig": True})
    out = store.edges("beruf:kldb:43413")
    assert len(out) == 1
    assert out[0]["eigenschaften"] == {"quelle": "BA", "eindeutig": True}
    assert out[0]["knoten_label"] == "Software developers"
    back = store.edges("klass:isco:2512", direction="eingehend")
    assert back and back[0]["knoten"] == "beruf:kldb:43413"
    nodes, edges = store.iter_graph()
    assert len(nodes) == 2 and len(edges) == 1


def test_persistence_across_reopen(tmp_path) -> None:
    path = tmp_path / "k.db"
    s1 = KnowledgeStore(path)
    s1.upsert_record("esco", "beruf", "uri:1", {"titel": "Buchhalter"})
    s1.close()
    time.sleep(0.01)
    s2 = KnowledgeStore(path)
    res = s2.upsert_record("esco", "beruf", "uri:1", {"titel": "Buchhalter"})
    assert res.status == "unveraendert"
    assert s2.stats()["datensaetze"][0]["anzahl"] == 1
    s2.close()


def test_diff_nested_paths() -> None:
    old = {"a": {"b": 1, "c": [1, 2]}, "d": "x"}
    new = {"a": {"b": 2, "c": [1, 2]}, "e": "y"}
    fields = {c["feld"] for c in diff(old, new)}
    assert fields == {"a.b", "d", "e"}


def test_fts_query_is_safe() -> None:
    assert fts_query('Bäcker "OR" -- drop') == '"bäcker"* OR "or" OR "drop"*'
    assert fts_query("  ") is None


def test_fts_layout_migration(tmp_path) -> None:
    """Databases with the early FTS layout (record_id column) are rebuilt and stay searchable."""
    import sqlite3

    path = tmp_path / "alt.db"
    s1 = KnowledgeStore(path)
    s1.upsert_record("berufenet", "beruf", "1", {"name": "Bäcker/in"}, title="Bäcker/in")
    s1.close()
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE search_index")
    conn.execute(
        "CREATE VIRTUAL TABLE search_index USING fts5("
        "record_id UNINDEXED, source UNINDEXED, kind UNINDEXED, title, body)"
    )
    conn.commit()
    conn.close()
    s2 = KnowledgeStore(path)
    assert s2.search("Bäcker")[0][0].key == "1"
    s2.close()
