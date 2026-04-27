VENV=.venv
PIP=$(VENV)/bin/pip
PYTEST=$(VENV)/bin/pytest
UVICORN=$(VENV)/bin/uvicorn

.PHONY: setup run test test-postgres postgres-up postgres-down

setup:
	python3 -m venv $(VENV)
	$(PIP) install -r requirements.txt

run:
	$(UVICORN) app.api.main:app --reload

test:
	$(PYTEST) -q

test-postgres:
	RUN_POSTGRES_TESTS=true POSTGRES_RUNTIME_ENABLED=true $(PYTEST) -q tests/test_api.py -k "postgres"

postgres-up:
	docker compose -f docker-compose.postgres.yml up -d

postgres-down:
	docker compose -f docker-compose.postgres.yml down
