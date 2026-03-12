# Family Tree MVP

Collaborative genealogy platform focused on South Asian family history with graph traversal and contextual storytelling.

## Increment Plan
1. Increment 1: backend foundation + minimal React UI + graph APIs + tests.
2. Increment 2 (current): user identity headers, role-based circle permissions, and change requests workflow.
3. Increment 3: media upload pipeline (signed URLs, derivatives metadata, processing jobs).
4. Increment 4: timeline/context events + maps integration.
5. Increment 5: realtime collaboration chat + revision/audit UX.

## What Is Implemented in Increment 2
- `FastAPI` backend with SQLite persistence.
- User and role model:
  - create/list users
  - create circles as owner
  - add/list circle members (`owner`, `editor`, `viewer`)
- Core genealogy APIs (permission-gated by circle role):
  - create/list circles
  - create/list persons
  - create/list relationships
  - ancestor/descendant subgraph traversal by depth
- Collaboration APIs:
  - create/list change requests
  - approve/reject change requests (owner/editor)
- Minimal React frontend served at `/`.
- SVG graph visualization panel for loaded subgraphs.
- Context event creation, person-event linking, and person timeline retrieval.
- Graph interaction features:
  - click node to open profile details and highlight lineage path
  - zoom controls (`+`, `-`, `fit`, `1:1`)
  - timeline item click highlights related graph node(s)
- Media MVP:
  - upload file assets to a person profile
  - list per-person media
  - download/open stored media assets
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

Quick manual flow in UI:
1. Create user(s)
2. Select active user
3. Create circle (active user becomes owner)
4. Add members with editor/viewer roles
5. Add people and relationships
6. Create/approve change requests

## Run Tests
```bash
make test
```

## Notes
- This increment uses SQLite for fast iteration.
- Production plan remains Postgres + Neo4j + object storage media pipeline per `MVP_TECHNICAL_ARCHITECTURE.md`.
- API authorization for MVP is simplified via `X-User-Id` header.
- Media in this increment stores files locally under `app/media/` for localhost testing.
