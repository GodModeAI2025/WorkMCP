---
date: 10-29-26
id: 910007
modified_at: 10/29/26 09:00
path: "WorkMCP"
tags:
- "workmcp"
- "doku"
- "graph"
title: "Job-Graph-Modell"
type: note
---

# Job-Graph-Modell

Der Graph liegt als Property-Graph in SQLite (`nodes`, `edges`) und wächst mit jedem Abruf. Jede Kante trägt ihre Herkunft (`quelle`) und Eigenschaften.

## Knoten

| Typ | ID-Schema | Herkunft |
|---|---|---|
| Beruf | `berufenet:<id>`, `esco:<uri>`, `onet:<soc>`, `berufsbezeichnung:<name>` | BERUFENET, ESCO, O*NET, BA-Anzeigen |
| Klassifikation | `kldb:<code>` (alle Ebenen), `isco:<code>` | KldB 2010, ISCO-08 |
| Aufgabe | `aufgabe:onet:<soc>#<task>`, `aufgabe:berufenet:<id>#<hash>`, `aufgabe:extrahiert:<hash>` | O*NET, BERUFENET, Modell/Experten |
| Skill | `skill:esco:<uri>`, `skill:ba:<name>`, `skill:extrahiert:<name>` | ESCO, BA-Fertigkeiten, Extraktion |
| Stellenanzeige | `stelle:ba:<refnr>`, `stelle:arbeitnow:<slug>`, `stelle:ats:<ats>:<firma>:<id>` | Jobquellen |
| Arbeitgeber, Branche, Region | `arbeitgeber:<name>`, `branche:<name>`, `region:<ort>` | Jobquellen |
| Automatisierung | `automatisierung:hn:<id>`, `automatisierung:extern:<hash>` | Hacker News, eigene Quellen |
| Entgelt | `entgelt:<kldb>\|r=…\|l=…` | Entgeltatlas |

## Kanten

| Kante | Richtung | Eigenschaften |
|---|---|---|
| `STELLT_AN` | Stellenanzeige → Aufgabe | `anteil_wochenarbeitszeit`, `quelle` |
| `ERFORDERT` | Stellenanzeige/Beruf → Skill | `relation` (essential/optional) |
| `TEIL_VON` | Aufgabe → Beruf | `task_type` (Core/Supplemental), `incumbents_responding`, Anteil |
| `AUTOMATISIERBAR_DURCH` | Aufgabe → Automatisierung | `bewertung` (0–1), `anteil_wochenarbeitszeit`, `suchbegriff`, `rang` |
| `GEHOERT_ZU` | Stellenanzeige → Branche | – |
| `FUER_BERUF` | Stellenanzeige → Beruf | über `hauptDkz` bzw. Berufsbezeichnung |
| `IN_REGION`, `AUSGESCHRIEBEN_VON` | Stellenanzeige → Region/Arbeitgeber | – |
| `KLASSIFIZIERT_ALS` | Beruf → KldB/ISCO | – |
| `ENTSPRICHT` | Crosswalk und Kanonisierung | `art` (exactMatch …), `hinweis` |
| `UNTERGRUPPE_VON` | KldB/ISCO-Hierarchie | – |
| `HAT_ENTGELT` | KldB → Entgelt | – |

## Automatisierungsbewertung nach Arbeitszeitanteil

Je Aufgabe speichert `record_extraction` den geschätzten Anteil an der Wochenarbeitszeit und je Automatisierung eine Bewertung von 0 bis 1. Daraus lässt sich das Potenzial einer Rolle abschätzen:

```text
Potenzial(Rolle) ≈ Σ über Aufgaben: anteil_wochenarbeitszeit × max(bewertung der verknüpften Automatisierungen)
```

## Export und Abfrage in Neo4j

```text
export_knowledge('cypher')   → graph-<zeit>.cypher
```

```bash
cypher-shell -u neo4j -p <passwort> < graph-<zeit>.cypher
```

Beispielabfrage, Aufgaben einer Berufsgattung über O*NET:

```cypher
MATCH (k:WorkMCP {id: 'kldb:72213'})-[:ENTSPRICHT|KLASSIFIZIERT_ALS*1..3]-(b:Beruf)<-[:TEIL_VON]-(a:Aufgabe)
RETURN b.label, a.label LIMIT 50;
```

GraphML (`export_knowledge('graphml')`) lässt sich mit NetworkX (`networkx.read_graphml`) oder Gephi öffnen. Wie der Archivy-Export funktioniert, steht in [[Archivy-Export|910010]].

Zurück zum [[WorkMCP Überblick|910001]].
