# Architecture Current State (solo builder view)

> TL;DR: feature coverage is strong, but architecture is still MVP-grade and needs hardening before scale.

## What is running now

- Backend: `FastAPI` in `app/api/main.py`
- Frontend: React + D3 in `app/web/index.html`
- Runtime DB: SQLite (`app/api/mvp.db`)
- Media storage: local filesystem (`app/media/`)
- Realtime: WebSocket channel per circle
- Tests: `pytest` via `make test`

Deployment assets now present:

- `Dockerfile`
- `docker-compose.prod.yml`
- `Caddyfile`
- GitHub Actions CI/CD workflows under `.github/workflows/`
- `docs/DEPLOY_AWS_CHEAP.md`

## What is already drafted for future state

- Postgres schema draft: `db/schema.sql`
- Neo4j constraints draft: `db/neo4j_constraints.cypher`
- MVP architecture direction: `MVP_TECHNICAL_ARCHITECTURE.md`

## Practical module map

- `app/api/main.py`
  - schema init + DB access
  - auth/session + role checks
  - persons/relationships/subgraph traversal
  - context events/timeline
  - media/places/migration
  - discussions/revisions/invitations/audit

- `app/web/index.html`
  - app state + API calls
  - D3 layouts (`hierarchy`, `time_aligned`)
  - graph interactions + timeline + sidebars

## Why maintainability feels hard right now

- backend and frontend are each concentrated in one big file
- graph rendering and product logic are tightly coupled
- infra assumptions (SQLite + local media) are great for localhost, weak for production

## What is strong and worth preserving

- permission model is real and used
- collaboration primitives exist (change requests, revisions, audit, chat)
- timeline + migration + context integration is a differentiated UX

## Solo-friendly architecture direction (no rewrite)

- keep existing behavior stable
- extract modules in small slices
- migrate infra in this order:
  1. CI/logging baseline
  2. Postgres runtime
  3. object storage media
  4. auth hardening + observability

This keeps momentum while reducing long-term maintenance pain.
