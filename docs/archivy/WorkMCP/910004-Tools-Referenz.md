---
date: 10-29-26
id: 910004
modified_at: 10/29/26 09:00
path: "WorkMCP"
tags:
- "workmcp"
- "doku"
- "tools"
title: "Tools-Referenz"
type: note
---

# Tools-Referenz

Alle Antworten sind strukturiertes JSON. Abrufende Tools enthalten ein Feld `gedaechtnis` mit `aus_speicher`, `stand` und `delta` (siehe [[Gedächtnis und Versionierung|910003]]). Erwartbare Fehler, etwa fehlende Parameter oder eine nicht erreichbare Quelle, kommen als lesbare Fehlermeldung beim Modell an.

## Stellenanzeigen

| Tool | Zweck | Wichtige Parameter |
|---|---|---|
| `search_jobs` | BA-Jobsuche (Deutschland-Kern) | `was`, `wo`, `umkreis`, `seiten`, `groesse` (≤100), `veroeffentlicht_seit`, `angebotsart` (arbeit/ausbildung/praktikum/selbstaendigkeit), `arbeitszeit`, `befristung`, `berufsfeld`, `arbeitgeber`, `zeitarbeit`, `aktualisieren` |
| `get_job_details` | Volltext einer BA-Anzeige, Branche, Fertigkeiten, Vergütung; 404 → Status `verschwunden` | `refnr` |
| `search_arbeitnow` | Arbeitnow-Stellen (aggregierte ATS-Feeds), lokal gefiltert | `was`, `remote_only`, `ort`, `visa_sponsorship`, `seiten` |
| `get_ats_jobs` | Stellen direkt aus dem ATS eines Arbeitgebers; ATS-Erkennung, Delta zeigt neue/geschlossene Stellen | `company_slug` (Slug oder Karriereseiten-URL), `ats`, `suchbegriff`, `ort`, `max_jobs` |
| `commoncrawl_lookup` | Common-Crawl-Index nach archivierten Seiten, optional Text laden | `url_muster`, `crawl`, `limit`, `text_abrufen` (≤5) |

**ATS-Erkennung:** Ohne `ats` werden Greenhouse, Lever, Ashby, Workable, Recruitee, Personio, SmartRecruiters und BambooHR nacheinander probiert. Das gefundene ATS merkt sich der Server je Firma. Workday braucht die Karriereseiten-URL, z. B. `https://intel.wd1.myworkdayjobs.com/External`.

## Berufe, Aufgaben, Skills

| Tool | Zweck | Wichtige Parameter |
|---|---|---|
| `search_occupation` | BERUFENET (mit KldB-Code), ESCO, KldB-Systematik, O*NET-Titel | `query`, `kldb_code`, `quellen`, `limit`, `sprache` |
| `get_occupation` | Profil zu `berufenet:<id>`, `kldb:<code>`, `isco:<code>`, `onet:<soc>` oder ESCO-URI | `beruf_id` |
| `get_tasks` | kanonische Aufgaben: O*NET (Core zuerst) und BERUFENET-Tätigkeiten | `beruf`, `quellen`, `nur_kern`, `limit` |
| `get_skills` | ESCO essential/optional plus Häufigkeiten aus gespeicherten BA-Anzeigen | `beruf`, `relation`, `limit` |
| `crosswalk` | Codes zwischen `kldb`, `isco`, `esco`, `onet`, `berufenet` übersetzen, auch mehrstufig (z. B. kldb→isco→esco→onet) | `code`, `von`, `nach` |
| `get_role_context` | alles in einem Aufruf: Zuordnung, Aufgaben, Skills, Entgelt, offene Stellen, optional Signale | `rolle`, `ort`, `mit_signalen` |

**Auflösung von Freitext:** BERUFENET-Suche (deutsch) → KldB-Code → ISCO (Umsteigeschlüssel) → ESCO → O*NET (Crosswalk). Für O*NET helfen auch ein O*NET-SOC-Code (`onet:13-2011.00`) oder ein englischer Titel.

## Gehalt

| Tool | Zweck | Wichtige Parameter |
|---|---|---|
| `get_salary` | Entgeltatlas: Median und Quartile (brutto/Monat, Vollzeit, SV-pflichtig), gekappte Werte gekennzeichnet | `kldb` (3–5 Ziffern), `region` (z. B. Bayern, München), `niveau` (helfer…experte), `geschlecht`, `alter`, `branche` |
| `adzuna_salary` | optional: Histogramm inserierter Gehälter, Top-Arbeitgeber, Verlauf je Kategorie | `was`, `standort` (z. B. `["Deutschland","Berlin"]`), `kategorie`, `monate` |

## Automatisierung und Extraktion

| Tool | Zweck | Wichtige Parameter |
|---|---|---|
| `find_automation_signals` | Hacker-News-Beiträge zu automatisierten Tätigkeiten; optional mit einer Aufgabe verknüpft | `suchbegriff` (englisch), `aufgabe_id` (Knoten-ID oder Aufgabentext), `zeitraum_tage`, `nur_kommentare` |
| `record_extraction` | extrahierte Aufgaben (mit Anteil an der Wochenarbeitszeit), Skills und Automatisierungsbewertungen versioniert speichern; schlägt kanonische Aufgaben vor | `bezug`, `aufgaben[]`, `skills[]`, `automatisierungen[]`, `quelle` |

## Gedächtnis, Daten, Betrieb

| Tool | Zweck |
|---|---|
| `remember` | eigene Daten (Rollenprofile, Feedback) versioniert speichern |
| `search_knowledge` | Volltextsuche offline (Arten u. a. `stelle`, `aufgabe`, `beruf`, `kldb`, `signal`) |
| `get_changes` | Änderungsprotokoll (`seit`: `24h`, `7d`, Datum; `ereignis`) |
| `get_history` | alle Versionen eines Datensatzes |
| `knowledge_stats` | Überblick über Bestände, Graph und letzte Abrufe |
| `graph_neighbors` | Nachbarn eines Knotens (mit Kantentyp und Richtung) |
| `import_reference_data` | `onet`, `kldb`, `kldb_isco`, `esco_onet` importieren oder aktualisieren |
| `export_knowledge` | `json`, `cypher` (Neo4j), `graphml`, `archivy` |
| `check_sources` | Erreichbarkeit aller Quellen prüfen (Status und Latenz) |

## Prompt

`rollen_analyse(rolle, ort)` führt durch: Rollenkontext → Aufgaben und Skills → Signale für die zeitintensivsten Aufgaben → speichern mit `record_extraction` → Quellen nennen.

Zurück zum [[WorkMCP Überblick|910001]].
