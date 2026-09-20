# Family Tree MVP

Collaborative genealogy platform focused on South Asian family history with graph traversal and contextual storytelling.

## Portfolio demo with real accounts and no AWS

Use the [free hosted setup guide](docs/DEPLOY_FREE_DEMO.md) and `render.yaml`: Render Free runs this app; Supabase Free provides Google authentication, persistent Postgres records, and private media storage. Testers can create private circles, explore their own fictional sample family, edit records, and return on another device. Real provider setup and a deployed acceptance test are still required. Free plans have storage/traffic limits, cold starts, and inactivity policies; this is not an always-on archival guarantee.

The hosted profile disables the unverified user picker, isolates review sessions from verified sessions, and enables RLS with browser database access revoked. Existing AWS deployment instructions below are an alternative path and are not needed for this demo. Moving the app does not stop billing for AWS resources that already exist.

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
- Selection-scoped UI loading cancels obsolete requests and ignores late responses so rapid circle/person switching cannot repaint panels with stale data.
- Circle selection loads membership, people, and relationships first; collaboration panels and management history are resiliently staged afterward so optional reads cannot block the first usable screen.
- Closed sidebar tools mount their forms and large person-option lists only after first expansion, avoiding thousands of hidden DOM nodes on large circles while preserving panel state after opening.
- The people/relationships panel initially renders 80 rows per list and uses an indexed person-name lookup; explicit **Show all** controls retain access to the complete circle without making first expansion pay the full rendering cost.
- A keyboard-friendly **Find a person** control searches name, birthplace, year, occupation, and religion with case/diacritic-insensitive matching. It renders at most eight ranked results, opens the chosen profile, and carries that choice into a compact graph-root summary instead of duplicating every person in another always-mounted dropdown.
- Graph traversal controls use visible labels and a responsive two-row layout so direction, depth, scope, layout, and lateral-expansion choices remain understandable between open sidebars.
- Opening a circle no longer auto-selects its first person or eagerly fetches that profile's media, places, revisions, and discussion. Graph rendering, node clicks, and explicit **Open profile** actions select a person intentionally.
- Selecting a person now reads the profile from the already-loaded circle data and issues no hidden-panel requests. Opening Media, Places, Revision History, or Discussion activates only that panel's loader; later person changes refresh only panels the user has actually used.
- Media and Places reuse the global selected-person context instead of mounting separate full-circle dropdowns, preventing another thousand hidden options after both panels have been used in a 500-person circle.
- Media access tickets are issued only when previews exist or the Media panel is opened; realtime WebSocket tickets and connections begin only after opening Discussion. Both remain circle-scoped and reset on circle changes.
- SVG graph visualization panel for loaded subgraphs.
- Context event creation, person-event linking, and person timeline retrieval.
- Graph interaction features:
  - click node to open profile details and highlight lineage path
  - zoom controls (`+`, `-`, `fit`, `1:1`)
  - timeline item click highlights related graph node(s)
- Media MVP:
  - upload file assets to a person profile
  - stream into server-owned paths with a configurable size limit (`MAX_MEDIA_UPLOAD_BYTES`, 25 MiB by default)
  - verify supported formats from file signatures rather than trusting the browser MIME declaration
  - keep raster previews separate from downloadable documents, audio, and video
  - list per-person media
  - download/open stored media assets
- Places and migration MVP:
  - add per-person lived places with coordinates/date ranges
  - map preview for selected place
  - export person migration path as GeoJSON
- Collaboration MVP:
  - per-entity discussion threads (currently person-scoped in UI)
  - thread message APIs
  - realtime message updates over circle WebSocket channels
- Revision history MVP:
  - immutable person revision snapshots on create and approved change-request edits
  - person revision history API and sidebar viewer
- Field-level privacy:
  - `medical_notes` remains stored in the person record but is returned only to circle owners and editors
  - viewer responses redact the field consistently in people lists, graph nodes, event-linked people, revision snapshots, audit payloads, and proposed change requests
  - viewers cannot propose sensitive-field changes, and new audit rows store changed field names rather than duplicating profile values
- Data quality guardrails:
  - duplicate-hint endpoint for person creation (name/date/place scoring)
  - hard block for exact name+birthdate duplicates
  - relationship taxonomy validation (`parent_of`, `spouse_of`, etc.)
  - parent-cycle prevention for ancestry edges
- Auth MVP:
  - `/auth/login` issues bearer session tokens
  - `/auth/me` resolves current user
  - `/auth/logout` revokes only the current session
  - API endpoints accept `Authorization: Bearer ...`
  - database rows contain only SHA-256 token digests; startup migrates legacy plaintext sessions without invalidating browser tokens
  - media links use renewable 15-minute, circle-scoped tickets stored only as hashes
  - WebSockets use 60-second, one-use tickets in the subprotocol header instead of URL credentials
  - legacy `X-User-Id` access is available only when `ALLOW_LEGACY_X_USER_ID=true`
- Backend tests with `pytest` and dependency-free frontend graph utility tests with Node's built-in test runner.

## Project Layout
- `app/api/main.py`: API server and graph traversal logic.
- `app/api/privacy.py`: pure field-visibility and JSON-redaction policy used by API serializers.
- `app/web/index.html`: minimal browser shell that loads integrity-verified same-origin dependencies.
- `app/web/app.js` and `app/web/app.css`: application behavior and presentation, served as same-origin revalidated assets.
- `app/web/bootstrap.js`: loading watchdog and recoverable dependency failure UI.
- `app/web/graph-utils.js`: pure, Node-tested graph navigation helpers.
- `app/web/error-utils.js`: pure, Node-tested formatting for readable API and validation failures.
- `app/web/privacy-utils.js`: pure, Node-tested external-link construction for consent-based integrations.
- `app/web/person-search-utils.js`: pure, Node-tested person indexing, normalization, ranking, and result bounding.
- `app/web/vendor/`: integrity-verified React 18.3.1, ReactDOM 18.3.1, and D3 7.9.0 production files with their package license notices.
- `tests/test_api.py`: API tests.
- `scripts/seed_graph_benchmark.py`: disposable 500-person/800-relationship browser performance fixture.
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

Local development defaults to `APP_ENV=development` with the review-only identity picker enabled. The UI labels this mode because choosing a user does not prove that user's identity.

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

`make test` runs both the Node graph-navigation contract tests and the Python API suite.

## Reproduce the Large-Graph Baseline

The graph switches from portrait-rich cards to a compact performance overview above 180 people or 320 relationships. The browser reports request-to-first-frame time and compares it with the 1.2-second target.

```bash
BENCHMARK_DIR="$(mktemp -d)"
.venv/bin/python scripts/seed_graph_benchmark.py --database "$BENCHMARK_DIR/family-tree.db"
DB_PATH="$BENCHMARK_DIR/family-tree.db" .venv/bin/uvicorn app.api.main:app --port 8001
```

Open `http://127.0.0.1:8001`, continue as **Graph Benchmark**, select **family_expanded**, set depth to `10`, and render. The status below the controls should show **Performance overview · 500 people · 800 relationships** and the measured first-frame time. The fixture is synthetic, creates a new SQLite file only, and refuses to overwrite an existing database.

## Local Postgres Sandbox
```bash
make postgres-up
python3 scripts/sqlite_to_postgres_runtime_export.py
```

Open a Postgres REPL:

```bash
docker compose -f docker-compose.postgres.yml exec postgres psql -U family_tree -d family_tree
```

Run the small guarded Postgres-backed API subset:

```bash
make test-postgres
```

Note:
- this expects local Postgres to be running via `make postgres-up`
- and `psycopg[binary]` installed inside `.venv` via `make setup` or `./.venv/bin/pip install -r requirements.txt`
- the Docker sandbox binds to `127.0.0.1:5433` so it does not collide with any local Postgres already using `5432`

Guide:
- `docs/POSTGRES_MIGRATION_GUIDE.md`
- `docs/POSTGRES_CUTOVER_RUNBOOK.md`

## Notes
- This increment uses SQLite for fast iteration.
- Production plan remains Postgres + Neo4j + object storage media pipeline per `MVP_TECHNICAL_ARCHITECTURE.md`.
- Bearer sessions are the default authorization path; keep `ALLOW_LEGACY_X_USER_ID=false` outside explicit local compatibility testing. Startup rejects that compatibility flag in staging or production.
- Authentication has two explicit runtime modes. `APP_ENV=development` or `test` enables the unverified review picker by default; `APP_ENV=staging` or `production` defaults to `ENABLE_REVIEW_AUTH=false` and closes `/users`, `/auth/login`, existing review sessions, media tickets, and WebSockets.
- `/runtime-config` gives the browser the public mode and warning text; `/health` exposes the environment and auth mode for operators. Neither endpoint contains secrets.
- HTTP responses include `X-Request-Id` and `Server-Timing`; structured request logs use route templates and omit request bodies, query strings, credentials, and raw entity IDs.
- `/metrics` reports process-local request counts, client/server errors, bounded latency histograms, approximate P50/P95, and read/write budget status by method and route template. It defaults on locally and off in staging/production.
- To enable deployed metrics, set `ENABLE_METRICS_ENDPOINT=true` and provision a unique `METRICS_BEARER_TOKEN` of at least 32 characters through a secret manager. The endpoint then requires `Authorization: Bearer ...`; never commit it or store it in a non-secret GitHub variable. EC2 deploy scripts restrict the generated `.env` file to mode `0600`.
- Metrics are intentionally bounded and privacy-safe, but process-local: multi-worker or multi-instance deployments need an external scraper/aggregator before the numbers represent the whole service.
- Browser access is same-origin by default in staging/production. Set `CORS_ALLOWED_ORIGINS` to an explicit comma-separated list of trusted `http://` or `https://` origins when a separate frontend requires cross-origin API access; wildcard origins are rejected at startup.
- The browser shell serves vendored React/ReactDOM 18.3.1 and D3 7.9.0 production builds from the same origin with SHA-384 Subresource Integrity. Core application startup no longer depends on a third-party JavaScript CDN; a bootstrap watchdog still keeps a visible retry state if any required asset is unavailable.
- Browser responses include `nosniff`, clickjacking, referrer, opener, and permissions protections. The main app enforces a source-restricted Content Security Policy and no longer permits inline scripts. Its remaining inline-style allowance exists because React and D3 still apply dynamic presentation styles and should be reduced as frontend modularization continues.
- Place records never auto-load a third-party map. A user must open **Map options**, review the disclosure, and explicitly follow a `noopener noreferrer` link before the selected location or network metadata is shared with Google.
- Medical notes use an API-boundary access rule: owners and editors can read/write them, while viewers receive `null`. Stored history is preserved; revision, audit, graph, and change-request serializers apply the same redaction policy.
- Setting `ENABLE_REVIEW_AUTH=true` in staging or production is an explicit review override, not production authentication. The picker has no password, magic-link, or external identity proof and must not be exposed to untrusted users.
- Deploy the session-digest migration to all app instances together; an older binary cannot read newly hashed session rows. Existing clients stay signed in, while short-lived circle tickets are reissued.
- Media in this increment stores files locally under `app/media/` for localhost testing.
- Production ingress must enforce a request-body limit at or below `MAX_MEDIA_UPLOAD_BYTES`; the application limit protects persisted storage but runs after multipart parsing begins.
- Realtime WebSocket features require a websocket backend (`websockets` package included in `requirements.txt`).

## Cheap AWS Deploy + CI/CD
- CI workflow: `.github/workflows/ci.yml`
- Primary CD workflow: `.github/workflows/deploy-aws-ssm.yml`
- ECR publish workflow: `.github/workflows/publish-ecr.yml`
- Fallback SSH deploy workflow: `.github/workflows/deploy-aws-ec2.yml`
- Deployment guide: `docs/DEPLOY_AWS_CHEAP.md`
- Running AWS setup guide: `docs/AWS_SETUP_RUNNING_GUIDE.md`
- Deployment failure runbook: `docs/DEPLOYMENT_FAILURE_RUNBOOK.md`
