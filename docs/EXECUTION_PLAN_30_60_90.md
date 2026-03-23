# Execution Plan (compressed for solo founder)

> Replacing 30/60/90 with a practical 6-week plan.

## Week 1-2: stabilize and de-risk

## Objectives

- reduce regression risk
- make code easier to reason about
- install non-negotiable quality gates

## Deliverables

1. Safety rails
- CI: tests + lint required
- local pre-commit checks (optional but recommended)

2. Code organization pass (targeted, not rewrite)
- split `app/api/main.py` into logical modules gradually
- extract graph renderer/API client logic from `app/web/index.html`

3. Logging baseline
- structured logs
- request ID in API logs

## Exit criteria

- shipping is safer
- big-file change risk starts dropping

## Week 3-4: production shape

## Objectives

- remove infra bottlenecks
- harden auth and storage

## Deliverables

1. Postgres migration path
- migration tooling in place
- app runs against Postgres in staging

2. Media storage v1
- storage adapter interface (`local` + `s3`)
- signed URL download path
- DB stores keys/metadata only

3. Auth cleanup
- Bearer auth primary path
- legacy fallback disabled in staging/prod

## Exit criteria

- staging no longer depends on local disk for media
- DB migration path is repeatable

## Week 5-6: scale confidence

## Objectives

- prove operability under load
- make deploy/recover predictable

## Deliverables

1. Performance baseline
- load test key APIs
- set and track P95 targets

2. Graph performance pass
- test larger family graphs
- optimize render hotspots

3. Release hardening
- staging -> prod promotion checklist
- rollback runbook tested once

## Exit criteria

- predictable release routine
- known rollback path
- baseline perf numbers documented

## Suggested first issue list

1. `chore(ci): add required test + lint checks`
2. `refactor(api): split auth/session + membership checks from main.py`
3. `refactor(web): extract GraphView + layout helpers`
4. `feat(db): add Postgres env config + migration tool`
5. `feat(media): storage adapter + signed URL flow`
6. `chore(ops): add structured logs + request_id`

## Daily operating rhythm (solo)

- 60-90 min deep work block on one roadmap item
- end day with:
  - green tests
  - short progress note
  - next-step TODO in repo
