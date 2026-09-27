# Radiology Workbench v3: dev targets (docs/ops/DEV_ENV.md)
# The repo path may contain spaces: recipes use relative paths and quote $(CURDIR).

SHELL := /bin/bash
.DEFAULT_GOAL := help

HOST ?= 127.0.0.1
# Image tag = the backend package version (single source: backend/pyproject.toml).
VERSION ?= $(shell sed -n 's/^version = "\(.*\)"/\1/p' backend/pyproject.toml)
FIXTURES ?= .fixtures/synthetic
PYTHON_VERSION ?= 3.12
# Python env: a venv by default; on remote servers pass VENV=$$CONDA_PREFIX (conda env `rw`).
VENV ?= backend/.venv
BPY := $(if $(filter /%,$(VENV)),$(VENV),../$(VENV))/bin/python

# Node runtime: native | docker | udocker (native if `node` exists, else udocker; AGENTS R4).
# Docs site tools (dev-only, pinned; never in pyproject.toml, package.json or the image; R5).
DOCS_TOOLS ?= uvx --from sphinx==9.1.0 --with myst-parser==5.1.0 --with furo==2025.12.19

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
        gen-api api-types bundle-size lint fix typecheck test reqs check e2e e2e-one e2e-servers record-mock \
        image udocker-run container-smoke docs docs-srs trace

help: ## List targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'
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

record-mock: ## TST-04: re-record the mock API (frontend/src/api/mock/recorded.json) from the backend on the fixtures
	cd backend && $(BPY) -m tools.record_mock

gen-api: ## Write the OpenAPI snapshot and regenerate the frontend API types (FE-03, BE-10)
	cd backend && $(BPY) -m tools.openapi_snapshot
	$(NODE) npm run gen:api

api-types: ## FE-03 gate: schema.d.ts equals the types generated from the current OpenAPI
	mkdir -p frontend/.vite/api-types
	cd backend && $(BPY) -m tools.openapi_snapshot --frontend ../frontend/.vite/api-types/openapi.json
	$(NODE) npx openapi-typescript .vite/api-types/openapi.json -o .vite/api-types/schema.d.ts
	@diff -q frontend/src/api/schema.d.ts frontend/.vite/api-types/schema.d.ts >/dev/null \
	  || { echo "api-types: frontend/src/api/schema.d.ts is stale; run make gen-api (FE-03)"; exit 1; }
	@echo "api-types: schema.d.ts up to date"

lint: ## ruff + eslint
	cd backend && $(BPY) -m ruff check . ../scripts ../plugins ../docs/_sphinx && $(BPY) -m ruff format --check . ../scripts ../plugins ../docs/_sphinx
	$(NODE) npm run lint

typecheck: ## mypy (strict) + tsc (strict)
	cd backend && $(BPY) -m mypy && $(BPY) -m mypy --strict ../scripts/*.py
	$(NODE) npm run typecheck

test: ## Unit tests: pytest + vitest
	cd backend && $(BPY) -m pytest
	$(NODE) npm test

bundle-size: ## NFR-07 gate: production build, initial JS (entry + modulepreload, gzip -9) <= 300 KiB (REL-04)
	$(NODE) npx vite build --outDir .vite/bundle --emptyOutDir --logLevel error
	$(NODE) node scripts/bundle-size.mjs .vite/bundle --budget-kib 300

reqs: ## Requirement tables check (SRS §1.5; stdlib, < 1 s)
	python3 docs/_sphinx/reqs.py check

check: lint typecheck test api-types bundle-size reqs ## Lint, type check, unit tests, API types, bundle budget and the requirement check (CI gate)

e2e: ## Playwright, both browsers (SPEC=name PROJECT=chromium|firefox narrow it; `npx playwright install` once)
	$(NODE) npx playwright test $(if $(SPEC),e2e/$(SPEC).spec.ts,) $(if $(PROJECT),--project=$(PROJECT),)

e2e-one: ## One spec in one browser: make e2e-one SPEC=g1-open [PROJECT=firefox] [E2E_REUSE=1]
	@test -n "$(SPEC)" || { echo "e2e-one: SPEC=<spec name without .spec.ts> is required"; exit 2; }
	$(NODE) npx playwright test e2e/$(SPEC).spec.ts --project=$(or $(PROJECT),chromium)

e2e-servers: ## E2E backend + web server in the foreground, for E2E_REUSE=1 runs (Ctrl-C stops)
	$(NODE) node e2e/serve.ts

fix: ## Autofix: ruff check --fix, ruff format, eslint --fix
	cd backend && $(BPY) -m ruff check --fix . ../scripts ../plugins ../docs/_sphinx && $(BPY) -m ruff format . ../scripts ../plugins ../docs/_sphinx
	$(NODE) npx eslint --fix .

image: ## Build the OCI image radiology-workbench:VERSION (Docker; add PLATFORM=linux/amd64 for the server)
	docker build $(if $(PLATFORM),--platform $(PLATFORM),) -t radiology-workbench:$(VERSION) .

container-smoke: ## TST-10 against the built image (Docker)
	scripts/container-smoke.sh

udocker-run: ## Run the image under udocker from .env (OPS-09)
	scripts/udocker-run.sh

docs: ## Docs site (Sphinx + MyST, warnings are errors) into build/docs/
	$(DOCS_TOOLS) sphinx-build -E -W --keep-going -q -b html -c docs/_sphinx docs build/docs
	@echo "docs: open build/docs/index.html"

docs-srs: ## SRS review table + counts into build/docs-srs/ (git-ignored)
	python3 docs/_sphinx/reqs.py srs build/docs-srs

trace: ## Requirement -> code/test citations into build/trace/ (a report, not a gate; AUD-A4-01)
	python3 docs/_sphinx/reqs.py trace build/trace
