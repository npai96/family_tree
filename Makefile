VENV=.venv
PIP=$(VENV)/bin/pip
PYTEST=$(VENV)/bin/pytest
UVICORN=$(VENV)/bin/uvicorn

.PHONY: setup run test postgres-up postgres-down

setup:
	python3 -m venv $(VENV)
	$(PIP) install -r requirements.txt

run:
	$(UVICORN) app.api.main:app --reload

test:
	$(PYTEST) -q

postgres-up:
	docker compose -f docker-compose.postgres.yml up -d

postgres-down:
	docker compose -f docker-compose.postgres.yml down
