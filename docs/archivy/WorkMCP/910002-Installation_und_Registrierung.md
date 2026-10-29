---
date: 10-29-26
id: 910002
modified_at: 10/29/26 09:00
path: "WorkMCP"
tags:
- "workmcp"
- "doku"
- "installation"
title: "Installation und Registrierung"
type: note
---

# Installation und Registrierung

Voraussetzungen: Python ≥ 3.10 und [uv](https://docs.astral.sh/uv/). Das MCP-SDK `mcp` 2.x wird automatisch installiert.

## Claude Code (stdio)

```bash
claude mcp add workmcp -- uvx --from git+https://github.com/GodModeAI2025/WorkMCP workmcp
```

Mit Umgebungsvariablen (eigener Speicherort, Adzuna-Key):

```bash
claude mcp add --transport stdio workmcp --env WORKMCP_DB=$HOME/.workmcp/knowledge.db --env WORKMCP_ADZUNA_APP_ID=… --env WORKMCP_ADZUNA_APP_KEY=… -- uvx --from git+https://github.com/GodModeAI2025/WorkMCP workmcp
```

Aus einem lokalen Klon:

```bash
claude mcp add workmcp -- uv --directory /pfad/zu/WorkMCP run workmcp
```

## Zentraler Betrieb (Streamable HTTP)

```bash
workmcp --transport streamable-http --host 0.0.0.0 --port 8000 --db /srv/workmcp/knowledge.db
```

Clients verbinden sich mit `http://<host>:8000/mcp`, in Claude Code so:

```bash
claude mcp add --transport http workmcp http://<host>:8000/mcp
```

Der HTTP-Modus bringt **keine eigene Authentifizierung** mit. Nur intern betreiben oder hinter einem Reverse Proxy mit Zugangsschutz. Alle Clients teilen sich dann ein gemeinsames Gedächtnis.

## Docker Compose: WorkMCP und Archivy

```bash
cp .env.example .env
```

```bash
docker compose up -d --build
```

| Dienst | Adresse | Inhalt |
|---|---|---|
| Archivy | http://localhost:5000 | Wissensdatenbank mit dieser Doku (Ordner WorkMCP), Login aus `.env` |
| WorkMCP | http://localhost:8000/mcp | MCP-Server (Streamable HTTP), Gedächtnis im Volume `workmcp-data` |

`export_knowledge('archivy')` schreibt ohne weitere Angaben in den Archivy-Ordner WorkMCP, siehe [[Archivy-Export|910010]]. Beide Ports sind nur lokal gebunden, WorkMCP prüft zusätzlich den Host-Header (`WORKMCP_ALLOWED_HOSTS`, Standard `localhost:*`).

## Weitere Harnesses

- **Projektdatei `.mcp.json`:** `command: "uvx"`, `args: ["--from", "git+https://github.com/GodModeAI2025/WorkMCP", "workmcp"]`.
- **OpenCode (`opencode.json`):** unter `mcp.workmcp` mit `type: "local"` und `command: ["uvx", "--from", "git+…", "workmcp"]`.
- **Andere MCP-fähige Harnesses:** über stdio oder die Streamable-HTTP-URL.

## Kommandozeile

| Option | Bedeutung |
|---|---|
| `--transport stdio\|streamable-http` | Transport (Standard stdio) |
| `--host`, `--port` | für streamable-http (Standard 127.0.0.1:8000) |
| `--allowed-host HOST[:PORT]` | erlaubter Host-Header (mehrfach, Standard aus `WORKMCP_ALLOWED_HOSTS`), aktiviert den DNS-Rebinding-Schutz auch bei `--host 0.0.0.0` |
| `--db PFAD` | Wissensdatenbank (überschreibt `WORKMCP_DB`) |
| `--offline` | nur Gedächtnis, keine Netzzugriffe |

## Erste Schritte

1. `check_sources`: Sind alle Quellen erreichbar?
2. `import_reference_data('onet')`: O*NET-Aufgaben laden (einmalig, danach bei neuen Releases wiederholen).
3. Optional KldB-Systematik, Umsteigeschlüssel und ESCO↔O*NET-Crosswalk importieren, siehe [[Referenzdaten importieren|910006]].
4. `get_role_context('Buchhalter', ort='Berlin')`.

Zurück zum [[WorkMCP Überblick|910001]].
