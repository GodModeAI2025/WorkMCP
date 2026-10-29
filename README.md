# WorkMCP – Job-Graph Deutschland als MCP-Server

WorkMCP ist eine MCP-Kontextschicht für Rollen, Aufgaben und Automatisierung. Agent-Harnesses wie Claude Code, OpenCode oder Copilot Studio erhalten darüber Stellenanzeigen, Berufe, Aufgaben, Skills, Gehälter und Automatisierungssignale aus öffentlichen Quellen. **Jeder Abruf wird lokal gemerkt.** Neue und geänderte Daten werden versioniert ergänzt, nichts wird stillschweigend überschrieben.

> **Rechtlicher Hinweis:** WorkMCP ist keine Rechtsberatung. Lizenzen und Nutzungsbedingungen der Datenquellen müssen Nutzende selbst prüfen. Eine Haftung für die Nutzung ist ausgeschlossen, soweit gesetzlich zulässig. Details stehen auf der [Landingpage](docs/index.html#recht) und im [Rechtlichen Hinweis](docs/archivy/WorkMCP/910009-Rechtlicher_Hinweis.md).

## Was der Server kann

- **Stellenanzeigen** aus drei sich ergänzenden Volltextquellen:
  - BA-Jobsuche als Deutschland-Kern.
  - Arbeitnow mit aggregierten ATS-Feeds, Remote- und Visa-Filter.
  - ATS-Karriereseiten direkt (Greenhouse, Lever, Ashby, Workable, Recruitee, Personio, SmartRecruiters, BambooHR, Workday) mit Abteilung, Seniority und Anstellungsart.
- **Berufe und Aufgaben:**
  - BERUFENET mit Aufgaben, Tätigkeitsfeldern und KldB-Code.
  - ESCO mit essential/optional Skills und ISCO-Gruppe.
  - O*NET Task Statements (Core/Supplemental).
  - KldB 2010 inklusive Hierarchie als Jobfamilien.
- **Crosswalks** KldB ↔ ISCO-08 ↔ ESCO ↔ O*NET ↔ BERUFENET, auch über mehrere Stufen.
- **Gehälter:**
  - Amtliche Medianentgelte mit Quartilen aus dem Entgeltatlas der BA.
  - Optional Gehalts-Histogramme aus Adzuna (kostenloser Key).
- **Automatisierungssignale** aus Hacker News. Aufgaben, Skills und Bewertungen speichert das Modell mit `record_extraction` versioniert im Graphen.
- **Rollenkontext in einem Aufruf** (`get_role_context`): Zuordnung, Aufgaben, Skills, Gehalt und Marktsignal.
- **Job-Graph** mit Knoten, Kanten und Herkunft, exportierbar als JSON, Neo4j-Cypher, GraphML oder als **Archivy-Wissensdatenbank**.
- **`check_sources`** prüft die Erreichbarkeit aller Quellen vom eigenen Rechner aus.

## Schnellstart

Voraussetzungen: Python ≥ 3.10 und [uv](https://docs.astral.sh/uv/).

**Claude Code (stdio, lokal):**

```bash
claude mcp add workmcp -- uvx --from git+https://github.com/GodModeAI2025/WorkMCP workmcp
```

Mit eigenem Speicherort der Wissensdatenbank:

```bash
claude mcp add --transport stdio workmcp --env WORKMCP_DB=$HOME/.workmcp/knowledge.db -- uvx --from git+https://github.com/GodModeAI2025/WorkMCP workmcp
```

**Aus einem lokalen Klon:**

```bash
git clone https://github.com/GodModeAI2025/WorkMCP.git
```

```bash
claude mcp add workmcp -- uv --directory /pfad/zu/WorkMCP run workmcp
```

**Zentral über Streamable HTTP** (ein Server für mehrere Harnesses):

```bash
uvx --from git+https://github.com/GodModeAI2025/WorkMCP workmcp --transport streamable-http --host 0.0.0.0 --port 8000
```

```bash
claude mcp add --transport http workmcp http://<server>:8000/mcp
```

Der HTTP-Modus hat keine eigene Authentifizierung. Betreibe ihn nur im internen Netz oder hinter einem Reverse Proxy mit Zugangsschutz. Mit `--allowed-host mcp.firma.de` (mehrfach möglich) oder `WORKMCP_ALLOWED_HOSTS` prüft der Server zusätzlich den Host-Header (Schutz vor DNS-Rebinding). Das Compose-Setup aktiviert diese Prüfung standardmäßig für localhost.

**Docker: WorkMCP und Archivy zusammen** (zentraler MCP-Server plus Wissensdatenbank mit vorinstallierter Doku):

```bash
cp .env.example .env
```

```bash
docker compose up -d --build
```

- Archivy: http://localhost:5000 (Login aus `.env`). Die Doku liegt im Ordner **WorkMCP**.
- WorkMCP: `http://localhost:8000/mcp`, in Claude Code mit `claude mcp add --transport http workmcp http://localhost:8000/mcp`.
- `export_knowledge('archivy')` schreibt die gemerkten Berufe direkt in denselben Archivy-Ordner. Beide Container teilen sich das Archivy-Volume (`WORKMCP_ARCHIVY_DIR=/archivy/data`).
- Beide Ports sind nur an 127.0.0.1 gebunden. Bei Docker-Hub-Rate-Limits lassen sich in `.env` Spiegel-Images setzen (`ARCHIVY_PYTHON_IMAGE`, `WORKMCP_PYTHON_IMAGE`).
- Getestet am 29.10.2026 mit Docker 29.9 und Compose v5.6: Start ohne Assistent, Login, Doku-Notizen sichtbar, Export aus WorkMCP erscheint sofort in Archivy, Neustart idempotent.

**Projektkonfiguration `.mcp.json`:**

```json
{
  "mcpServers": {
    "workmcp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/GodModeAI2025/WorkMCP", "workmcp"],
      "env": { "WORKMCP_DB": "~/.workmcp/knowledge.db" }
    }
  }
}
```

**OpenCode (`opencode.json`):**

```json
{
  "mcp": {
    "workmcp": {
      "type": "local",
      "command": ["uvx", "--from", "git+https://github.com/GodModeAI2025/WorkMCP", "workmcp"],
      "enabled": true
    }
  }
}
```

**Erste Schritte im Harness:**

1. `check_sources` prüft, ob alle Quellen erreichbar sind.
2. `import_reference_data('onet')` lädt die O*NET-Aufgaben einmalig, die Version wird automatisch erkannt.
3. `get_role_context('Buchhalter', ort='Berlin')` liefert den ersten Rollenkontext.

## Gedächtnis: merken und ergänzen

| Situation | Verhalten |
|---|---|
| Neuer Datensatz | wird gespeichert (Version 1, Ereignis `neu`) |
| Geänderter Datensatz | neue Version, alte Version bleibt erhalten, feldgenaues Diff (`geaendert`) |
| Unveränderter Datensatz | nur „zuletzt gesehen“ und der Abrufzähler werden aktualisiert |
| Anzeige nicht mehr abrufbar (404) | Status `verschwunden`, wird nie gelöscht; taucht sie wieder auf: `wieder_da` |
| Wiederholte Anfrage innerhalb der TTL | Antwort aus dem Speicher (`aus_speicher: true`) |
| Quelle nicht erreichbar | letzter gespeicherter Stand mit Warnung |
| `aktualisieren: true` | frischer Abruf; das Delta zeigt `neu`, `geaendert` und `nicht_mehr_enthalten` gegenüber der letzten identischen Anfrage |
| Offline-Modus (`WORKMCP_OFFLINE=1`) | nur Gedächtnis, keine Netzzugriffe |

Werkzeuge zum Gedächtnis:

- `get_changes(seit='7d')`: Änderungsprotokoll.
- `get_history(...)`: alle Versionen eines Datensatzes.
- `search_knowledge(...)`: Volltextsuche offline.
- `knowledge_stats()`: Überblick.
- `remember(...)`: eigene Daten wie interne Rollenprofile oder Expertenfeedback, ebenfalls versioniert.

## Tools

| Bereich | Tools |
|---|---|
| Stellen | `search_jobs` (BA), `get_job_details`, `search_arbeitnow`, `get_ats_jobs`, `commoncrawl_lookup` |
| Berufe | `search_occupation`, `get_occupation`, `get_tasks`, `get_skills`, `crosswalk`, `get_role_context` |
| Gehalt | `get_salary` (Entgeltatlas), `adzuna_salary` (optional) |
| Automatisierung | `find_automation_signals`, `record_extraction` |
| Gedächtnis | `remember`, `search_knowledge`, `get_changes`, `get_history`, `knowledge_stats`, `graph_neighbors` |
| Daten und Betrieb | `import_reference_data`, `export_knowledge`, `check_sources` |

Dazu kommt der Prompt `rollen_analyse(rolle, ort)`. Er führt durch den Ablauf Rolle → Aufgaben → Automatisierung. Die vollständige Referenz steht in [docs/archivy/WorkMCP/910004-Tools-Referenz.md](docs/archivy/WorkMCP/910004-Tools-Referenz.md).

## Datenquellen

Alle integrierten Quellen sind kostenlos. Kostenpflichtige APIs wie Apify werden bewusst nicht genutzt.

| Quelle | Zugang | Hinweise zu Lizenz und Bedingungen (selbst prüfen!) |
|---|---|---|
| BA-Jobsuche, BERUFENET, Entgeltatlas | JSON-Backends der BA-Web-Apps, öffentliche Client-IDs | **Keine offiziell angebotene API**, dokumentiert von [bundesAPI](https://github.com/bundesAPI). Endpunkte können sich ändern. Entgeltatlas: „Statistik der Bundesagentur für Arbeit“ als Quelle angeben. |
| ESCO | Web-API der EU-Kommission | Nutzungsbedingungen des ESCO-Portals, Quellenangabe |
| O*NET | Datenbank-Download (Text) | **CC BY 4.0**, Namensnennung von USDOL/ETA erforderlich; O*NET® ist eine Marke von USDOL/ETA |
| KldB 2010, Umsteigeschlüssel KldB→ISCO-08 | Datei der BA-Statistik (Import) | Quellenangabe Bundesagentur für Arbeit |
| ESCO↔O*NET-Crosswalk | Datei vom ESCO-Portal oder O*NET (Import) | Bedingungen der Herausgeber |
| Arbeitnow | kostenlose API ohne Key | Bedingungen von Arbeitnow |
| ATS-Job-Boards | öffentliche Karriereseiten-Feeds ohne Login | robots.txt und Bedingungen der Arbeitgeber und ATS-Anbieter, schonend abrufen |
| Adzuna (optional) | kostenloser Developer-Key | Adzuna-API-Bedingungen, u. a. Verlinkung über `redirect_url` |
| Hacker News | Algolia-Such-API | Inhalte gehören den Verfassenden |
| Common Crawl | URL-Index und WARC-Abruf | Common Crawl Terms of Use; Urheberrecht der Seitenbetreiber |

Nicht integriert sind LinkedIn, Indeed, StepStone und XING: keine Lese-API, Scraping verbieten die AGB. Ebenso Interamt (keine Lese-API) und Apify (kostenpflichtig). Die Einordnung steht im [Faktencheck](FAKTENCHECK.md).

**Datenschutz:** Stellenanzeigen können personenbezogene Daten enthalten. Felder mit Kontaktpersonen, Telefonnummern, E-Mail-Adressen und Bewerbungsangaben werden **vor dem Speichern entfernt**. Mit `WORKMCP_STORE_PERSONAL_DATA=1` lässt sich das abschalten; dann ist DSGVO-Konformität selbst sicherzustellen.

## Referenzdaten importieren

```text
import_reference_data('onet')                                  # automatisch neueste Version, CC BY 4.0
import_reference_data('kldb', quelle='/pfad/kldb2010.xlsx')    # KldB-2010-Systematik (Fassung 2020)
import_reference_data('kldb_isco', quelle='/pfad/umsteiger.xlsx')
import_reference_data('esco_onet', quelle='/pfad/esco_onet.csv')
```

Herkunft der Dateien:

- **KldB-Systematik:** [BA-Statistik → KldB 2010 Fassung 2020 → Systematik-Verzeichnisse](https://statistik.arbeitsagentur.de/DE/Navigation/Grundlagen/Klassifikationen/Klassifikation-der-Berufe/KldB2010-Fassung2020/Systematik-Verzeichnisse/Systematik-Verzeichnisse-Nav.html).
- **Umsteigeschlüssel KldB→ISCO-08:** [BA-Statistik → Arbeitsmittel](https://statistik.arbeitsagentur.de/DE/Navigation/Grundlagen/Klassifikationen/Klassifikation-der-Berufe/KldB2010-Fassung2020/Arbeitsmittel/Arbeitsmittel-Nav.html).
- **ESCO↔O*NET:** [ESCO „Other crosswalks“](https://esco.ec.europa.eu/en/use-esco/other-crosswalks) oder [O*NET Crosswalk Files](https://www.onetcenter.org/crosswalks.html).

Die Spalten werden an Kopfzeilen und Wertformen erkannt, Titelzeilen stören nicht. Wiederholte Importe melden neue, geänderte und **entfallene** Einträge, etwa zwischen zwei O*NET-Releases.

## Konfiguration

| Variable | Standard | Bedeutung |
|---|---|---|
| `WORKMCP_DB` | `~/.workmcp/knowledge.db` | Wissensdatenbank (SQLite) |
| `WORKMCP_OFFLINE` | `0` | nur Gedächtnis, keine Netzzugriffe |
| `WORKMCP_TTL_JOBS_HOURS` / `_DETAILS_HOURS` / `_SIGNALS_HOURS` | 6 / 24 / 24 | Gültigkeitsdauer für Stellen, Details und Signale |
| `WORKMCP_TTL_REFERENCE_DAYS` | 30 | Gültigkeitsdauer für Berufe und Referenzdaten |
| `WORKMCP_LANGUAGE` | `de` | Sprache für ESCO |
| `WORKMCP_ESCO_VERSION` | – | z. B. `v1.2.1` (sonst Standard der API) |
| `WORKMCP_ONET_VERSION` | automatisch | z. B. `31_0` |
| `WORKMCP_ADZUNA_APP_ID` / `_APP_KEY` | – | aktiviert Adzuna (kostenloser Key) |
| `WORKMCP_STORE_PERSONAL_DATA` | `0` | Kontaktfelder aus Stellenanzeigen speichern |
| `WORKMCP_KLDB_SOURCE`, `_KLDB_ISCO_SOURCE`, `_ESCO_ONET_SOURCE` | – | Standardquellen für den Import |
| `WORKMCP_ARCHIVY_DIR` | – | Archivy-Datenverzeichnis als Standardziel von `export_knowledge('archivy')` |
| `WORKMCP_ALLOWED_HOSTS` | – | erlaubte Host-Header für streamable-http, kommagetrennt (wie `--allowed-host`) |
| `WORKMCP_BA_*`, `WORKMCP_ESCO_BASE`, `WORKMCP_HN_BASE` … | siehe `src/workmcp/config.py` | Endpunkte und Client-IDs überschreiben |

## Graph-Modell

- **Knoten:** `Beruf`, `Klassifikation` (KldB/ISCO, Hierarchie als Jobfamilien), `Aufgabe`, `Skill`, `Stellenanzeige`, `Arbeitgeber`, `Branche`, `Region`, `Automatisierung`, `Entgelt`.
- **Kanten:** `STELLT_AN`, `ERFORDERT`, `TEIL_VON` (mit O*NET Core/Supplemental), `AUTOMATISIERBAR_DURCH` (Bewertung, Anteil an der Wochenarbeitszeit), `GEHOERT_ZU`, `FUER_BERUF`, `IN_REGION`, `AUSGESCHRIEBEN_VON`, `KLASSIFIZIERT_ALS`, `ENTSPRICHT`, `UNTERGRUPPE_VON`, `HAT_ENTGELT`.

Details stehen in [docs/archivy/WorkMCP/910007-Job-Graph-Modell.md](docs/archivy/WorkMCP/910007-Job-Graph-Modell.md). Für Neo4j: `export_knowledge('cypher')`, dann `cypher-shell < graph.cypher`.

## Dokumentation

- [Landingpage](docs/index.html), für GitHub Pages aus dem Ordner `/docs` gedacht.
- [Archivy-Dokumentation](docs/archivy/LIESMICH.md): Notizen mit YAML-Front-Matter, direkt in eine [Archivy](https://github.com/archivy/archivy)-Wissensdatenbank kopierbar. `export_knowledge('archivy')` schreibt auch die gemerkten Berufe als verlinkte Archivy-Notizen.
- [Faktencheck](FAKTENCHECK.md) der zugrunde liegenden Recherche.

## Bekannte Grenzen

- Die Clients sind gegen dokumentierte Antwortformate getestet (bundesAPI-OpenAPI, ESCO-HAL, O*NET-Dateilayout, live verifizierte ATS-Referenz). Gegen die **Live-APIs konnten sie in der Entwicklungsumgebung nicht laufen**, deren Netzwerk-Policy die Hosts sperrt. Vor dem Produktiveinsatz `check_sources` ausführen und Ergebnisse stichprobenartig prüfen.
- Die Aufgaben-Extraktion aus BERUFENET ist heuristisch (Abschnitte „Aufgaben und Tätigkeiten“). Die Rohantwort wird immer vollständig gespeichert.
- O*NET-Aufgaben sind englisch und beschreiben US-Berufe. Für die Zuordnung zu deutschen Berufen werden ESCO-URIs und der ESCO↔O*NET-Crosswalk empfohlen.
- `search_arbeitnow` filtert lokal, weil die API keine Suchparameter für Begriff und Ort hat.

## Entwicklung

```bash
uv sync --extra dev
```

```bash
uv run pytest
```

```bash
uv run ruff check src tests && uv run mypy src
```

## Lizenz

MIT, siehe [LICENSE](LICENSE). Die abgerufenen Daten unterliegen den Bedingungen ihrer jeweiligen Quellen.
