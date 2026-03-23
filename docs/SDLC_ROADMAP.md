# SDLC Roadmap (solo + lean)

> Goal: keep moving fast as a solo builder, but avoid breaking prod every week.

## Working model (one-person version)

Use a lightweight release loop:

- tiny branches (or direct-to-main for very small, low-risk fixes)
- PR-style self-check before merge (yes, even if it's just you)
- deploy to staging first, then promote to prod
- always keep a rollback path

## Environments (lean)

- `dev`: local machine
- `staging`: one hosted environment that mirrors prod config as closely as possible
- `prod`: real users/data

If budget/time is tight, keep `staging` and `prod` only, and use local as `dev`.

## Solo Definition of Ready (before coding)

- what user problem this change solves (1-2 lines)
- acceptance criteria (3-5 bullets)
- test plan (unit/integration/manual)
- rollback note (how to undo if it goes wrong)

## Solo Definition of Done (before deploy)

- tests pass (`make test`)
- lint/format pass
- docs/config notes updated if behavior changed
- manual smoke flow tested in UI
- release note written in commit/PR text

## Self-PR checklist (copy/paste template)

- [ ] What changed and why
- [ ] Risk level: low / medium / high
- [ ] API/schema impact
- [ ] Test evidence (`make test`, manual steps)
- [ ] Rollback steps

## Release cadence (compressed)

- 2-3 focused releases per week
- hotfixes anytime, but always follow with short notes

## Branch/version strategy (simple)

- branches: `feat/*`, `fix/*`, `chore/*`
- commits: clear, conventional-style messages
- tag weekly stable points (`v0.x.y`) once production starts

## Quality gates to add first

1. CI required: `make test`
2. Lint/format required (`ruff` + `black`)
3. Optional type checks (non-blocking at first)
4. Minimal UI smoke automation for critical path

## Incident loop (solo)

When something breaks:

1. stop feature work
2. patch + rollback if needed
3. write 5-minute incident note:
- what broke
- user impact
- root cause
- fix shipped
- guardrail to prevent repeat

## Security baseline (must-have even solo)

- Bearer-only auth in prod
- secrets in env/secret manager, never repo
- backup + restore drill monthly
- signed URLs for media access
- strict CORS + request size limits

## Rule of thumb

If a change touches auth, data model, or graph rendering:

- do it in smaller commits
- ship behind a feature flag if possible
- validate in staging before prod
