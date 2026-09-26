.PHONY: setup install up down dev lint test test-ci demo demo-laptop eval clean

# Interpreter used by the Python targets. Defaults to `python3` so that an activated
# virtualenv wins — override explicitly for a pinned interpreter:
#   make demo PYTHON=python3.10
# CI runs the suite on 3.10, 3.11 and 3.12 (see .github/workflows/ci.yml).
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

# Strict variant for CI: same suite, but a skip or a shrunken count is a failure.
# `make test` cannot see either — a module-level importorskip once hid 14 tests behind
# "1 skipped" with exit code 0.
test-ci:
	$(PYTHON) scripts/check_no_pytest_skips.py

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
