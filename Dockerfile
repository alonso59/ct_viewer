# syntax=docker/dockerfile:1
# Radiology Workbench: one image for Docker and udocker (ADR-0007, docs/ops/DEPLOYMENT.md).
#   make image   # = docker build -t radiology-workbench:<backend/pyproject.toml version> .
# Stages: web (node:22-slim) -> build (python:3.12-slim + gcc) -> runtime (python:3.12-slim).

FROM node:22-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS build
# gcc + git only here: the [radiomics] extra builds PyRadiomics from a pinned commit (ADR-0006).
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev git \
 && rm -rf /var/lib/apt/lists/*
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
# Dependencies only (the app source is copied into the runtime stage), so code edits keep this layer.
COPY backend/pyproject.toml /src/backend/pyproject.toml
RUN mkdir /src/backend/app && touch /src/backend/app/__init__.py \
 && pip install "/src/backend[radiomics]" \
 && pip uninstall -y radiology-workbench \
 && find /opt/venv -depth -name __pycache__ -type d -exec rm -rf {} +

FROM python:3.12-slim AS runtime
COPY --from=build /opt/venv /opt/venv
COPY backend/app /app/backend/app
COPY backend/tools /app/backend/tools
COPY scripts/container_app.py /app/scripts/container_app.py
COPY --from=web /src/frontend/dist /app/static
# OPS-02: no fixed UID; any user may write /workspace when it is not mounted, HOME is /tmp.
RUN mkdir -m 1777 /workspace
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/backend \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    CONTAINER_MODE=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    WORKSPACE_ROOT=/workspace \
    STATIC_ROOT=/app/static
# ADR-0006: the pinned PyRadiomics must pass the IBSI digital-phantom smoke in this Linux image.
RUN python -m tools.spikes.ibsi_phantom_smoke
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/v1/health' % os.environ.get('PORT', '8000'), timeout=4)"]
CMD ["python", "/app/scripts/container_app.py"]
