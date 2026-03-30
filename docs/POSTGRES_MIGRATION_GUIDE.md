# Postgres Migration Guide

> Practical first step, not a big-bang switch.

## What this increment does

- introduces `DATABASE_URL`-style config for the API runtime
- keeps SQLite as the active runtime backend
- adds a runtime-focused PostgreSQL schema in `db/runtime_postgres.sql`
- adds local Postgres Docker compose in `docker-compose.postgres.yml`
- adds a SQLite -> PostgreSQL export helper in `scripts/sqlite_to_postgres_runtime_export.py`

## What this increment does not do yet

- it does **not** switch the live API runtime to PostgreSQL
- it does **not** rewrite all raw SQL in `app/api/main.py`
- it does **not** migrate production data automatically

That is intentional. The goal is to separate:

1. runtime config cleanup
2. data export/import mechanics
3. actual runtime backend switch

## Current runtime config

The API now understands:

- `DATABASE_URL=sqlite:////absolute/path/to/mvp.db`
- or the older `DB_PATH=/absolute/path/to/mvp.db`

If `DATABASE_URL` is PostgreSQL, the app currently fails fast with a clear message instead of partially booting.

## Start local PostgreSQL

```bash
docker compose -f docker-compose.postgres.yml up -d
```

This gives you a local Postgres instance with the runtime-compatible schema loaded.

Default dev connection:

```text
postgresql://family_tree:family_tree_dev@127.0.0.1:5432/family_tree
```

## Export current SQLite data for PostgreSQL

```bash
python3 scripts/sqlite_to_postgres_runtime_export.py
```

This writes:

```text
db/generated/runtime_seed.sql
```

You can then load it into the local Postgres container with something like:

```bash
docker exec -i $(docker ps -qf name=postgres) psql -U family_tree -d family_tree < db/generated/runtime_seed.sql
```

## Recommended next implementation slices

## Slice 1

- move DB code out of `app/api/main.py` into a dedicated module
- centralize query execution instead of calling `conn.execute(...)` everywhere

## Slice 2

- add PostgreSQL connection support in that DB module
- translate placeholder style and integrity errors in one place

## Slice 3

- run API tests against both SQLite and PostgreSQL
- fix query-level incompatibilities one category at a time

## Slice 4

- switch staging runtime to PostgreSQL
- keep SQLite only for ultra-fast local smoke tests

## Why there are two Postgres schemas in `db/`

- `db/schema.sql`
  - aspirational production schema
  - richer than the current MVP runtime

- `db/runtime_postgres.sql`
  - compatibility schema for the existing SQLite-era API
  - best first migration target for the current codebase
