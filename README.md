# Family Tree MVP

Collaborative genealogy platform focused on South Asian family history with graph traversal and contextual storytelling.

## Increment Plan
1. Increment 1 (current): backend foundation + minimal React UI + graph APIs + tests.
2. Increment 2: authentication, role-based circle permissions, change requests workflow.
3. Increment 3: media upload pipeline (signed URLs, derivatives metadata, processing jobs).
4. Increment 4: timeline/context events + maps integration.
5. Increment 5: realtime collaboration chat + revision/audit UX.

## What Is Implemented in Increment 1
- `FastAPI` backend with SQLite persistence.
- Core APIs:
  - create/list circles
  - create/list persons
  - create/list relationships
  - ancestor/descendant subgraph traversal by depth
- Minimal React frontend served at `/`.
- API tests with `pytest`.

## Project Layout
- `app/api/main.py`: API server and graph traversal logic.
- `app/web/index.html`: minimal React-based frontend (CDN React).
- `tests/test_api.py`: API tests.
- `db/schema.sql`: target Postgres schema for production architecture.
- `db/neo4j_constraints.cypher`: target Neo4j constraints/indexes.

## Run Locally
```bash
make setup
make run
```

Open:
- App UI: `http://127.0.0.1:8000/`
- API docs: `http://127.0.0.1:8000/docs`

## Run Tests
```bash
make test
```

## Notes
- This increment uses SQLite for fast iteration.
- Production plan remains Postgres + Neo4j + object storage media pipeline per `MVP_TECHNICAL_ARCHITECTURE.md`.
