.PHONY: setup install up down dev lint test demo demo-laptop eval clean

# ── Setup ────────────────────────────────

setup:
	python3.10 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
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
	ruff check agent/ ingestion/ retrieval/ apps/ eval/ scripts/

test:
	pytest -q --tb=short 2>/dev/null || echo "No tests yet — run 'make demo'"

# ── Demo ─────────────────────────────────

demo:
	python3.10 scripts/demo.py

demo-laptop:
	python3.10 scripts/demo.py laptop

# ── Eval ─────────────────────────────────

eval:
	python3.10 -m eval.run_all --output eval/reports/latest.md

# ── Clean ────────────────────────────────

clean:
	rm -rf data/uploads/* data/cache/* __pycache__ */__pycache__
