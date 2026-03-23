# Production Readiness Gap Analysis (solo-focused)

> Practical read: what to fix first so you can run this safely as a one-person team.

## Current readiness score (rough)

- Product capability: **8/10**
- Maintainability: **4/10**
- Scalability: **3/10**
- Operational readiness: **3/10**
- Security/privacy posture: **4/10**

## Biggest gaps (ordered by impact vs effort)

## 1) Runtime DB is still SQLite

Why it matters:

- write concurrency and horizontal scaling are limited.

Do next:

- move runtime to Postgres (keep SQLite for local quick tests only).

## 2) Media is stored on app filesystem

Why it matters:

- breaks on redeploys and multi-instance hosting.

Do next:

- move to object storage + signed URLs.

## 3) Large single-file backend/frontend

Why it matters:

- harder debugging, higher regression risk when you’re solo.

Do next:

- modularize incrementally around boundaries (auth, graph, media, discussions).

## 4) Mixed auth paths

Why it matters:

- extra complexity and avoidable security ambiguity.

Do next:

- keep Bearer in staging/prod, legacy header only for local dev if needed.

## 5) Missing deploy/observability baseline

Why it matters:

- incidents become guesswork.

Do next:

- CI gates + structured logs + error tracking + basic metrics.

## 6) No explicit performance budgets

Why it matters:

- regressions happen quietly as data grows.

Do next (starter targets):

- P95 read API < 250ms
- P95 write API < 400ms
- graph first frame < 1.2s for 500 nodes / 800 edges

## 7) Privacy/governance not fully hardened

Why it matters:

- genealogy data can be sensitive and multi-family contexts add risk.

Do next:

- field-level privacy rules
- backup/restore runbook + monthly drill
- retention/deletion policy

## Recommended order (solo-optimized)

1. CI safety rails + logging
2. Postgres migration
3. media storage migration
4. modularization pass
5. auth hardening + privacy controls
6. perf/load tuning

## Keep this simple

- no big-bang rewrite
- no multi-quarter “platform project”
- ship in narrow slices with rollback each time
