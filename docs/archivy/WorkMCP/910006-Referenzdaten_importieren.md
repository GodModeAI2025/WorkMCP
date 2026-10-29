---
date: 10-29-26
id: 910006
modified_at: 10/29/26 09:00
path: "WorkMCP"
tags:
- "workmcp"
- "doku"
- "import"
title: "Referenzdaten importieren"
type: note
---

# Referenzdaten importieren

`import_reference_data(datensatz, quelle=…)` lädt Klassifikationen und Crosswalks ins Gedächtnis. Wiederholte Importe ergänzen neue Einträge, versionieren geänderte und markieren entfallene als `verschwunden`.

## O*NET (automatisch)

```text
import_reference_data('onet')                       # neueste Version wird auf onetcenter.org erkannt
import_reference_data('onet', onet_version='31_0')  # feste Version
import_reference_data('onet', quelle='/pfad/db_31_0_text.zip')   # lokales Archiv oder Ordner
```

Importiert werden „Occupation Data“, „Task Statements“ (Core/Supplemental, befragte Stelleninhaber) und optional „Alternate Titles“. Die Lizenz ist CC BY 4.0, siehe [[Datenquellen und Lizenzen|910005]].

## KldB 2010 (Fassung 2020)

Quelle: BA-Statistik, Klassifikation der Berufe, KldB 2010 Fassung 2020, Systematik-Verzeichnisse (XLSX). Erwartet werden eine Spalte mit dem Schlüssel (1–5 Ziffern, auch „B 72213“) und eine mit Titel oder Bezeichnung. Eine Spalte „Ebene“ ist optional, sie füllt führende Nullen auf. Titelzeilen oberhalb der Kopfzeile stören nicht.

```text
import_reference_data('kldb', quelle='/pfad/KldB2010-Fassung2020.xlsx')
```

Ergebnis: Klassifikationsknoten mit Ebene (Berufsbereich … Berufsgattung), Anforderungsniveau (Helfer, Fachkraft, Spezialist, Experte) und `UNTERGRUPPE_VON`-Kanten. Die Hierarchie dient als Jobfamilie und Jobcluster.

## Umsteigeschlüssel KldB 2010 → ISCO-08

Quelle: BA-Statistik → KldB 2010 Fassung 2020 → Arbeitsmittel, „Umsteigeschlüssel vom 5-Steller (Berufsgattung) KldB 2010 zum 4-Steller (Unit Group) ISCO-08“. Spalten werden an „KldB“/„ISCO“ bzw. an der Form der Werte erkannt (5- und 4-stellig). Hinweise zur Eindeutigkeit werden übernommen, sofern vorhanden.

```text
import_reference_data('kldb_isco', quelle='/pfad/Umsteigeschluessel-KldB2010-ISCO08.xlsx')
```

Umsteigeschlüssel sind oft nicht eindeutig (1:n). `crosswalk` liefert dann alle Kandidaten.

## ESCO ↔ O*NET

Quelle: ESCO-Portal („Other crosswalks“) oder O*NET Resource Center („Crosswalk Files“). Spalten werden an der Form erkannt: ESCO-Berufs-URI (`http://data.europa.eu/esco/occupation/…`) und O*NET-SOC-Code (`13-2011.00`), optional Titel und Match-Art.

```text
import_reference_data('esco_onet', quelle='/pfad/esco_onet_crosswalk.csv')
```

## Standardquellen

Mit `WORKMCP_KLDB_SOURCE`, `WORKMCP_KLDB_ISCO_SOURCE` und `WORKMCP_ESCO_ONET_SOURCE` (URL oder Pfad) lässt sich `quelle` weglassen. Altes Excel (`.xls`) wird nicht gelesen, solche Dateien bitte als `.xlsx` oder `.csv` speichern.

Zurück zum [[WorkMCP Überblick|910001]].
