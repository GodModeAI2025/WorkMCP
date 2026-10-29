# WorkMCP als zentraler MCP-Server (Streamable HTTP).
# Basis-Image überschreibbar, z. B. --build-arg PYTHON_IMAGE=mirror.gcr.io/library/python:3.13-slim
ARG PYTHON_IMAGE=python:3.13-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WORKMCP_DB=/data/knowledge.db

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && mkdir -p /data

VOLUME ["/data"]
EXPOSE 8000
CMD ["workmcp", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
