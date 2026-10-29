---
date: 10-29-26
id: 910010
modified_at: 10/29/26 09:00
path: "WorkMCP"
tags:
- "workmcp"
- "doku"
- "archivy"
title: "Archivy-Export"
type: note
---

# Archivy-Export

`export_knowledge('archivy', pfad=…)` schreibt die gemerkten Berufe als verlinkte Archivy-Notizen. Das sind Berufe aus BERUFENET, ESCO und O*NET, die Aufgaben, Skills, Klassifikationen oder Entsprechungen haben.

```text
export_knowledge('archivy', pfad='/pfad/zum/archivy/data')
```

## Ergebnis

- **Ordner** `WorkMCP/` im Zielverzeichnis, im Front-Matter `path: "WorkMCP"`.
- **Notizen** je Beruf mit den Abschnitten Klassifikation, Aufgaben (mit O*NET Core/Supplemental), Skills (essential/optional) und Entspricht. Die letzten verlinken andere Berufsnotizen per `[[Titel|ID]]`.
- **Index:** eine Indexnotiz „WorkMCP Index“ mit allen Berufen.
- **IDs:** ab **900001**, stabil über wiederholte Exporte (Datei `.workmcp-archivy-ids.json` im Ordner). Ein erneuter Export aktualisiert die Notizen statt Duplikate anzulegen.
- **Front-Matter:** wie von Archivy selbst geschrieben: `type: note`, `title`, `date` (mm-dd-yy), `modified_at` (mm/dd/yy HH:MM), `tags`, `id`, `path`.

## Zusammen mit der Doku nutzen

Die Projektdokumentation (IDs 910001–910010) liegt im selben Ordner `WorkMCP/`. Einmal kopiert, steht in Archivy Doku und Daten nebeneinander und ist gemeinsam durchsuchbar.

## Hinweise

- Archivy führt intern einen Zähler für die nächste freie ID. Die hohen ID-Bereiche vermeiden Kollisionen mit eigenen Notizen.
- Die exportierten Inhalte unterliegen weiter den Lizenzen ihrer Quellen, z. B. O*NET CC BY 4.0. Jede Notiz weist darauf hin.

Zurück zum [[WorkMCP Überblick|910001]].
