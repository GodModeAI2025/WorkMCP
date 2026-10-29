# Archivy (https://github.com/archivy/archivy) mit vorinstallierter WorkMCP-Dokumentation.
# Archivy 1.7.7 pinnt ältere Abhängigkeiten, daher Python 3.11. Build-Kontext: Repository-Wurzel.
ARG PYTHON_IMAGE=python:3.11-slim
FROM ${PYTHON_IMAGE}

ARG ARCHIVY_VERSION=1.7.7
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ARCHIVY_INTERNAL_DIR_PATH=/archivy

# ripgrep (Debian-Paket): Suche, Tags und Links in Archivy; abschaltbar mit --build-arg WITH_RIPGREP=0.
# setuptools<81: Archivy importiert pkg_resources.
ARG WITH_RIPGREP=1
RUN if [ "$WITH_RIPGREP" = "1" ]; then \
        apt-get update && apt-get install -y --no-install-recommends ripgrep && rm -rf /var/lib/apt/lists/*; \
    fi \
    && pip install --no-cache-dir "setuptools<81" "archivy==${ARCHIVY_VERSION}"

COPY deploy/archivy/entrypoint.sh /usr/local/bin/archivy-entrypoint
COPY docs/archivy/WorkMCP /opt/workmcp-docs/WorkMCP
RUN chmod +x /usr/local/bin/archivy-entrypoint

VOLUME ["/archivy"]
EXPOSE 5000
ENTRYPOINT ["archivy-entrypoint"]
