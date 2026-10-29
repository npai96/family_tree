# Family workspace implementation

The user approved the five-destination concept in `prototypes/family-os-workspace/` for implementation. The working interface now uses that structure and visual direction with live application data.

| Destination | Working features |
| --- | --- |
| Home | Selected circle, actual people, connection counts, available audit activity, links into the workspace |
| Family tree | Existing D3 graph, search, root and traversal options, zoom, selected-person summary, relationship management |
| People & stories | Searchable directory, readable profile, role-gated editor, private media, discussion, revision history |
| Places & time | Person selector, existing place and migration tools, context events, timeline, lineage chronology |
| Our circle | Account controls, circle creation, invitations, membership, ownership transfer, change requests, audit log |

## How the pieces fit

`app.js` still owns authentication, selected identity/circle/person, data requests, mutation handlers, and permission decisions. It passes the existing working panels into `workspace.js`, which arranges them and manages presentation state. `workspace.css` supplies the approved warm paper, indigo, rounded surfaces, desktop sidebar, and mobile navigation.

Routes use `#home`, `#tree`, `#people`, `#places`, and `#circle`. This works with the existing root HTTP route and browser Back/Forward without introducing a router dependency or changing the Google callback. Unknown fragments fall back to Home.

Visited destinations remain mounted while hidden so an unfinished form and graph viewport can survive navigation. They are not mounted before first use. Person tabs activate their existing lazy loaders only when opened. The workspace is keyed by account and circle, so switching either discards the old presentation state and drafts. Signing out unmounts all private destinations. Backend authorization remains authoritative; navigation is not an access-control boundary.

The guided person journey uses the existing save, duplicate detection, relationship creation, and graph-reveal functions. No prototype records, sample activity, or fake map routes are included in the production workspace.

## Verification

- `make test` includes route allowlisting, directory search boundaries, and all existing frontend/backend tests.
- `scripts/check_workspace_ui.cjs` exercises the real app through a headless browser using fictional owners and viewers. It checks profile saving, draft retention through Back navigation, lazy media, graph rendering, place tools, invitations, the add-person journey, mobile overflow, sign-out, viewer edit restrictions, and medical-note privacy.
- The browser check requires Playwright, installed Chrome, and a **disposable local test server**. It creates records and refuses non-loopback URLs or a missing `VIRAASAT_UI_TEST_DISPOSABLE=1` acknowledgement. Do not point it at the normal local database.

Example isolated server (use a new temporary directory):

```sh
test_dir=$(mktemp -d /tmp/viraasat-workspace.XXXXXX)
env APP_ENV=test ENABLE_REVIEW_AUTH=true POSTGRES_RUNTIME_ENABLED=false \
  DATABASE_URL= SUPABASE_URL= SUPABASE_PUBLISHABLE_KEY= \
  SUPABASE_SECRET_KEY= SUPABASE_SERVICE_ROLE_KEY= \
  DB_PATH="$test_dir/test.db" MEDIA_DIR="$test_dir/media" \
  .venv/bin/uvicorn app.api.main:app --host 127.0.0.1 --port 8766
```

In another terminal with Playwright available:

```sh
VIRAASAT_UI_TEST_DISPOSABLE=1 node scripts/check_workspace_ui.cjs
```

These local checks do not verify a new hosted release or a new Google OAuth round trip. The Supabase/PostgreSQL opt-in checks still require their separate configured test environment. No migration or authentication configuration change is needed for this interface release.

## Release verification, October 28, 2026

The user approved updating the website while preserving security and backend behavior. The release changes presentation, navigation, and the explicit asset allowlist for `workspace.js` and `workspace.css`. It does not modify database migrations, authorization handlers, session/CSRF logic, storage handlers, dependencies, or hosted environment settings.

Fresh local verification passed: 19 JavaScript tests, 102 Python tests, and the disposable owner/viewer browser workflow described above. Twelve PostgreSQL-specific tests were skipped. This is regression evidence, not a claim that live Google sign-in or Supabase was retested.

Render remains a manual release: deploy the reviewed `main` commit without changing environment variables or enabling review authentication. After deployment, confirm the workspace loads, the approved owner can access existing family data, and the invited viewer remains unable to edit or read medical notes. No database restore or migration rehearsal is required for this presentation-only release. The preceding commit is the rollback target if the new interface has a regression.
