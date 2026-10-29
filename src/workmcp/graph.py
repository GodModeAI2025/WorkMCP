"""Node/edge conventions of the job graph and exporters (JSON, Neo4j Cypher, GraphML).

Node types follow the proposed model: Beruf, Klassifikation (KldB/ISCO, incl. job families via the
KldB hierarchy), Aufgabe, Skill, Stellenanzeige, Arbeitgeber, Branche, Region, Automatisierung, Entgelt.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from xml.sax.saxutils import escape, quoteattr

# edge types
STELLT_AN = "STELLT_AN"  # Stellenanzeige -> Aufgabe (extrahiert)
ERFORDERT = "ERFORDERT"  # Stellenanzeige/Beruf -> Skill
TEIL_VON = "TEIL_VON"  # Aufgabe -> Beruf
AUTOMATISIERBAR_DURCH = "AUTOMATISIERBAR_DURCH"  # Aufgabe -> Automatisierung
GEHOERT_ZU = "GEHOERT_ZU"  # Beruf/Stellenanzeige -> Branche
FUER_BERUF = "FUER_BERUF"  # Stellenanzeige -> Beruf
IN_REGION = "IN_REGION"  # Stellenanzeige -> Region
AUSGESCHRIEBEN_VON = "AUSGESCHRIEBEN_VON"  # Stellenanzeige -> Arbeitgeber
KLASSIFIZIERT_ALS = "KLASSIFIZIERT_ALS"  # Beruf -> KldB/ISCO
ENTSPRICHT = "ENTSPRICHT"  # crosswalk between classifications / canonical task or skill
UNTERGRUPPE_VON = "UNTERGRUPPE_VON"  # KldB/ISCO hierarchy (Berufsgattung -> ... -> Berufsbereich)
HAT_ENTGELT = "HAT_ENTGELT"  # KldB -> Entgelt

_SLUG_RE = re.compile(r"\s+")


def slug(text: str) -> str:
    return _SLUG_RE.sub("-", text.strip().lower())[:120]


def short_hash(text: str) -> str:
    return hashlib.sha1(slug(text).encode("utf-8")).hexdigest()[:12]


def kldb_id(code: str) -> str:
    return f"kldb:{code}"


def isco_id(code: str) -> str:
    return f"isco:{code}"


def esco_id(uri: str) -> str:
    return f"esco:{uri}"


def onet_id(soc: str) -> str:
    return f"onet:{soc}"


def berufenet_id(bid: str) -> str:
    return f"berufenet:{bid}"


def posting_id(source: str, key: str) -> str:
    return f"stelle:{source}:{key}"


def task_id(source: str, key: str) -> str:
    return f"aufgabe:{source}:{key}"


def skill_id(source: str, key: str) -> str:
    return f"skill:{source}:{key}"


def region_id(name: str) -> str:
    return f"region:{slug(name)}"


def employer_id(name: str) -> str:
    return f"arbeitgeber:{slug(name)}"


def branche_id(name: str) -> str:
    return f"branche:{slug(name)}"


def kldb_parents(code: str) -> list[str]:
    """KldB hierarchy: 43413 -> [4341, 434, 43, 4]."""
    return [code[:n] for n in range(len(code) - 1, 0, -1)]


# ------------------------------------------------------------------ export


def _flat(props: dict[str, Any]) -> dict[str, Any]:
    """Neo4j properties must be primitives or lists of primitives."""
    out: dict[str, Any] = {}
    for k, v in props.items():
        if v is None:
            continue
        primitive = (str, int, float, bool)
        if isinstance(v, primitive) or (isinstance(v, list) and all(isinstance(x, primitive) for x in v)):
            out[k] = v
        else:
            out[k] = json.dumps(v, ensure_ascii=False)
    return out


def _cypher_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_cypher_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def _cypher_map(props: dict[str, Any]) -> str:
    return "{" + ", ".join(f"`{k}`: {_cypher_value(v)}" for k, v in props.items()) + "}"


def _label(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", text) or "Knoten"


def to_cypher(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    lines = [
        "// WorkMCP Job-Graph – Import z. B. mit cypher-shell < graph.cypher",
        "CREATE CONSTRAINT workmcp_id IF NOT EXISTS FOR (n:WorkMCP) REQUIRE n.id IS UNIQUE;",
    ]
    for n in nodes:
        props = _flat({"label": n.get("label"), **(n.get("eigenschaften") or {})})
        node_id = _cypher_value(n["id"])
        lines.append(f"MERGE (n:WorkMCP {{id: {node_id}}}) SET n:{_label(n['typ'])} SET n += {_cypher_map(props)};")
    for e in edges:
        props = _flat({**(e.get("eigenschaften") or {}), "quelle": e.get("quelle")})
        lines.append(
            f"MATCH (a:WorkMCP {{id: {_cypher_value(e['von'])}}}), (b:WorkMCP {{id: {_cypher_value(e['nach'])}}}) "
            f"MERGE (a)-[r:{_label(e['typ'])}]->(b) SET r += {_cypher_map(props)};"
        )
    return "\n".join(lines) + "\n"


def to_graphml(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '  <key id="typ" for="all" attr.name="typ" attr.type="string"/>',
        '  <key id="label" for="node" attr.name="label" attr.type="string"/>',
        '  <key id="props" for="all" attr.name="eigenschaften" attr.type="string"/>',
        '  <graph id="workmcp" edgedefault="directed">',
    ]
    for n in nodes:
        out.append(f"    <node id={quoteattr(n['id'])}>")
        out.append(f'      <data key="typ">{escape(n["typ"])}</data>')
        out.append(f'      <data key="label">{escape(n.get("label") or "")}</data>')
        out.append(
            f'      <data key="props">{escape(json.dumps(n.get("eigenschaften") or {}, ensure_ascii=False))}</data>'
        )
        out.append("    </node>")
    for i, e in enumerate(edges):
        out.append(f'    <edge id="e{i}" source={quoteattr(e["von"])} target={quoteattr(e["nach"])}>')
        out.append(f'      <data key="typ">{escape(e["typ"])}</data>')
        out.append(
            f'      <data key="props">{escape(json.dumps(e.get("eigenschaften") or {}, ensure_ascii=False))}</data>'
        )
        out.append("    </edge>")
    out += ["  </graph>", "</graphml>"]
    return "\n".join(out) + "\n"
