"""Export the remembered job graph as Archivy notes (https://github.com/archivy/archivy).

Archivy stores every note as ``{id}-{title}.md`` with YAML front matter (``type``, ``title``, ``date``,
``modified_at``, ``tags``, ``id``, ``path``) and links notes with ``[[title|id]]``.  The export writes
into a sub folder (default ``WorkMCP``) of an Archivy data directory and keeps note ids stable across
exports via ``.workmcp-archivy-ids.json``.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from .store import KnowledgeStore

ID_BASE = 900_000
NOTE_TYPES = ("Beruf",)


def secure_title(title: str) -> str:
    """Same idea as werkzeug.secure_filename, which Archivy uses for file names."""
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text.replace("/", " ")).strip("._")
    return text[:200] or "note"


def _yaml_str(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def note_text(note_id: int, title: str, content: str, tags: list[str], path: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    tag_lines = "".join(f"- {_yaml_str(t)}\n" for t in tags) if tags else ""
    return (
        "---\n"
        f"date: {now.strftime('%m-%d-%y')}\n"
        f"id: {note_id}\n"
        f"modified_at: {now.strftime('%m/%d/%y %H:%M')}\n"
        f"path: {_yaml_str(path)}\n"
        f"tags:{' []' if not tags else ''}\n{tag_lines}"
        f"title: {_yaml_str(title)}\n"
        "type: note\n"
        "---\n\n"
        f"{content.rstrip()}\n"
    )


def export_archivy(store: KnowledgeStore, target: Path, sub_folder: str = "WorkMCP") -> dict[str, Any]:
    folder = target / sub_folder if sub_folder else target
    folder.mkdir(parents=True, exist_ok=True)
    id_file = folder / ".workmcp-archivy-ids.json"
    try:
        ids: dict[str, int] = json.loads(id_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ids = {}

    def note_id(key: str) -> int:
        if key not in ids:
            ids[key] = max(ids.values(), default=ID_BASE) + 1
        return ids[key]

    nodes, edges = store.iter_graph()
    by_id = {n["id"]: n for n in nodes}
    out_edges: dict[str, list[dict[str, Any]]] = {}
    in_edges: dict[str, list[dict[str, Any]]] = {}
    for e in edges:
        out_edges.setdefault(e["von"], []).append(e)
        in_edges.setdefault(e["nach"], []).append(e)

    def has_content(nid: str) -> bool:
        return any(e["typ"] in ("ERFORDERT", "KLASSIFIZIERT_ALS", "ENTSPRICHT") for e in out_edges.get(nid, [])) or any(
            e["typ"] == "TEIL_VON" for e in in_edges.get(nid, [])
        )

    berufe = [n for n in nodes if n["typ"] in NOTE_TYPES and has_content(n["id"])]
    titles = {n["id"]: (n.get("label") or n["id"]) for n in berufe}

    def link(nid: str) -> str:
        if nid in titles:
            return f"[[{titles[nid]}|{note_id(nid)}]]"
        return by_id.get(nid, {}).get("label") or nid

    written = []
    for n in berufe:
        nid = n["id"]
        title = titles[nid]
        props = n.get("eigenschaften") or {}
        lines = [f"# {title}", "", f"- Knoten: `{nid}`"]
        if props.get("url"):
            lines.append(f"- Quelle: {props['url']}")
        klass = [e for e in out_edges.get(nid, []) if e["typ"] == "KLASSIFIZIERT_ALS"]
        if klass:
            lines += [
                "",
                "## Klassifikation",
                *[f"- {e['nach']} {by_id.get(e['nach'], {}).get('label') or ''}".rstrip() for e in klass],
            ]
        tasks = [e for e in in_edges.get(nid, []) if e["typ"] == "TEIL_VON"]
        if tasks:
            lines += ["", "## Aufgaben"]
            for e in tasks[:60]:
                typ = (e.get("eigenschaften") or {}).get("task_type")
                lines.append(f"- {by_id.get(e['von'], {}).get('label') or e['von']}" + (f" _({typ})_" if typ else ""))
        skills = [e for e in out_edges.get(nid, []) if e["typ"] == "ERFORDERT"]
        if skills:
            lines += ["", "## Skills"]
            for e in skills[:80]:
                rel = (e.get("eigenschaften") or {}).get("relation")
                lines.append(f"- {by_id.get(e['nach'], {}).get('label') or e['nach']}" + (f" ({rel})" if rel else ""))
        same = [e["nach"] for e in out_edges.get(nid, []) if e["typ"] == "ENTSPRICHT"] + [
            e["von"] for e in in_edges.get(nid, []) if e["typ"] == "ENTSPRICHT"
        ]
        if same:
            lines += ["", "## Entspricht", *[f"- {link(x)}" for x in dict.fromkeys(same)]]
        lines += ["", "_Automatisch exportiert aus dem WorkMCP-Gedächtnis. Lizenzen der Quellen beachten._"]
        source_tag = str(props.get("quelle") or "workmcp").lower().replace(" ", "-")
        nid_num = note_id(nid)
        path = folder / f"{nid_num}-{secure_title(title)}.md"
        for old in folder.glob(f"{nid_num}-*.md"):
            if old != path:
                old.unlink()
        path.write_text(
            note_text(nid_num, title, "\n".join(lines), ["workmcp", "beruf", source_tag], sub_folder), encoding="utf-8"
        )
        written.append(path.name)
    index_lines = ["# WorkMCP – Berufe im Gedächtnis", "", *[f"- {link(n['id'])}" for n in berufe]]
    index_id = note_id("__index__")
    for old in folder.glob(f"{index_id}-*.md"):
        old.unlink()
    (folder / f"{index_id}-WorkMCP_Index.md").write_text(
        note_text(index_id, "WorkMCP Index", "\n".join(index_lines), ["workmcp", "index"], sub_folder), encoding="utf-8"
    )
    id_file.write_text(json.dumps(ids, indent=1, ensure_ascii=False), encoding="utf-8")
    return {
        "format": "archivy",
        "ordner": str(folder),
        "notizen": len(written) + 1,
        "hinweis": "Ordner in das Archivy-Datenverzeichnis legen (oder dieses als Ziel wählen); IDs ab 900001.",
    }
