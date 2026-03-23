# Execution Plan (compressed for solo founder)

> Replacing 30/60/90 with a practical 6-week plan.

## Week 0 (1-2 days): deployment foundation

## Objectives

- get a cheap AWS deploy path live
- stop treating deployment as a future problem

## Deliverables

1. AWS box ready
- create Lightsail/EC2 Ubuntu instance
- run `deploy/ec2/bootstrap.sh`
- point domain DNS to instance

2. GitHub Actions wired
- add repo secrets:
  - `AWS_EC2_HOST`
  - `AWS_EC2_USER`
  - `AWS_EC2_SSH_KEY`
  - `APP_DOMAIN`
- verify CI runs on PR
- verify CD runs on push to `main`

3. First successful deploy
- app reachable at your domain
- `/health` returns OK over HTTPS

## Exit criteria

- you can deploy with one merge to `main`
- rollback path is known and tested once

## Week 1-2: stabilize and de-risk

## Objectives

- reduce regression risk
- make code easier to reason about
- install non-negotiable quality gates

## Deliverables

1. Safety rails
- CI: tests + lint required
- local pre-commit checks (optional but recommended)
- CD deploy status visible in GitHub Actions

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
- first DB migration rollback tested

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
- add \"deploy health\" step in GitHub Actions (fail pipeline if `/health` fails)

## Exit criteria

- predictable release routine
- known rollback path
- baseline perf numbers documented

## Suggested first issue list

1. `chore(ci): add required test + lint checks`
2. `chore(cd): configure AWS deploy secrets and first successful deploy`
3. `refactor(api): split auth/session + membership checks from main.py`
4. `refactor(web): extract GraphView + layout helpers`
5. `feat(db): add Postgres env config + migration tool`
6. `feat(media): storage adapter + signed URL flow`
7. `chore(ops): add structured logs + request_id`

## Daily operating rhythm (solo)

- 60-90 min deep work block on one roadmap item
- end day with:
  - green tests
  - short progress note
  - next-step TODO in repo

## \"How to do all this\" in plain order

1. Follow `docs/DEPLOY_AWS_CHEAP.md` once and get first deploy live.
2. Lock CI/CD before deeper refactors.
3. Then do backend/frontend modularization in small slices.
4. Then swap runtime DB (SQLite -> Postgres).
5. Then swap media storage (local -> S3/object storage).
6. Then run load tests and optimize hotspots.
