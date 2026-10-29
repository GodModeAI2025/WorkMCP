---
date: 10-29-26
id: 910003
modified_at: 10/29/26 09:00
path: "WorkMCP"
tags:
- "workmcp"
- "doku"
- "gedaechtnis"
title: "Gedächtnis und Versionierung"
type: note
---

# Gedächtnis und Versionierung

Anforderung: Der MCP-Server soll sich abgerufene Daten merken und neue oder veränderte Daten jeweils ergänzen.

## Datenmodell (SQLite)

| Tabelle | Inhalt |
|---|---|
| `records` | ein Datensatz je (Quelle, Art, Schlüssel): aktuelle Daten, Inhalts-Hash, Version, Status, zuerst/zuletzt gesehen, zuletzt geändert, Abrufzähler |
| `record_versions` | jede Version mit Gültigkeitszeitraum (`gueltig_ab`/`gueltig_bis`) |
| `changelog` | Ereignisse `neu`, `geaendert` (mit feldgenauem Diff), `verschwunden`, `wieder_da` |
| `fetch_runs` | jeder Abruf mit Parametern, Zählern und Ergebnisschlüsseln (Basis für TTL und Delta) |
| `search_index` | Volltextindex (FTS5, umlauttolerant) |
| `nodes`/`edges` | Job-Graph mit Eigenschaften und Herkunft |

## Ablauf eines Abrufs

1. Gab es dieselbe Anfrage (gleiche Parameter) innerhalb der Gültigkeitsdauer, kommt die Antwort aus dem Speicher (`aus_speicher: true`).
2. Sonst wird die Quelle gefragt. Jeder Datensatz wird per Inhalts-Hash verglichen: **neu**, **geändert** (neue Version, Diff im Changelog) oder **unverändert** (nur „zuletzt gesehen“).
3. Das Delta gegenüber der letzten identischen Anfrage steht in `gedaechtnis.delta`: `neu`, `geaendert` (mit Feldänderungen), `wieder_da`, `unveraendert` (Anzahl) und `nicht_mehr_enthalten`. Letzteres zeigt zum Beispiel offline genommene Stellen oder geschlossene ATS-Stellen.
4. Ist die Quelle nicht erreichbar, kommt der letzte gespeicherte Stand mit einer Warnung.

Flüchtige Felder lösen keine neue Version aus, etwa die Hacker-News-Punkte.

## Gültigkeitsdauer (TTL)

| Art | Standard | Variable |
|---|---|---|
| Stellensuche | 6 h | `WORKMCP_TTL_JOBS_HOURS` |
| Stellendetails, Adzuna | 24 h | `WORKMCP_TTL_DETAILS_HOURS` |
| Berufe, ESCO, Entgeltatlas, Common-Crawl-Index | 30 Tage | `WORKMCP_TTL_REFERENCE_DAYS` |
| Automatisierungssignale | 24 h | `WORKMCP_TTL_SIGNALS_HOURS` |

`aktualisieren: true` erzwingt einen frischen Abruf. Im Offline-Modus (`WORKMCP_OFFLINE=1` oder `--offline`) gibt es nur Antworten aus dem Gedächtnis.

## Wiederholte Importe

`import_reference_data` arbeitet genauso. Ein neues O*NET-Release ergänzt neue Aufgaben, versioniert geänderte und markiert entfallene als `verschwunden`. Gelöscht wird nichts.

## Eigene Daten und Expertenwissen

- `remember(art, schluessel, daten)` speichert z. B. interne Rollenprofile oder Kundendokumente als strukturierte Daten, versioniert wie alles andere.
- `record_extraction(bezug, aufgaben, skills, automatisierungen, quelle)` speichert vom Modell extrahierte oder von Fachexperten korrigierte Aufgaben, Skills und Automatisierungsbewertungen mit Version und Changelog.

## Auswerten

- `get_changes(seit='7d', ereignis='verschwunden')`
- `get_history(quelle, art, schluessel)`
- `search_knowledge('Rechnungen prüfen', art='aufgabe')`
- `knowledge_stats()`

## Datenschutz

Kontaktfelder aus Stellenanzeigen (Kontakt, Ansprechpartner, Telefon, E-Mail, Bewerbung) werden vor dem Speichern entfernt. Abschalten lässt sich das mit `WORKMCP_STORE_PERSONAL_DATA=1`, siehe [[Rechtlicher Hinweis|910009]].

Zurück zum [[WorkMCP Überblick|910001]].
