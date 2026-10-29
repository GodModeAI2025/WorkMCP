"""Persistent knowledge store.

Every record fetched from a source is remembered in SQLite.  Re-fetching the same record
(same ``source``/``kind``/``key``) is detected via a content hash:

* new record      -> version 1, changelog event ``neu``
* changed content -> new version, previous version kept in ``record_versions``,
                     changelog event ``geaendert`` with a field-level diff
* same content    -> only ``last_seen``/``fetch_count`` are updated
* vanished record -> status ``verschwunden`` (e.g. a job ad that returns 404), never deleted

On top of the records the store keeps a small property graph (``nodes``/``edges``) and a
full-text index used for offline search and task matching.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

EVENT_NEW = "neu"
EVENT_CHANGED = "geaendert"
EVENT_GONE = "verschwunden"
EVENT_REAPPEARED = "wieder_da"

STATUS_ACTIVE = "aktiv"
STATUS_GONE = "verschwunden"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    title TEXT,
    data TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'aktiv',
    origin TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    last_changed TEXT NOT NULL,
    fetch_count INTEGER NOT NULL DEFAULT 1,
    UNIQUE (source, kind, key)
);
CREATE INDEX IF NOT EXISTS idx_records_kind ON records (kind, source);
CREATE INDEX IF NOT EXISTS idx_records_changed ON records (last_changed);

CREATE TABLE IF NOT EXISTS record_versions (
    record_id INTEGER NOT NULL REFERENCES records (id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    data TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    PRIMARY KEY (record_id, version)
);

CREATE TABLE IF NOT EXISTS changelog (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    record_id INTEGER NOT NULL REFERENCES records (id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    title TEXT,
    event TEXT NOT NULL,
    version INTEGER,
    changes TEXT,
    run_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_changelog_ts ON changelog (ts);
CREATE INDEX IF NOT EXISTS idx_changelog_record ON changelog (record_id);

CREATE TABLE IF NOT EXISTS fetch_runs (
    id INTEGER PRIMARY KEY,
    started TEXT NOT NULL,
    finished TEXT,
    source TEXT NOT NULL,
    operation TEXT NOT NULL,
    params TEXT NOT NULL,
    params_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'laeuft',
    error TEXT,
    n_total INTEGER DEFAULT 0,
    n_new INTEGER DEFAULT 0,
    n_changed INTEGER DEFAULT 0,
    n_unchanged INTEGER DEFAULT 0,
    result_keys TEXT,
    meta TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_lookup ON fetch_runs (operation, params_hash, status, started);

CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    label TEXT,
    props TEXT NOT NULL DEFAULT '{}',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes (type);

CREATE TABLE IF NOT EXISTS edges (
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    type TEXT NOT NULL,
    props TEXT NOT NULL DEFAULT '{}',
    source TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (src, dst, type)
);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges (dst, type);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges (type);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    record_id UNINDEXED,
    source UNINDEXED,
    kind UNINDEXED,
    title,
    body,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""

_TOKEN_RE = re.compile(r"[\w][\w\-./]*", re.UNICODE)


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _strip_keys(data: Any, ignore: frozenset[str]) -> Any:
    if not ignore:
        return data
    if isinstance(data, dict):
        return {k: _strip_keys(v, ignore) for k, v in data.items() if k not in ignore}
    if isinstance(data, list):
        return [_strip_keys(v, ignore) for v in data]
    return data


def content_hash(data: Any, ignore: Iterable[str] = ()) -> str:
    stripped = _strip_keys(data, frozenset(ignore))
    return hashlib.sha256(canonical_json(stripped).encode("utf-8")).hexdigest()


def params_hash(params: dict[str, Any]) -> str:
    cleaned = {k: v for k, v in params.items() if v is not None}
    return hashlib.sha256(canonical_json(cleaned).encode("utf-8")).hexdigest()[:32]


def _short(value: Any, limit: int = 160) -> Any:
    if isinstance(value, (dict, list)):
        text = canonical_json(value)
        return text if len(text) <= limit else text[: limit - 1] + "…"
    if isinstance(value, str) and len(value) > limit:
        return value[: limit - 1] + "…"
    return value


def diff(old: Any, new: Any, ignore: Iterable[str] = (), max_depth: int = 4) -> list[dict[str, Any]]:
    """Field-level diff between two JSON documents (dotted paths, lists compared as a whole)."""
    ignore_set = frozenset(ignore)
    changes: list[dict[str, Any]] = []

    def walk(a: Any, b: Any, path: str, depth: int) -> None:
        if isinstance(a, dict) and isinstance(b, dict) and depth < max_depth:
            for k in sorted(set(a) | set(b)):
                if k in ignore_set:
                    continue
                p = f"{path}.{k}" if path else str(k)
                if k not in a:
                    changes.append({"feld": p, "alt": None, "neu": _short(b[k])})
                elif k not in b:
                    changes.append({"feld": p, "alt": _short(a[k]), "neu": None})
                else:
                    walk(a[k], b[k], p, depth + 1)
            return
        if canonical_json(_strip_keys(a, ignore_set)) != canonical_json(_strip_keys(b, ignore_set)):
            changes.append({"feld": path or "$", "alt": _short(a), "neu": _short(b)})

    walk(old, new, "", 0)
    return changes


def fts_query(text: str, mode: str = "or", prefix: bool = True) -> str | None:
    """Turn free text into a safe FTS5 MATCH expression."""
    tokens = [t.strip("-./") for t in _TOKEN_RE.findall(text or "")]
    tokens = [t for t in tokens if len(t) >= 2]
    if not tokens:
        return None
    parts = []
    for tok in dict.fromkeys(tok.lower() for tok in tokens):
        quoted = '"' + tok.replace('"', '""') + '"'
        parts.append(quoted + "*" if prefix and len(tok) >= 4 else quoted)
    joiner = " AND " if mode == "and" else " OR "
    return joiner.join(parts)


def _text_from(data: Any, limit: int = 6000) -> str:
    out: list[str] = []
    size = 0

    def walk(v: Any) -> None:
        nonlocal size
        if size >= limit:
            return
        if isinstance(v, str):
            out.append(v)
            size += len(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(data)
    return " ".join(out)[:limit]


@dataclass
class UpsertResult:
    record_id: int
    key: str
    status: str  # neu | geaendert | unveraendert | wieder_da
    version: int
    changes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Record:
    id: int
    source: str
    kind: str
    key: str
    title: str | None
    data: Any
    version: int
    status: str
    origin: str | None
    first_seen: str
    last_seen: str
    last_changed: str
    fetch_count: int

    def meta(self) -> dict[str, Any]:
        return {
            "quelle": self.source,
            "art": self.kind,
            "schluessel": self.key,
            "version": self.version,
            "status": self.status,
            "zuerst_gesehen": self.first_seen,
            "zuletzt_gesehen": self.last_seen,
            "zuletzt_geaendert": self.last_changed,
            "abrufe": self.fetch_count,
        }


@dataclass
class FetchRun:
    id: int
    started: str
    finished: str | None
    source: str
    operation: str
    params: dict[str, Any]
    status: str
    error: str | None
    result_keys: list[str]
    meta: dict[str, Any]

    def age(self) -> timedelta:
        return datetime.now(timezone.utc) - parse_ts(self.finished or self.started)


class KnowledgeStore:
    """SQLite-backed memory of everything the server has fetched."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
            self.path = str(Path(self.path).expanduser())
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.executescript(_SCHEMA)
        self.fts_enabled = self._init_fts()
        self._conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
        )

    def _init_fts(self) -> bool:
        try:
            self._conn.executescript(_FTS_SCHEMA)
            return True
        except sqlite3.OperationalError:
            return False

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._conn.in_transaction:
                yield self._conn
                return
            self._conn.execute("BEGIN")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    # ------------------------------------------------------------------ records

    def upsert_record(
        self,
        source: str,
        kind: str,
        key: str,
        data: Any,
        *,
        title: str | None = None,
        text: str | None = None,
        origin: str | None = None,
        run_id: int | None = None,
        hash_ignore: Iterable[str] = (),
        now: str | None = None,
    ) -> UpsertResult:
        """Insert or update a record, versioning content changes."""
        ts = now or utcnow()
        ignore = tuple(hash_ignore)
        digest = content_hash(data, ignore)
        payload = canonical_json(data)
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT id, content_hash, version, status, data FROM records WHERE source=? AND kind=? AND key=?",
                (source, kind, key),
            ).fetchone()
            if row is None:
                cur = conn.execute(
                    "INSERT INTO records (source, kind, key, title, data, content_hash, version, status, origin,"
                    " first_seen, last_seen, last_changed, fetch_count) VALUES (?,?,?,?,?,?,1,?,?,?,?,?,1)",
                    (source, kind, key, title, payload, digest, STATUS_ACTIVE, origin, ts, ts, ts),
                )
                record_id = int(cur.lastrowid or 0)
                conn.execute(
                    "INSERT INTO record_versions (record_id, version, data, content_hash, valid_from)"
                    " VALUES (?,?,?,?,?)",
                    (record_id, 1, payload, digest, ts),
                )
                self._log(conn, ts, record_id, source, kind, key, title, EVENT_NEW, 1, None, run_id)
                self._index(conn, record_id, source, kind, title, text if text is not None else _text_from(data))
                return UpsertResult(record_id, key, EVENT_NEW, 1)

            record_id = int(row["id"])
            was_gone = row["status"] == STATUS_GONE
            if row["content_hash"] == digest:
                conn.execute(
                    "UPDATE records SET last_seen=?, fetch_count=fetch_count+1, status=?, origin=COALESCE(?, origin)"
                    " WHERE id=?",
                    (ts, STATUS_ACTIVE, origin, record_id),
                )
                if was_gone:
                    self._log(
                        conn, ts, record_id, source, kind, key, title, EVENT_REAPPEARED, row["version"], None, run_id
                    )
                    return UpsertResult(record_id, key, EVENT_REAPPEARED, int(row["version"]))
                return UpsertResult(record_id, key, "unveraendert", int(row["version"]))

            version = int(row["version"]) + 1
            changes = diff(json.loads(row["data"]), data, ignore)
            conn.execute(
                "UPDATE record_versions SET valid_to=? WHERE record_id=? AND valid_to IS NULL", (ts, record_id)
            )
            conn.execute(
                "INSERT INTO record_versions (record_id, version, data, content_hash, valid_from) VALUES (?,?,?,?,?)",
                (record_id, version, payload, digest, ts),
            )
            conn.execute(
                "UPDATE records SET data=?, content_hash=?, version=?, title=COALESCE(?, title), status=?,"
                " origin=COALESCE(?, origin), last_seen=?, last_changed=?, fetch_count=fetch_count+1 WHERE id=?",
                (payload, digest, version, title, STATUS_ACTIVE, origin, ts, ts, record_id),
            )
            self._log(conn, ts, record_id, source, kind, key, title, EVENT_CHANGED, version, changes, run_id)
            self._index(conn, record_id, source, kind, title, text if text is not None else _text_from(data))
            return UpsertResult(record_id, key, EVENT_CHANGED, version, changes)

    def mark_gone(self, source: str, kind: str, key: str, *, run_id: int | None = None) -> bool:
        ts = utcnow()
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT id, version, status, title FROM records WHERE source=? AND kind=? AND key=?",
                (source, kind, key),
            ).fetchone()
            if row is None or row["status"] == STATUS_GONE:
                return False
            conn.execute("UPDATE records SET status=?, last_changed=? WHERE id=?", (STATUS_GONE, ts, row["id"]))
            self._log(
                conn, ts, int(row["id"]), source, kind, key, row["title"], EVENT_GONE, row["version"], None, run_id
            )
            return True

    def _log(
        self,
        conn: sqlite3.Connection,
        ts: str,
        record_id: int,
        source: str,
        kind: str,
        key: str,
        title: str | None,
        event: str,
        version: int | None,
        changes: list[dict[str, Any]] | None,
        run_id: int | None,
    ) -> None:
        conn.execute(
            "INSERT INTO changelog (ts, record_id, source, kind, key, title, event, version, changes, run_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                ts,
                record_id,
                source,
                kind,
                key,
                title,
                event,
                version,
                canonical_json(changes) if changes else None,
                run_id,
            ),
        )

    def _index(
        self, conn: sqlite3.Connection, record_id: int, source: str, kind: str, title: str | None, body: str
    ) -> None:
        if not self.fts_enabled:
            return
        conn.execute("DELETE FROM search_index WHERE record_id = ?", (record_id,))
        conn.execute(
            "INSERT INTO search_index (record_id, source, kind, title, body) VALUES (?,?,?,?,?)",
            (record_id, source, kind, title or "", body or ""),
        )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> Record:
        return Record(
            id=int(row["id"]),
            source=row["source"],
            kind=row["kind"],
            key=row["key"],
            title=row["title"],
            data=json.loads(row["data"]),
            version=int(row["version"]),
            status=row["status"],
            origin=row["origin"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            last_changed=row["last_changed"],
            fetch_count=int(row["fetch_count"]),
        )

    def get_record(self, source: str, kind: str, key: str) -> Record | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM records WHERE source=? AND kind=? AND key=?", (source, kind, key)
            ).fetchone()
        return self._row_to_record(row) if row else None

    def get_record_by_id(self, record_id: int) -> Record | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def get_records(self, source: str, kind: str, keys: Sequence[str]) -> list[Record]:
        """Records for ``keys`` in the given order (missing keys are skipped)."""
        if not keys:
            return []
        found: dict[str, Record] = {}
        with self._lock:
            for i in range(0, len(keys), 500):
                chunk = list(keys[i : i + 500])
                placeholders = ",".join("?" * len(chunk))
                rows = self._conn.execute(
                    f"SELECT * FROM records WHERE source=? AND kind=? AND key IN ({placeholders})",
                    (source, kind, *chunk),
                ).fetchall()
                for row in rows:
                    found[row["key"]] = self._row_to_record(row)
        return [found[k] for k in keys if k in found]

    def find_records(
        self,
        *,
        source: str | None = None,
        kind: str | None = None,
        key_prefix: str | None = None,
        title_like: str | None = None,
        json_equals: tuple[str, Any] | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Record]:
        clauses, args = [], []
        if source:
            clauses.append("source = ?")
            args.append(source)
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        if key_prefix:
            clauses.append("key LIKE ? ESCAPE '\\'")
            args.append(key_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        if title_like:
            clauses.append("title LIKE ?")
            args.append(f"%{title_like}%")
        if json_equals:
            clauses.append("json_extract(data, ?) = ?")
            args.extend([f"$.{json_equals[0]}", json_equals[1]])
        if status:
            clauses.append("status = ?")
            args.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM records {where} ORDER BY id LIMIT ? OFFSET ?", (*args, limit, offset)
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def keys(self, source: str, kind: str, *, status: str | None = None, key_prefix: str | None = None) -> list[str]:
        """Keys only (cheap) – used to detect records that vanished from a re-imported dataset."""
        clauses, args = ["source = ?", "kind = ?"], [source, kind]
        if status:
            clauses.append("status = ?")
            args.append(status)
        if key_prefix:
            clauses.append("key LIKE ? ESCAPE '\\'")
            args.append(key_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        with self._lock:
            rows = self._conn.execute(f"SELECT key FROM records WHERE {' AND '.join(clauses)} ORDER BY id", args)
            return [r[0] for r in rows.fetchall()]

    def count_records(self, source: str | None = None, kind: str | None = None) -> int:
        clauses, args = [], []
        if source:
            clauses.append("source = ?")
            args.append(source)
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            return int(self._conn.execute(f"SELECT COUNT(*) FROM records {where}", args).fetchone()[0])

    def history(self, record_id: int) -> list[dict[str, Any]]:
        with self._lock:
            versions = self._conn.execute(
                "SELECT version, data, valid_from, valid_to FROM record_versions WHERE record_id=? ORDER BY version",
                (record_id,),
            ).fetchall()
            events = self._conn.execute(
                "SELECT ts, event, version, changes FROM changelog WHERE record_id=? ORDER BY id", (record_id,)
            ).fetchall()
        changes_by_version: dict[int, list[Any]] = {}
        other_events: list[dict[str, Any]] = []
        for ev in events:
            if ev["event"] == EVENT_CHANGED and ev["version"] is not None:
                changes_by_version[int(ev["version"])] = json.loads(ev["changes"]) if ev["changes"] else []
            elif ev["event"] in (EVENT_GONE, EVENT_REAPPEARED):
                other_events.append({"zeit": ev["ts"], "ereignis": ev["event"], "version": ev["version"]})
        out = []
        for v in versions:
            entry: dict[str, Any] = {
                "version": int(v["version"]),
                "gueltig_ab": v["valid_from"],
                "gueltig_bis": v["valid_to"],
                "daten": json.loads(v["data"]),
            }
            if int(v["version"]) in changes_by_version:
                entry["aenderungen"] = changes_by_version[int(v["version"])]
            out.append(entry)
        if other_events:
            out.append({"statuswechsel": other_events})
        return out

    def changes(
        self,
        *,
        since: str | None = None,
        source: str | None = None,
        kind: str | None = None,
        event: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses, args = [], []
        if since:
            clauses.append("ts >= ?")
            args.append(since)
        if source:
            clauses.append("source = ?")
            args.append(source)
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        if event:
            clauses.append("event = ?")
            args.append(event)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM changelog {where} ORDER BY id DESC LIMIT ?", (*args, limit)
            ).fetchall()
        return [
            {
                "zeit": r["ts"],
                "ereignis": r["event"],
                "quelle": r["source"],
                "art": r["kind"],
                "schluessel": r["key"],
                "titel": r["title"],
                "version": r["version"],
                "aenderungen": json.loads(r["changes"]) if r["changes"] else None,
            }
            for r in rows
        ]

    def change_counts(self, since: str | None = None) -> dict[str, int]:
        args: list[Any] = []
        where = ""
        if since:
            where = "WHERE ts >= ?"
            args.append(since)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT event, COUNT(*) AS n FROM changelog {where} GROUP BY event", args
            ).fetchall()
        return {r["event"]: int(r["n"]) for r in rows}

    # --------------------------------------------------------------- full text

    def search(
        self,
        query: str,
        *,
        source: str | None = None,
        kind: str | None = None,
        limit: int = 20,
        mode: str = "and",
    ) -> list[tuple[Record, float]]:
        """Full-text search over all remembered records (falls back to LIKE without FTS5)."""
        if self.fts_enabled:
            expr = fts_query(query, mode=mode)
            if not expr:
                return []
            clauses, args = ["search_index MATCH ?"], [expr]
            if source:
                clauses.append("source = ?")
                args.append(source)
            if kind:
                clauses.append("kind = ?")
                args.append(kind)
            sql = (
                "SELECT record_id, bm25(search_index, 0.0, 0.0, 0.0, 4.0, 1.0) AS score FROM search_index WHERE "
                + " AND ".join(clauses)
                + " ORDER BY score LIMIT ?"
            )
            with self._lock:
                try:
                    rows = self._conn.execute(sql, (*args, limit)).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            results = []
            for r in rows:
                rec = self.get_record_by_id(int(r["record_id"]))
                if rec:
                    results.append((rec, float(-r["score"])))
            return results
        recs = self.find_records(source=source, kind=kind, title_like=query, limit=limit)
        return [(r, 0.0) for r in recs]

    # ------------------------------------------------------------- fetch runs

    def begin_run(self, source: str, operation: str, params: dict[str, Any]) -> int:
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO fetch_runs (started, source, operation, params, params_hash) VALUES (?,?,?,?,?)",
                (utcnow(), source, operation, canonical_json(params), params_hash(params)),
            )
            return int(cur.lastrowid or 0)

    def finish_run(
        self,
        run_id: int,
        *,
        status: str = "ok",
        error: str | None = None,
        results: Sequence[UpsertResult] = (),
        result_keys: Sequence[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        counts = {"neu": 0, "geaendert": 0, "unveraendert": 0}
        for r in results:
            if r.status == EVENT_NEW:
                counts["neu"] += 1
            elif r.status == EVENT_CHANGED:
                counts["geaendert"] += 1
            else:
                counts["unveraendert"] += 1
        keys = list(result_keys) if result_keys is not None else [r.key for r in results]
        with self.transaction() as conn:
            conn.execute(
                "UPDATE fetch_runs SET finished=?, status=?, error=?, n_total=?, n_new=?, n_changed=?,"
                " n_unchanged=?, result_keys=?, meta=? WHERE id=?",
                (
                    utcnow(),
                    status,
                    error,
                    len(keys),
                    counts["neu"],
                    counts["geaendert"],
                    counts["unveraendert"],
                    canonical_json(keys),
                    canonical_json(meta or {}),
                    run_id,
                ),
            )

    def last_run(self, operation: str, params: dict[str, Any], *, status: str = "ok") -> FetchRun | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM fetch_runs WHERE operation=? AND params_hash=? AND status=? ORDER BY id DESC LIMIT 1",
                (operation, params_hash(params), status),
            ).fetchone()
        if row is None:
            return None
        return FetchRun(
            id=int(row["id"]),
            started=row["started"],
            finished=row["finished"],
            source=row["source"],
            operation=row["operation"],
            params=json.loads(row["params"]),
            status=row["status"],
            error=row["error"],
            result_keys=json.loads(row["result_keys"]) if row["result_keys"] else [],
            meta=json.loads(row["meta"]) if row["meta"] else {},
        )

    def recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, started, source, operation, status, error, n_total, n_new, n_changed, n_unchanged"
                " FROM fetch_runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "zeit": r["started"],
                "quelle": r["source"],
                "operation": r["operation"],
                "status": r["status"],
                "fehler": r["error"],
                "treffer": r["n_total"],
                "neu": r["n_new"],
                "geaendert": r["n_changed"],
                "unveraendert": r["n_unchanged"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------- graph

    def upsert_node(
        self,
        node_id: str,
        type_: str,
        label: str | None = None,
        props: dict[str, Any] | None = None,
        *,
        now: str | None = None,
    ) -> None:
        ts = now or utcnow()
        with self.transaction() as conn:
            row = conn.execute("SELECT props, label FROM nodes WHERE id=?", (node_id,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO nodes (id, type, label, props, first_seen, last_seen) VALUES (?,?,?,?,?,?)",
                    (node_id, type_, label, canonical_json(props or {}), ts, ts),
                )
                return
            merged = json.loads(row["props"] or "{}")
            if props:
                merged.update({k: v for k, v in props.items() if v is not None})
            conn.execute(
                "UPDATE nodes SET type=?, label=COALESCE(?, label), props=?, last_seen=? WHERE id=?",
                (type_, label, canonical_json(merged), ts, node_id),
            )

    def upsert_edge(
        self,
        src: str,
        dst: str,
        type_: str,
        props: dict[str, Any] | None = None,
        source: str | None = None,
        *,
        now: str | None = None,
    ) -> None:
        ts = now or utcnow()
        with self.transaction() as conn:
            row = conn.execute("SELECT props FROM edges WHERE src=? AND dst=? AND type=?", (src, dst, type_)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO edges (src, dst, type, props, source, first_seen, last_seen) VALUES (?,?,?,?,?,?,?)",
                    (src, dst, type_, canonical_json(props or {}), source, ts, ts),
                )
                return
            merged = json.loads(row["props"] or "{}")
            if props:
                merged.update({k: v for k, v in props.items() if v is not None})
            conn.execute(
                "UPDATE edges SET props=?, source=COALESCE(?, source), last_seen=? WHERE src=? AND dst=? AND type=?",
                (canonical_json(merged), source, ts, src, dst, type_),
            )

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "typ": row["type"],
            "label": row["label"],
            "eigenschaften": json.loads(row["props"] or "{}"),
            "zuerst_gesehen": row["first_seen"],
            "zuletzt_gesehen": row["last_seen"],
        }

    def find_nodes(
        self, *, type_: str | None = None, label_like: str | None = None, id_prefix: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        clauses, args = [], []
        if type_:
            clauses.append("type = ?")
            args.append(type_)
        if label_like:
            clauses.append("label LIKE ?")
            args.append(f"%{label_like}%")
        if id_prefix:
            clauses.append("id LIKE ?")
            args.append(id_prefix + "%")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            rows = self._conn.execute(f"SELECT * FROM nodes {where} ORDER BY id LIMIT ?", (*args, limit)).fetchall()
        return [
            {"id": r["id"], "typ": r["type"], "label": r["label"], "eigenschaften": json.loads(r["props"] or "{}")}
            for r in rows
        ]

    def edges(
        self, node_id: str, *, type_: str | None = None, direction: str = "beide", limit: int = 200
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        with self._lock:
            for col, other, richtung in (("src", "dst", "ausgehend"), ("dst", "src", "eingehend")):
                if direction not in ("beide", richtung):
                    continue
                sql = (
                    f"SELECT e.src, e.dst, e.type, e.props, e.source, n.type AS ntype, n.label AS nlabel "
                    f"FROM edges e LEFT JOIN nodes n ON n.id = e.{other} WHERE e.{col} = ?"
                )
                args: list[Any] = [node_id]
                if type_:
                    sql += " AND e.type = ?"
                    args.append(type_)
                sql += " ORDER BY e.type, e.last_seen DESC LIMIT ?"
                args.append(limit)
                for r in self._conn.execute(sql, args).fetchall():
                    results.append(
                        {
                            "richtung": richtung,
                            "typ": r["type"],
                            "knoten": r[other],
                            "knoten_typ": r["ntype"],
                            "knoten_label": r["nlabel"],
                            "eigenschaften": json.loads(r["props"] or "{}"),
                            "quelle": r["source"],
                        }
                    )
        return results

    def iter_graph(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        with self._lock:
            nodes = [
                {"id": r["id"], "typ": r["type"], "label": r["label"], "eigenschaften": json.loads(r["props"] or "{}")}
                for r in self._conn.execute("SELECT * FROM nodes ORDER BY id")
            ]
            edges = [
                {
                    "von": r["src"],
                    "nach": r["dst"],
                    "typ": r["type"],
                    "eigenschaften": json.loads(r["props"] or "{}"),
                    "quelle": r["source"],
                }
                for r in self._conn.execute("SELECT * FROM edges ORDER BY src, dst, type")
            ]
        return nodes, edges

    # ------------------------------------------------------------------- stats

    def stats(self) -> dict[str, Any]:
        with self._lock:
            by_source = [
                {
                    "quelle": r["source"],
                    "art": r["kind"],
                    "anzahl": int(r["n"]),
                    "verschwunden": int(r["gone"] or 0),
                    "zuletzt": r["last"],
                }
                for r in self._conn.execute(
                    "SELECT source, kind, COUNT(*) AS n, SUM(status = 'verschwunden') AS gone,"
                    " MAX(last_seen) AS last FROM records GROUP BY source, kind ORDER BY source, kind"
                )
            ]
            versions = int(self._conn.execute("SELECT COUNT(*) FROM record_versions").fetchone()[0])
            nodes = {
                r["type"]: int(r["n"])
                for r in self._conn.execute("SELECT type, COUNT(*) AS n FROM nodes GROUP BY type ORDER BY type")
            }
            edges = {
                r["type"]: int(r["n"])
                for r in self._conn.execute("SELECT type, COUNT(*) AS n FROM edges GROUP BY type ORDER BY type")
            }
        return {
            "datenbank": self.path,
            "volltextsuche": self.fts_enabled,
            "datensaetze": by_source,
            "versionen_gesamt": versions,
            "graph_knoten": nodes,
            "graph_kanten": edges,
            "ereignisse": self.change_counts(),
        }
