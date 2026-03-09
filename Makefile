VENV=.venv
PIP=$(VENV)/bin/pip
PYTEST=$(VENV)/bin/pytest
UVICORN=$(VENV)/bin/uvicorn

.PHONY: setup run test

setup:
	python3 -m venv $(VENV)
	$(PIP) install -r requirements.txt

run:
	$(UVICORN) app.api.main:app --reload

test:
	$(PYTEST) -q
