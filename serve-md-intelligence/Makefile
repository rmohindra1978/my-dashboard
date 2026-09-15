PYTHON ?= python3
VENV ?= .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

.PHONY: setup setup-backend setup-frontend data data-sample dev api web test test-backend test-frontend lint fmt docs clean

setup: setup-backend setup-frontend

setup-backend:
	test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

setup-frontend:
	cd frontend && npm install

## Build the full national warehouse from public sources (cached under data/raw)
data:
	$(PY) -m pipelines.build --all

## Build a small sample warehouse from checked-in fixtures (fast; used by tests and local dev)
data-sample:
	$(PY) -m pipelines.build --sample

api:
	$(VENV)/bin/uvicorn backend.app.main:app --reload --port 8000

web:
	cd frontend && npm run dev

## Run API and frontend together (Ctrl-C stops both)
dev:
	$(MAKE) -j2 api web

test: test-backend test-frontend

test-backend:
	$(VENV)/bin/pytest --cov --cov-report=term-missing

test-frontend:
	cd frontend && npm run test -- --run

lint:
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	cd frontend && npm run lint && npm run typecheck

fmt:
	$(VENV)/bin/ruff format .
	$(VENV)/bin/ruff check --fix .

## Regenerate docs/data-dictionary.md from config/metrics.yaml
docs:
	$(PY) -m backend.app.tools.gen_data_dictionary

clean:
	rm -rf data/warehouse/*.duckdb data/warehouse/*.wal
