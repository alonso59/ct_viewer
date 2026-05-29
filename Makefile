SHELL := /bin/bash

PROJECT_ROOT := /home/alonso/Documents/radio-ccrcc/radioccrcc-webui
UDOCKER := /home/alonso/anaconda3/envs/ccrcc/bin/python $(PROJECT_ROOT)/udocker.py
SETUP_DOC := $(PROJECT_ROOT)/docs/SETUP_PREREQUISITES.md

.PHONY: setup setup-prereqs setup-udocker setup-node install-backend dev-backend dev-frontend build-frontend compose-build compose-up compose-down compose-logs run build-portable

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
	@if $(UDOCKER) images -l 2>/dev/null | awk '{print $$1}' | grep -Fxq "node:20-slim"; then \
		echo "Node image already present: node:20-slim"; \
	else \
		$(UDOCKER) pull node:20-slim; \
	fi
	@if $(UDOCKER) ps | awk '{print $$1}' | grep -Fxq "radio-node"; then \
		echo "Container already exists: radio-node"; \
	else \
		$(UDOCKER) create --name=radio-node node:20-slim; \
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

# Standalone mode: opens browser automatically, supports --data-dir and --port
# Usage: make run  OR  make run DATA_DIR=/path/to/dataset PORT=8000
# Uses whatever python is active in the current shell (no conda dependency).
run:
	set -a && [ ! -f .env ] || source .env && set +a && \
	cd backend && \
	python -m app $(if $(DATA_DIR),--data-dir "$(DATA_DIR)",) $(if $(PORT),--port $(PORT),)

dev-frontend:
	$(UDOCKER) run --hostenv \
		-v /home/alonso/Documents/radio-ccrcc/radioccrcc-webui/frontend:/app \
		-p 5173:5173 \
		radio-node \
		bash -c "cd /app && npm install && npm run dev -- --host 0.0.0.0 --port 5173"

build-frontend:
	$(UDOCKER) run --hostenv \
		-v /home/alonso/Documents/radio-ccrcc/radioccrcc-webui/frontend:/app \
		radio-node \
		bash -c "cd /app && npm install && npm run build"

compose-build:
	docker compose build

compose-up:
	docker compose up -d --build

compose-down:
	docker compose down

compose-logs:
	docker compose logs -f

# Portable executable build (Linux/macOS)
# Requires: npm on PATH + python with pyinstaller
build-portable:
	chmod +x build-portable.sh && ./build-portable.sh $(if $(SKIP_FRONTEND),--skip-frontend,)
