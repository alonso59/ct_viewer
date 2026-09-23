SHELL := /bin/bash

PROJECT_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
UDOCKER := /home/alonso/anaconda3/envs/ccrcc/bin/python $(PROJECT_ROOT)/udocker.py
SETUP_DOC := $(PROJECT_ROOT)/docs/SETUP_PREREQUISITES.md
NODE_IMAGE := node:22-slim
NODE_CONTAINER := radio-node22

.PHONY: setup setup-prereqs setup-udocker setup-node install-backend dev-backend dev-frontend build-frontend compose-build compose-up compose-down compose-logs

setup: setup-prereqs setup-udocker setup-node install-backend

setup-prereqs:
	@echo "Checking repository prerequisites..."
	@if [ -f "/home/alonso/anaconda3/etc/profile.d/conda.sh" ]; then \
		echo "OK: conda base installation found"; \
	else \
		echo "ERROR: conda not found at /home/alonso/anaconda3"; \
		echo "See setup guide: $(SETUP_DOC)"; \
		exit 1; \
	fi
	@if [ -f "$(PROJECT_ROOT)/udocker.py" ] && [ -f "$(PROJECT_ROOT)/udocker-1.3.17/udocker/maincmd.py" ]; then \
		echo "OK: vendored udocker runtime found"; \
	else \
		echo "ERROR: vendored udocker runtime not found under $(PROJECT_ROOT)/udocker-1.3.17"; \
		echo "See setup guide: $(SETUP_DOC)"; \
		exit 1; \
	fi
	@if command -v docker >/dev/null 2>&1; then \
		echo "OK: docker CLI available (compose targets enabled)"; \
	else \
		echo "INFO: docker CLI not found (this is fine for remote dev mode)."; \
		echo "      For optional Docker install steps, see: $(SETUP_DOC)"; \
	fi

setup-udocker:
	@echo "Initializing local udocker runtime..."
	@$(UDOCKER) version >/dev/null

setup-node:
	@if $(UDOCKER) images -l 2>/dev/null | awk '{print $$1}' | grep -Fxq "$(NODE_IMAGE)"; then \
		echo "Node image already present: $(NODE_IMAGE)"; \
	else \
		$(UDOCKER) pull $(NODE_IMAGE); \
	fi
	@if $(UDOCKER) ps | awk '{print $$1}' | grep -Fxq "$(NODE_CONTAINER)"; then \
		echo "Container already exists: $(NODE_CONTAINER)"; \
	else \
		$(UDOCKER) create --name=$(NODE_CONTAINER) $(NODE_IMAGE); \
	fi

install-backend:
	source /home/alonso/anaconda3/etc/profile.d/conda.sh && \
	conda activate ccrcc && \
	cd backend && \
	pip install -r requirements.txt

dev-backend:
	source /home/alonso/anaconda3/etc/profile.d/conda.sh && \
	conda activate ccrcc && \
	set -a && \
	[ ! -f .env ] || source .env && \
	set +a && \
	cd backend && \
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	$(UDOCKER) run --hostenv \
		-v $(PROJECT_ROOT)/frontend:/app \
		-p 5173:5173 \
		$(NODE_CONTAINER) \
		bash -c "cd /app && npm install && npm run dev -- --host 0.0.0.0 --port 5173"

build-frontend:
	$(UDOCKER) run --hostenv \
		-v $(PROJECT_ROOT)/frontend:/app \
		$(NODE_CONTAINER) \
		bash -c "cd /app && npm install && npm run build"

compose-build:
	docker compose build

compose-up:
	docker compose up -d --build

compose-down:
	docker compose down

compose-logs:
	docker compose logs -f
