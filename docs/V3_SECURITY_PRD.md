# Viraasat V3 — Security and privacy layer (working PRD)

**Status:** Working PRD. V3 is deployed for a small approved-test cohort; the owner has reported successful hosted Google sign-in, role-limited viewing, session revocation, and private-media ticket denial after sign-out. Disposable local PostgreSQL checks pass. A disposable Supabase migration rehearsal, independent hosted API probe, living-person consent, tested restoration, and per-circle database RLS remain separate evidence or design gates. **Audience:** a small approved-test cohort today; expansion to real family records requires a separate release decision. This document incorporates the portfolio-evidence requirements supplied for V3. It does not certify the hosted deployment.

## Product problem and outcome

Viraasat stores family relationships, stories, medical notes, and photos. A valid login proves who someone is; it does not prove they belong to a particular circle or should edit a particular record. V3 should make that distinction reliable across every API and media path, reduce abuse of the free hosted service, and give families clearer control over sensitive information.

**Outcome:** A signed-in person can access only the circles and fields their role permits. A leaked identifier, modified request, expired session, or guessed media path must not cross that boundary. Security decisions and test evidence should be reviewable for a technical product portfolio without exposing family data.

## Verified V2 baseline

- In V2, Supabase Google sign-in verified identity and FastAPI issued a hashed-at-rest, 14-day app session whose bearer token the browser held in localStorage. Provider/account revocation did not immediately invalidate an existing app session. V3 now uses an HTTP-only app cookie and account-wide app-session revocation; provider revocation still is not continuously synchronized. See `app/api/hosted.py`, `app/api/security.py`, `app/web/app.js`, and `docs/DEPLOY_FREE_DEMO.md`.
- FastAPI checks circle membership and owner/editor/viewer roles. Viewers cannot write; medical notes are omitted from viewer responses, including relevant history and audit payloads. See `app/api/main.py` and `app/api/privacy.py`.
- The hosted media bucket is private. The API validates JPEG/PNG content and file size, and checks membership before serving media or issuing a scoped, session-bound media ticket. See `app/api/main.py` and `app/api/hosted.py`.
- Supabase tables have RLS enabled and browser-facing `anon`/`authenticated` grants revoked. **The backend connects through the table-owning database role, so current circle isolation depends on FastAPI checks; RLS is not a second per-circle enforcement layer for those requests.** See `db/supabase_privacy.sql`, `app/api/db_runtime.py`, and [Supabase's RLS guidance](https://supabase.com/docs/guides/database/postgres/row-level-security).
- Tests cover several boundaries using a mocked provider and temporary SQLite. Real Supabase/RLS policy execution and all hosted permission paths have not been independently tested. See `tests/test_hosted.py` and `docs/DEPLOY_FREE_DEMO.md`.

## V3 scope and priorities

| Priority | Work package | Acceptance evidence |
|---|---|---|
| P0 | Inventory every read/write/media route and centralize identity, circle, role, and field-level authorization in reusable server-side policies. Preserve viewer and medical-note behavior. | Deny-by-default route matrix; tests modify circle/person/media IDs across two fictional families, including list, history, audit, and realtime paths. |
| P0 | Session lifecycle: reject invalid/expired sessions, revoke all app sessions when an account loses access, and decide whether to move the browser token from localStorage to a secure HTTP-only cookie with CSRF protection. | Expiry, logout, provider-revocation/admin-revocation, and CSRF tests for the chosen design. Document residual exposure. |
| P0 | Keep private media access membership-bound. Compare the current revocable API media tickets/proxy with short-lived Supabase signed URLs before changing it; signed URLs remain usable until expiry. | Unauthorized users cannot obtain or use media access; sign-out/revocation behavior is measured for the chosen path. |
| P0 | Abuse and cost controls for invitations, authentication callbacks, read-heavy endpoints, and uploads; bound total storage per circle/account as well as per-file size. | Excess requests receive a bounded response (for example 429); retries cannot create duplicate invitations or unbounded storage use. Verify behavior under Render's deployment shape. |
| P0 | Secrets and observability: keep database/storage secrets server-only; log request IDs, route templates, outcomes, and relevant authorization failures without tokens, URLs containing credentials, family stories, or medical notes. | Redaction tests and sanitized sample events; no secrets in repository, browser assets, or portfolio screenshots. |
| P1 | Decide whether V3 needs database-level **per-circle** RLS. If yes, replace the privileged table-owner runtime access with a role/context design that actually evaluates policies, then test it against real Postgres. | Two-family policy tests under the actual runtime role; no claim of defense-in-depth until verified. |
| P1 | Invitation lifecycle: expiry, acceptance bound to the intended account, revocation, replay protection, and owner-visible history. | Wrong-account, expired, revoked, repeated, and role-escalation attempts fail. |
| P1 | Accidental destruction and sensitive-data lifecycle: confirmation/recovery for destructive changes; decisions for living-person visibility, medical-note consent, deletion/export, backup, and restore. | Recovery drill with fictional records; role and consent tests; documented retention/restore limits. |
| P2 | Advanced anomaly detection and automated security alerts after there is enough traffic to justify thresholds. | Alert runbook and false-positive review; no invented detection metrics. |

Open sign-up, public family trees, and a claim of clinical-grade protection are **not** in this scope. Keep approved-test-account access until a separate product decision expands it.

The working-tree implementation makes that cohort an application rule: hosted startup requires `APPROVED_TESTER_EMAILS`, Google callback checks the verified email, and app sessions/tickets recheck the list. The first V3 login revokes old sessions created before verified-email approval. See [SEC-009](security-decisions.md#sec-009--enforce-the-approved-tester-cohort-in-the-application).

## Key design gates

1. **Authorization boundary:** Use one server-owned policy vocabulary for `view circle`, `edit person`, `manage members`, `view medical notes`, and `access media`. UI role cues mirror these checks but never replace them. [OWASP's object-authorization guidance](https://api-security.owasp.org/editions/2023/en/0xa1-broken-object-level-authorization/) explains why changing a resource ID is a central test.
2. **Database boundary:** Current RLS/grants protect against direct browser database access. Per-circle RLS requires a non-bypassing runtime role and trustworthy request identity inside the database transaction. Choose that architecture only after an integration test proves the policy under the exact role used in production.
3. **Media boundary:** Current session-bound tickets can stop working at logout; [Supabase signed URLs](https://supabase.com/docs/guides/storage/serving/downloads) have simpler delivery but remain valid until expiry. Preserve the private bucket either way.
4. **Privacy model:** Current viewer/editor/owner roles are circle-wide except medical notes. Before real relatives are invited, decide what living people can consent to, hide, correct, export, or delete. Do not treat role-based access as consent.
5. **Free hosting:** Choose limits that can run on Render/Supabase Free without new AWS spending. Document any control that needs shared state or an external service; process-local counters alone do not enforce global limits across workers or restarts.

## Delivery sequence

1. **Threat model and route inventory.** Record threat, likelihood/impact, current control, verification, and residual risk for cross-family access, escalation, ID enumeration, media, sessions, invitations, destruction, uploads, secrets/logs, and scraping.
2. **P0 controls and tests.** Land small, reviewable changes with migration and rollback notes. Use two synthetic families and at least owner/editor/viewer/outsider identities. Keep the public hosted service on the last verified release until tests and a controlled smoke check pass.
3. **P1 decisions and provider verification.** Run actual Postgres/Supabase checks in a disposable environment before changing RLS or media architecture. Exercise restore and invitation lifecycle with fictional data.
4. **Portfolio evidence.** Capture only sanitized, synthetic evidence after controls work. Publish a concise explanation of the trust boundaries, choices, tests, and remaining limits.

## Documentation and evidence required during implementation

The supplied V3 addendum is an evidence requirement, not proof that a control already exists. Maintain these artifacts as the corresponding work lands:

- `docs/security-decisions.md`: one short record per material choice with decision, threat, rationale, alternatives, trade-offs, implementation, verification, and residual risk.
- `docs/security-threat-model.md`: concrete abuse-case table using `threat → likelihood/impact → control → verification → residual risk`.
- `docs/security-portfolio.md`: product context, security problem, 4–6 key threats, decisions in `problem → decision → trade-off → evidence` form, Mermaid trust-boundary diagram, meaningful tests, and limitations.
- `docs/security-screenshot-plan.md`: screenshot, screen/tool, concept, setup, redactions, and caption. Prefer role contrast, cross-family denial, private media, actual RLS policy if implemented, tests, sanitized telemetry, and architecture.
- `docs/portfolio-assets/security/`: capture only when tooling and synthetic data permit; otherwise provide exact manual reproduction steps. Never expose real family content, credentials, JWTs, live signed URLs, email addresses, or private logs.
- `SECURITY.md`: disclosure/contact process and deployment/security expectations, with no invented guarantee.
- `docs/security-implementation-report.md`: original trust model, threats, controls, decisions, tests, observability, safe visuals, residual risks, P2 backlog, three factual resume-bullet candidates, a 100–150-word product-oriented portfolio summary, and three `problem → decision → trade-off → result` interview points. Write only after implementation evidence exists.

The final report should include a **before/after/risk reduced** table only for states confirmed in code and tests. Do not fabricate metrics, screenshots, weaknesses, or a claim that Viraasat is fully secure.

## V3 definition of done

- P0/P1 controls chosen for release are implemented, tested, and deployed through a reversible process.
- Cross-family, role, session, media, upload, invitation, and log-redaction regressions pass; provider-dependent claims have provider-level evidence.
- Decisions, threat model, architecture diagram, screenshot plan, `SECURITY.md`, and implementation report match the shipped code.
- Every public visual uses synthetic/sanitized data. Residual risks and operational limits are stated plainly.
