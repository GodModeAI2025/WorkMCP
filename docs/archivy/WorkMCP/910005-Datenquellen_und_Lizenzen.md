---
date: 10-29-26
id: 910005
modified_at: 10/29/26 09:00
path: "WorkMCP"
tags:
- "workmcp"
- "doku"
- "quellen"
- "lizenzen"
title: "Datenquellen und Lizenzen"
type: note
---

# Datenquellen und Lizenzen

> Die Angaben sind eine **unverbindliche Orientierung** (Stand 29.10.2026). Lizenzen und Nutzungsbedingungen prüfen Nutzende selbst, siehe [[Rechtlicher Hinweis|910009]]. Alle integrierten Quellen sind kostenlos, kostenpflichtige APIs werden nicht genutzt.

| Quelle | Endpunkt (Standard) | Zugang | Status | Lizenz/Bedingungen |
|---|---|---|---|---|
| BA-Jobsuche | `rest.arbeitsagentur.de/jobboerse/jobsuche-service` (`/pc/v6/jobs`, Fallback v4; Details `/pc/v4/jobdetails/{base64(refnr)}`) | `X-API-Key: jobboerse-jobsuche` | inoffiziell, von bundesAPI dokumentiert | keine veröffentlichten API-Bedingungen; Inhalte der Inserierenden |
| BERUFENET | `rest.arbeitsagentur.de/infosysbub/bnet/pc/v1/berufe` | `X-API-Key: infosysbub-berufenet` | inoffiziell | Inhalte der BA |
| Entgeltatlas | `rest.arbeitsagentur.de/infosysbub/entgeltatlas/pc/v1/entgelte/{kldb}` | `X-API-Key: infosysbub-ega` (Fallback: Client-ID aus der bundesAPI-Doku) | inoffiziell | Quellenangabe „Statistik der Bundesagentur für Arbeit“ |
| ESCO | `ec.europa.eu/esco/api` (`search`, `resource/occupation`, `resource/concept`) | ohne Key | offizielle Web-API | Nutzungsbedingungen der Europäischen Kommission, Quellenangabe |
| O*NET | `onetcenter.org/dl_files/database/db_<version>_text/…` | ohne Key | offizieller Download | **CC BY 4.0**, Namensnennung USDOL/ETA (Wortlaut siehe unten) |
| KldB 2010 (Fassung 2020), Umsteigeschlüssel KldB→ISCO-08 | Dateien der BA-Statistik (Import) | – | amtlich | Quellenangabe Bundesagentur für Arbeit |
| ESCO↔O*NET-Crosswalk | CSV/XLSX vom ESCO-Portal oder O*NET (Import) | – | offiziell | Bedingungen der Herausgeber |
| Arbeitnow | `arbeitnow.com/api/job-board-api` | ohne Key | öffentliche API | Bedingungen von Arbeitnow |
| ATS-Job-Boards | Greenhouse, Lever, Ashby, Workable, Recruitee, Personio (XML), SmartRecruiters, BambooHR, Workday | ohne Login | öffentliche Karriereseiten-Feeds (Referenz live verifiziert am 04.08.2026) | robots.txt und Bedingungen der Arbeitgeber bzw. ATS-Anbieter; schonend abrufen, auf die Originalanzeige verlinken |
| Adzuna (optional) | `api.adzuna.com/v1/api/jobs/de/{histogram,top_companies,history,search}` | kostenloser Developer-Key | offizielle API | Adzuna-API-Bedingungen (u. a. `redirect_url` zur Anzeige nutzen) |
| Hacker News | `hn.algolia.com/api/v1/search` | ohne Key | öffentliche API | Inhalte gehören den Verfassenden |
| Common Crawl | `index.commoncrawl.org`, `data.commoncrawl.org` | ohne Key | öffentlich | Common Crawl Terms of Use; Urheberrecht der Seitenbetreiber |

## Namensnennung O*NET (Vorschlag)

> Dieses Produkt nutzt Informationen aus der O*NET-Datenbank (Release <Version>) des U.S. Department of Labor, Employment and Training Administration (USDOL/ETA), lizenziert unter CC BY 4.0. O*NET® ist eine Marke von USDOL/ETA. WorkMCP hat die Daten ggf. verändert; USDOL/ETA ist für diese Inhalte nicht verantwortlich.

Den verbindlichen Wortlaut gibt die Lizenzseite der O*NET-Datenbank auf onetcenter.org vor.

## Bewusst nicht integriert

| Quelle | Grund |
|---|---|
| LinkedIn, Indeed, StepStone, XING | keine Lese-API; AGB verbieten Scraping (Indeed betreibt einen eigenen MCP-Server in der Beta) |
| Interamt | API nur zum Einpflegen von Stellen |
| Apify-Actors | kostenpflichtig |
| StepStone/GEHALT.de-Gehaltsreport | keine API |
| GENESIS (Destatis), IAB-Stellenerhebung, BIBB-FDZ | Registrierung bzw. Forschungsdatenzugang; als Erweiterung denkbar |

## Erreichbarkeit

`check_sources` fragt jede Quelle einmal vom eigenen Rechner aus ab. Jede HTTP-Antwort zählt als erreichbar, auch ein 404. Gemeldet werden Status und Latenz.

Zurück zum [[WorkMCP Überblick|910001]].
