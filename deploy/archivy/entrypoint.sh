#!/bin/sh
# Startet Archivy ohne interaktiven Assistenten:
#  1. config.yml anlegen (falls nicht vorhanden): Host 0.0.0.0, Daten unter $ARCHIVY_INTERNAL_DIR_PATH, ripgrep-Suche
#  2. WorkMCP-Dokumentation in den Ordner data/WorkMCP kopieren (bei jedem Start aktualisiert)
#  3. Admin-Benutzer anlegen, falls ARCHIVY_ADMIN_USER/ARCHIVY_ADMIN_PASSWORD gesetzt sind
set -eu

BASE="${ARCHIVY_INTERNAL_DIR_PATH:-/archivy}"
CONF="$BASE/config.yml"
DOCS_SRC="${WORKMCP_DOCS_DIR:-/opt/workmcp-docs/WorkMCP}"
mkdir -p "$BASE/data/WorkMCP"

if [ ! -f "$CONF" ]; then
  cat > "$CONF" <<EOF
HOST: 0.0.0.0
PORT: 5000
USER_DIR: $BASE
SITE_TITLE: ${ARCHIVY_SITE_TITLE:-WorkMCP Wissen}
SEARCH_CONF:
  enabled: 1
  engine: ripgrep
EOF
  echo "archivy-entrypoint: $CONF angelegt"
fi

if [ -d "$DOCS_SRC" ]; then
  # Doku-Notizen (IDs 910001–910099) werden überschrieben; eigene Notizen bitte außerhalb dieser IDs anlegen
  cp -f "$DOCS_SRC"/*.md "$BASE/data/WorkMCP/"
  echo "archivy-entrypoint: WorkMCP-Dokumentation nach $BASE/data/WorkMCP kopiert"
fi

if [ -n "${ARCHIVY_ADMIN_USER:-}" ] && [ -n "${ARCHIVY_ADMIN_PASSWORD:-}" ]; then
  archivy create-admin "$ARCHIVY_ADMIN_USER" --password "$ARCHIVY_ADMIN_PASSWORD" || true
fi

exec archivy run
