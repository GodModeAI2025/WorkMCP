# WorkMCP-Dokumentation für Archivy

Der Ordner [`WorkMCP/`](WorkMCP/) enthält die Projektdokumentation als **Archivy-Notizen**. [Archivy](https://github.com/archivy/archivy) ist eine selbst gehostete Wissensdatenbank. Jede Notiz ist eine Markdown-Datei `{id}-{titel}.md` mit YAML-Front-Matter (`type`, `title`, `date`, `modified_at`, `tags`, `id`, `path`). Notizen verlinken sich mit `[[Titel|ID]]`.

## In Archivy laden

1. Archivy installieren und einrichten (siehe [Archivy-Doku](https://archivy.github.io)):

   ```bash
   pip install archivy
   ```

   ```bash
   archivy init
   ```

   ```bash
   archivy create-admin <benutzername>
   ```

2. Den Ordner `WorkMCP/` in das Archivy-Datenverzeichnis kopieren. Den Pfad nennt `archivy init`, typischerweise `…/archivy/data/`.
3. `archivy run` starten. Die Notizen erscheinen im Ordner **WorkMCP** und sind durchsuchbar. Bei Ripgrep- oder Elasticsearch-Suche ggf. `archivy index` ausführen.

Die Notiz-IDs liegen im Bereich **910001–910099**, damit sie nicht mit eigenen Notizen kollidieren. Der Export der gemerkten Berufe (`export_knowledge('archivy')`) nutzt IDs ab **900001** im selben Ordner `WorkMCP/`. So entsteht eine gemeinsame, verlinkte Wissensbasis aus Doku und Daten.

## Notizen

| ID | Notiz |
|---|---|
| 910001 | [WorkMCP Überblick](WorkMCP/910001-WorkMCP_Uberblick.md) |
| 910002 | [Installation und Registrierung](WorkMCP/910002-Installation_und_Registrierung.md) |
| 910003 | [Gedächtnis und Versionierung](WorkMCP/910003-Gedachtnis_und_Versionierung.md) |
| 910004 | [Tools-Referenz](WorkMCP/910004-Tools-Referenz.md) |
| 910005 | [Datenquellen und Lizenzen](WorkMCP/910005-Datenquellen_und_Lizenzen.md) |
| 910006 | [Referenzdaten importieren](WorkMCP/910006-Referenzdaten_importieren.md) |
| 910007 | [Job-Graph-Modell](WorkMCP/910007-Job-Graph-Modell.md) |
| 910008 | [Faktencheck Kurzfassung](WorkMCP/910008-Faktencheck_Kurzfassung.md) |
| 910009 | [Rechtlicher Hinweis](WorkMCP/910009-Rechtlicher_Hinweis.md) |
| 910010 | [Archivy-Export](WorkMCP/910010-Archivy-Export.md) |
