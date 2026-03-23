# Temporary Workarounds vs Production Upgrades

> Purpose: track what we are doing temporarily to move fast, and what to change before/at production scale.

## 1) Domain and TLS

Current workaround:

- No custom domain yet.
- `APP_DOMAIN` and `AWS_EC2_HOST` are both set to EC2 public IP/DNS.
- App may run over plain HTTP for now.

Production target:

- Buy/setup domain.
- Point DNS `A` record to Elastic IP.
- Set:
  - `AWS_EC2_HOST` = EC2 host (IP or DNS for SSH)
  - `APP_DOMAIN` = app domain (example `app.example.com`)
- Enforce HTTPS with Caddy.

Trigger to upgrade:

- Before sharing with real users outside trusted testing.

## 2) Runtime database

Current workaround:

- SQLite file (`app/api/mvp.db`) mounted on instance disk.

Production target:

- Move runtime DB to Postgres.
- Use migrations (Alembic or equivalent).
- Keep SQLite only for local/dev quick runs.

Trigger to upgrade:

- As soon as concurrent usage increases or before multi-instance deployment.

## 3) Media storage

Current workaround:

- Media files stored on local VM disk (`app/media`).

Production target:

- Use S3 (or equivalent object storage).
- DB stores keys/metadata only.
- Serve through signed URLs + derivatives.

Trigger to upgrade:

- Before high media volume, backup requirements, or multi-instance scale.

## 4) Single-instance deployment

Current workaround:

- One EC2 VM with Docker Compose (`app` + `caddy`).

Production target:

- Still okay for early production.
- Later move to managed/replicated setup:
  - container platform (ECS/App Runner/etc.)
  - managed DB (RDS)
  - external object storage (S3)

Trigger to upgrade:

- CPU/memory saturation, frequent restarts, or downtime risk becomes visible.

## 5) CI/CD strategy

Current workaround:

- GitHub Actions deploy directly to server over SSH.

Production target:

- Keep this for lean solo phase.
- Add staging/prod promotion and deploy health checks.
- Add rollback automation and release tags.

Trigger to upgrade:

- When deployment failures or manual rollback friction starts costing time.

## 6) Auth compatibility path

Current workaround:

- Bearer token auth plus optional legacy header path.

Production target:

- Bearer-only in staging/prod.
- Disable legacy auth fallback outside local dev.

Trigger to upgrade:

- Before broad user onboarding.

## 7) Observability

Current workaround:

- Basic app logs and manual checks.

Production target:

- Structured logs + request IDs.
- Error monitoring and alerting.
- Basic metrics (latency, error rate, uptime).

Trigger to upgrade:

- Immediately after first external users, before growth.

## 8) Backups and recovery

Current workaround:

- No fully tested automated restore flow yet.

Production target:

- Automated DB backups.
- Media backup/replication strategy.
- Documented restore runbook tested monthly.

Trigger to upgrade:

- Before storing important real family archives.

## 9) Codebase shape

Current workaround:

- Large backend/frontend files to iterate quickly.

Production target:

- Incremental modularization:
  - backend: routers/services/repos
  - frontend: graph renderer/components/api client

Trigger to upgrade:

- Start now in small slices; mandatory before large feature velocity.

## 10) Practical “go-live checklist” (minimum)

Before calling it production-ready:

- [ ] Domain + HTTPS live
- [ ] Postgres runtime
- [ ] S3 media path enabled
- [ ] Bearer-only auth in non-dev
- [ ] CI required checks pass
- [ ] CD with health check + rollback path
- [ ] Backup/restore test completed
- [ ] Basic observability wired

---

## Related docs

- `docs/DEPLOY_AWS_CHEAP.md`
- `docs/SDLC_ROADMAP.md`
- `docs/EXECUTION_PLAN_30_60_90.md`
- `docs/PRODUCTION_READINESS_GAP_ANALYSIS.md`
