.PHONY: setup up down migrate test lint typecheck dataset eval-dev eval eval-smoke \
        audit-verify demo chaos seed-examples clean

PYTHON := .venv/bin/python
UV := uv

setup:
	$(UV) venv --python 3.12
	$(UV) pip install -e ".[dev]"
	@which gitleaks > /dev/null 2>&1 || echo "Warning: gitleaks not installed (brew install gitleaks)"
	@cp -n .env.example .env 2>/dev/null || true
	@echo "Setup complete. Edit .env and run: make up && make migrate"

up:
	docker compose up -d --build
	@echo "Waiting for services..."
	@sleep 5
	@docker compose ps

down:
	docker compose down

migrate:
	DATABASE_URL=postgresql+asyncpg://payguard:payguard@localhost:5432/payguard \
		$(PYTHON) -m alembic upgrade head

test:
	$(PYTHON) -m pytest tests/ -v

lint:
	$(PYTHON) -m ruff check payguard/ tests/

typecheck:
	$(PYTHON) -m mypy payguard/shared/ payguard/verifier/ --strict

dataset:
	$(PYTHON) -m payguard.dataset.generate

eval-dev:
	@echo "Running evaluation on validation split..."
	$(PYTHON) -m payguard.eval.run --split val

eval:
	@echo "Running evaluation on TEST split — appending to ledger..."
	$(PYTHON) -m payguard.eval.run --split test

eval-smoke:
	@echo "Running smoke eval (5 samples)..."
	$(PYTHON) -m payguard.eval.run --split val --max-samples 5

audit-verify:
	$(PYTHON) -m payguard.shared.audit_verify

demo:
	PAYGUARD_DEMO=1 GATEWAY_MODE=EMULATE docker compose up -d --build
	$(PYTHON) -m payguard.demo.seed
	@echo "Demo running. Visit http://localhost:3000"

chaos:
	$(PYTHON) -m payguard.gateway.chaos_toggle

seed-examples:
	$(PYTHON) -m payguard.dataset.seed_examples

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .mypy_cache .ruff_cache .pytest_cache dist build
