---
date: 10-29-26
id: 910008
modified_at: 10/29/26 09:00
path: "WorkMCP"
tags:
- "workmcp"
- "doku"
- "faktencheck"
title: "Faktencheck Kurzfassung"
type: note
---

# Faktencheck Kurzfassung

Die vollständige Prüfung mit Belegen steht in `FAKTENCHECK.md` im Repository-Wurzelverzeichnis. Die wichtigsten Korrekturen an der zugrunde liegenden Recherche:

1. **BA-Jobsuche, BERUFENET und Entgeltatlas sind keine offiziellen APIs.** Die Dokumentation stammt von der Community (bundesAPI), Endpunkte können sich ändern.
2. **FastMCP heißt seit `mcp` 2.0 `MCPServer`.** Alter Code mit `mcp.server.fastmcp` startet mit dem aktuellen SDK nicht mehr. SSE ist veraltet.
3. **Die Jobsuche v6 liefert `ergebnisliste`/`stellenlokationen`.** Die OpenAPI-Spezifikation beschreibt noch das v4-Format.
4. **BERUFENET hat eine JSON-Schnittstelle.** Scraping ist nicht nötig.
5. **Gehaltsbänder gibt es amtlich im Entgeltatlas.** Adzuna ist nicht die „einzige“ Gehaltsquelle und liefert inserierte, teils geschätzte Werte.
6. **Die KldB ist kein Branchen-Overlay.** Branchen klassifiziert die WZ; Primärquelle der KldB ist die BA-Statistik.
7. **Fertige MCP-Server für BERUFENET, ESCO und O*NET gibt es,** etabliert ist keiner davon.
8. **Die Quellenangaben der Recherche sind um eine Zeile verschoben.**
9. **O*NET steht unter CC BY 4.0,** Namensnennung ist Pflicht. Aktuell ist Release 31.0.
10. **Die Cobrainer-Zahlen (250.000 Skills, 15 Jahre) sind öffentlich nicht belegt.**

Wie sich diese Korrekturen im Code niederschlagen, steht in [[Datenquellen und Lizenzen|910005]].

Zurück zum [[WorkMCP Überblick|910001]].
