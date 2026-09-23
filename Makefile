# Radiology Workbench v3: dev targets (docs/ops/DEV_ENV.md)
# The repo path may contain spaces: recipes use relative paths and quote $(CURDIR).

SHELL := /bin/bash
.DEFAULT_GOAL := help

HOST ?= 127.0.0.1
FIXTURES ?= .fixtures/synthetic
PYTHON_VERSION ?= 3.12
# Python env: a venv by default; on remote servers pass VENV=$$CONDA_PREFIX (conda env `rw`).
VENV ?= backend/.venv
BPY := $(if $(filter /%,$(VENV)),$(VENV),../$(VENV))/bin/python

# Node runtime: native | docker | udocker (native if `node` exists, else udocker; AGENTS R4).
RUNTIME ?= $(if $(shell command -v node 2>/dev/null),native,udocker)
NODE_IMAGE ?= node:22-slim
UDOCKER_NODE ?= rw-node
ifeq ($(RUNTIME),native)
  NODE := cd frontend &&
else ifeq ($(RUNTIME),docker)
  NODE := docker run --rm -v "$(CURDIR)/frontend:/app" -w /app -e VITE_HOST=0.0.0.0 -p 5173:5173 $(NODE_IMAGE)
else ifeq ($(RUNTIME),udocker)
  NODE := python3 udocker.py run --hostenv --volume="$(CURDIR)/frontend:/app" --workdir=/app $(UDOCKER_NODE)
else
  $(error RUNTIME must be native, docker or udocker)
endif

.PHONY: help setup setup-backend setup-frontend setup-node dev-backend dev-frontend fixtures \
        gen-api lint typecheck test check e2e image udocker-run

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'
	@echo "  RUNTIME=$(RUNTIME)  VENV=$(VENV)"

setup: setup-backend setup-frontend ## Create the Python env and install both sides

setup-backend: ## Python 3.12 env + backend[dev] (override PYTHON_VERSION)
	@if [ ! -x "$(VENV)/bin/python" ]; then \
	  if command -v uv >/dev/null; then uv venv --python $(PYTHON_VERSION) "$(VENV)"; \
	  else python$(PYTHON_VERSION) -m venv "$(VENV)"; fi; fi
	@if command -v uv >/dev/null; then VIRTUAL_ENV="$(VENV)" uv pip install -e 'backend[dev]'; \
	else "$(VENV)/bin/python" -m pip install -e 'backend[dev]'; fi

setup-frontend: ## Install frontend deps from the lockfile
	$(NODE) npm ci

setup-node: ## One-time: create the udocker Node container (remote servers)
	python3 udocker.py pull $(NODE_IMAGE)
	python3 udocker.py create --name=$(UDOCKER_NODE) $(NODE_IMAGE)

dev-backend: ## API with reload on HOST (default 127.0.0.1):8000
	cd backend && WORKSPACE_ROOT=../.workspace $(BPY) -m uvicorn app.main:app --reload --host $(HOST) --port 8000

dev-frontend: ## Vite dev server on 5173 (proxies /api -> 8000)
	$(NODE) npm run dev

fixtures: ## Generate the synthetic dataset into FIXTURES (TST-11)
	cd backend && $(BPY) -m tools.make_fixtures --out "../$(FIXTURES)"

gen-api: ## Regenerate frontend API types from OpenAPI (FE-03)
	cd backend && $(BPY) -c "import json; from app.main import app; print(json.dumps(app.openapi(), indent=1))" > ../frontend/src/api/openapi.json
	$(NODE) npm run gen:api

lint: ## ruff + eslint
	cd backend && $(BPY) -m ruff check . && $(BPY) -m ruff format --check .
	$(NODE) npm run lint

typecheck: ## mypy (strict) + tsc (strict)
	cd backend && $(BPY) -m mypy
	$(NODE) npm run typecheck

test: ## Unit tests: pytest + vitest
	cd backend && $(BPY) -m pytest
	$(NODE) npm test

check: lint typecheck test ## Lint, type check and unit tests for both sides (CI gate)

e2e: ## Playwright (needs `npx playwright install` once)
	$(NODE) npm run e2e

image: ## Build the OCI image (lane P7)
	@echo "Not implemented yet: lane P7 (docs/ops/DEPLOYMENT.md)"; exit 1

udocker-run: ## Run the image under udocker (lane P7)
	@echo "Not implemented yet: lane P7, scripts/udocker-run.sh (OPS-09)"; exit 1
