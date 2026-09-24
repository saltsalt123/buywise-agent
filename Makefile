.PHONY: setup install up down dev lint test demo demo-laptop eval clean

# Interpreter used by the Python targets. The project is developed and tested on
# Python 3.10; other 3.10+ versions are allowed by pyproject but are not covered
# by CI. Defaults to `python3` so that an activated virtualenv wins — override
# explicitly for a pinned interpreter:  make demo PYTHON=python3.10
PYTHON ?= python3

# ── Setup ────────────────────────────────

setup:
	$(PYTHON) -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
	@echo "Run: source .venv/bin/activate"

install:
	pip install -e ".[dev]"

# ── Docker ───────────────────────────────

up:
	docker compose up --build -d

down:
	docker compose down

# ── Dev ──────────────────────────────────

dev:
	uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload

lint:
	$(PYTHON) -m ruff check agent/ ingestion/ retrieval/ apps/ eval/ scripts/ tests/

test:
	$(PYTHON) -m pytest -q --tb=short

# ── Demo ─────────────────────────────────

demo:
	$(PYTHON) scripts/demo.py

demo-laptop:
	$(PYTHON) scripts/demo.py laptop

# ── Eval ─────────────────────────────────

eval:
	$(PYTHON) -m eval.run_all --output eval/reports/latest.md

# ── Clean ────────────────────────────────

clean:
	rm -rf data/uploads/* data/cache/* __pycache__ */__pycache__
