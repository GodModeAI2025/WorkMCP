---
date: 10-29-26
id: 910001
modified_at: 10/29/26 09:00
path: "WorkMCP"
tags:
- "workmcp"
- "doku"
- "index"
title: "WorkMCP Überblick"
type: note
---

# WorkMCP Überblick

WorkMCP ist ein MCP-Server, der einen **Job-Graphen für Deutschland** aus öffentlichen Quellen aufbaut und als Kontext an Agent-Harnesses liefert. Er orientiert sich am Modell Rollen → Aufgaben → Workflows → Automatisierungen und ist eine offene, lokal betriebene Variante dessen, was Anbieter wie Cobrainer mit proprietären Daten machen.

## Drei Ebenen

| Ebene | Quellen | Wofür |
|---|---|---|
| Marktdaten | BA-Jobsuche, Arbeitnow, ATS-Karriereseiten, Common Crawl | Was wird tatsächlich gesucht? Volltexte, Arbeitgeber, Regionen |
| Referenzklassifikationen | BERUFENET, KldB 2010, ESCO, O*NET, Crosswalks | Kanonische Berufe, Aufgaben und Skills |
| Gehalt und Signale | Entgeltatlas, Adzuna (optional), Hacker News | Gehaltsbänder, Automatisierungsindizien |

## Architektur

```
 Harness (Claude Code, OpenCode, …)
            │  MCP: stdio oder Streamable HTTP
            ▼
 ┌──────────────────────────────────────────────┐
 │ server.py   24 Tools + Prompt rollen_analyse │
 │ service.py  Cache/TTL, Delta, Fallback       │
 │ occupations.py  Berufe, Crosswalks, Gehalt   │
 │ sources/*   BA, ESCO, O*NET, ATS, …          │
 └───────────────┬──────────────────────────────┘
                 ▼
 store.py  SQLite: Datensätze + Versionen + Changelog
           + Abruf-Läufe + Volltext + Graph (Knoten/Kanten)
```

## Weiterlesen

- [[Installation und Registrierung|910002]] ([Datei](910002-Installation_und_Registrierung.md))
- [[Gedächtnis und Versionierung|910003]] ([Datei](910003-Gedachtnis_und_Versionierung.md))
- [[Tools-Referenz|910004]] ([Datei](910004-Tools-Referenz.md))
- [[Datenquellen und Lizenzen|910005]] ([Datei](910005-Datenquellen_und_Lizenzen.md))
- [[Referenzdaten importieren|910006]] ([Datei](910006-Referenzdaten_importieren.md))
- [[Job-Graph-Modell|910007]] ([Datei](910007-Job-Graph-Modell.md))
- [[Faktencheck Kurzfassung|910008]] ([Datei](910008-Faktencheck_Kurzfassung.md))
- [[Rechtlicher Hinweis|910009]] ([Datei](910009-Rechtlicher_Hinweis.md))
- [[Archivy-Export|910010]] ([Datei](910010-Archivy-Export.md))
