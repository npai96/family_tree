# Viraasat security decisions

**Status:** V3 implemented and locally tested; production Postgres and Render verification are pending. These decisions describe the working tree, not a shipped release. The [route matrix](security-route-matrix.md) and [threat model](security-threat-model.md) track coverage and residual risks.

## SEC-001 — Keep authorization on the server

**Status:** V3 policy code and synthetic tests pass locally; release is pending.

- **Threat:** A signed-in member changes a circle, person, relationship, or media ID to reach another family's record, or a viewer sends an editor request directly.
- **Decision:** Authenticate the caller and check circle membership and the required role for each operation in FastAPI. Keep browser affordances as a reflection of the server policy, never as its enforcement.
- **Why:** Google/Supabase identify an account, but do not know which Viraasat circle that account may read or edit. One policy vocabulary makes route review and role tests possible.
- **Alternatives:** Trust hidden/disabled UI controls (insufficient because requests can be forged); put all authorization in database policies (possible only after changing the privileged runtime role and testing real Postgres).
- **Trade-off:** Every API and realtime path must apply the right policy. A missed check remains a risk until route inventory and two-family tests cover it.
- **Implementation:** `app/api/authorization.py` defines named actions and denies unknown roles/actions; `_require_circle_action` in `app/api/main.py` applies them after membership lookup. `app/api/privacy.py` handles sensitive-field redaction. Media/person joins are circle-scoped and open WebSockets revalidate session/membership before broadcasts.
- **Verification:** `tests/test_api.py` contains `test_two_family_object_ids_and_role_boundaries` and `test_open_realtime_connection_stops_after_membership_or_session_revocation` with fictional records. These pass in the local SQLite suite; hosted evidence is pending.
- **Residual risk:** A valid account or device compromise can still expose the circles it is authorized to see; role permission is not consent from every person represented in the tree.

## SEC-002 — Use revocable app sessions and move hosted sessions into secure cookies

**Status:** Hashing, expiry, and per-session logout are existing behavior. V3 hosted cookie/CSRF protection and account-wide revocation pass local tests; hosted verification is pending.

- **Threat:** A copied, expired, or revoked token continues to access private records.
- **Decision:** Use high-entropy app sessions, store only a SHA-256 lookup digest in Postgres, check expiry/revocation at access, and bind media/WebSocket tickets to the parent session. V3 puts the hosted app session in an `HttpOnly`, `Secure`, `SameSite` cookie, requires a CSRF header for state-changing browser requests, and adds account-wide invalidation for loss of account access. Review/dev mode retains its explicit bearer contract.
- **Why:** Server-side session rows allow immediate app-level revocation without needing to wait for the original fourteen-day lifetime.
- **Alternatives:** A stateless long-lived JWT (harder to revoke immediately); retain hosted localStorage bearer tokens (simpler but exposed to JavaScript in the app origin).
- **Trade-off:** Cookies reduce token exposure to JavaScript but are automatically sent by browsers, so every state-changing hosted request needs CSRF protection. Media and WebSocket access require a careful migration. A logout revokes one session; provider-side revocation alone does not automatically revoke every app session.
- **Implementation:** V2 session contract in `app/api/main.py`, `app/api/hosted.py`, `app/api/security.py`, `app/web/app.js`, and `auth_sessions` in `app/api/db_runtime.py` / `db/runtime_postgres.sql`. V3 working tree sets `__Host-ft_session` in `app/api/hosted.py`, checks an `X-FT-CSRF` header in `app/api/cookie_auth.py`, and migrates old browser bearer sessions by rotation; `app/web/app.js` uses cookie credentials. Account-wide revocation is exposed through hosted API and operator script. Local integration passes; hosted verification is pending.
- **Verification:** Existing token expiry, hashed storage, logout, and ticket revocation tests in `tests/test_api.py`; `tests/test_hosted.py` covers cookie flags, CSRF denial, migration rotation, logout, account-wide revocation, and child-ticket invalidation. Local tests pass; browser/hosted smoke is pending.
- **Residual risk:** Compromised client devices and injected JavaScript can still issue same-origin requests while a hosted session is active, even if they cannot read an `HttpOnly` token. The app does not continuously recheck the Google account's status.

## SEC-003 — Keep media private behind the application

**Status:** Existing private-media architecture; V3 local authorization and quota tests pass. Hosted provider verification is pending.

- **Threat:** A guessed or shared object path exposes family media, or an image URL remains usable after access is revoked.
- **Decision:** Keep the Supabase Storage bucket private. Check circle membership in FastAPI before serving an object through the API, using either the app bearer session or a short-lived, scoped, parent-session-bound media ticket.
- **Why:** The API can recheck access and parent-session revocation on each read. Storage service credentials never enter the browser.
- **Alternatives:** Public bucket with opaque names (rejected: obscurity is not authorization); short-lived Supabase signed URLs (less API bandwidth, but a previously issued URL remains usable until expiry and cannot be revoked on app sign-out).
- **Trade-off:** Proxying image bytes uses Render bandwidth and adds latency; free-tier egress and per-circle storage must be monitored and bounded.
- **Implementation:** `app/api/main.py` media routes and `app/api/hosted.py` server-only Storage calls. This implementation does **not** issue Supabase signed URLs.
- **Verification:** Media-ticket expiry, wrong-circle, scope, parent-session-revocation, and API quota tests pass locally. Real private-bucket setup is user-reported in `docs/DEPLOY_FREE_DEMO.md`; V3 hosted provider check remains pending.
- **Residual risk:** Authorized people can download, save, or photograph media. Private storage is not a promise that recipients cannot redistribute it.

## SEC-004 — Treat database RLS as a separate design gate

**Status:** Existing database role inspected; per-circle RLS is **not implemented**.

- **Threat:** A backend authorization bug could read another circle through the runtime database connection.
- **Decision:** Keep browser-facing `anon` and `authenticated` table access revoked. Do not claim a second per-circle RLS boundary for backend requests until the runtime uses a non-bypassing role, trustworthy transaction-scoped identity, policies on every relevant table, and two-family integration tests under that exact role.
- **Why:** The current backend role owns the tables and can bypass normal RLS; enabling RLS alone does not protect backend queries from cross-circle mistakes.
- **Alternatives:** Retain API-only authorization with explicit coverage (current model); introduce a non-owning runtime role with per-circle policies (greater defense in depth, but increases migration and transaction complexity).
- **Trade-off:** Deferring per-circle RLS leaves the API as the principal family-isolation boundary. Moving roles requires a staged, reversible migration and a real Postgres test environment.
- **Implementation:** `db/supabase_privacy.sql` revokes browser roles; `app/api/db_runtime.py` uses `DATABASE_URL`. No per-circle runtime policies are claimed here.
- **Verification:** SQL review and opt-in real Postgres policy tests are required before changing this status. SQLite tests cannot prove Postgres RLS execution.
- **Residual risk:** A missing or faulty API authorization check can expose another circle to the privileged runtime role.

## SEC-005 — Bind invitations to an identity and lifecycle

**Status:** Recipient binding and one-time status checks existed; V3 expiry, explicit revocation, idempotent creation, and atomic replay handling pass local helper and route tests. Release is pending.

- **Threat:** An invitation is accepted by the wrong account, reused, kept indefinitely, or used to gain a stronger role than intended.
- **Decision:** Resolve the recipient to an account ID at creation, permit only that account to respond, and constrain the granted role to the invitation. V3 adds explicit expiry/revocation and atomic replay handling with owner-visible history.
- **Why:** A shareable invitation code is an identifier, not a grant of permission. The accepted invitation must be bound to the authenticated recipient and original owner decision.
- **Alternatives:** Open bearer invite link (simpler but transferable); manual direct membership grants only (less smooth collaboration).
- **Trade-off:** Account-bound invitations require invitees to sign in before the owner can target them. Expiry can interrupt a legitimate invite and needs clear UI messaging.
- **Implementation:** `app/api/security_abuse.py` implements seven-day expiry, account-bound atomic response, owner-initiated revocation, and idempotent pending creation; schema changes are in `app/api/db_runtime.py` and `db/runtime_postgres.sql`. `app/api/main.py` applies them. Hosted invitations require the recipient's account ID/invitation code; review mode rejects duplicate display-name matches.
- **Verification:** API-level wrong-recipient, expiry, revocation, replay, role-floor, and duplicate-name tests in `tests/test_api.py`; helper tests in `tests/test_security_abuse.py` pass locally. Concurrent Postgres and hosted evidence remain pending.
- **Residual risk:** An invited person's legitimate account can be compromised, and owners can intentionally grant wider access. Owners still need to verify that the invitation code came from the intended recipient.

## SEC-006 — Bound free-tier abuse with shared state

**Status:** Existing per-file upload size/type checks; V3 durable request counters and total storage quotas pass local helper and route tests. Hosted verification is pending.

- **Threat:** Repeated invitation, login, read, or upload requests exhaust the free app/database/storage allowance.
- **Decision:** Keep content-sniffed, bounded uploads and add limits that are enforced by durable shared database state where they need to survive Render restarts. Limit aggregate media storage per circle and uploader as well as individual file size. Proposed V3 defaults are 250 MiB per circle, 100 MiB per uploader, 30 uploads/day, 20 invitations/day, and 240 heavy reads/minute; confirm the final values and responses in integrated tests before publication.
- **Why:** A process-local Python counter resets on restart and does not coordinate workers; the database is already the shared durable component in this deployment.
- **Alternatives:** In-memory counters (simple but weak across restarts/workers); paid rate-limit/cache service (adds cost and an extra dependency); provider edge/WAF controls (useful later, but not a substitute for account/circle quotas).
- **Trade-off:** Limits can delay real users, especially on shared IPs, and database-backed accounting adds write contention. Capacity values should be tuned from synthetic tests and observed usage, not invented traffic metrics.
- **Implementation:** Existing media checks in `app/api/main.py`; V3 database-backed rate windows and transaction-scoped circle/uploader quotas in `app/api/security_abuse.py`, with schema in `app/api/db_runtime.py` and `db/runtime_postgres.sql`. API call sites include login callbacks, invitations, heavy graph reads, and uploads.
- **Verification:** Existing spoofed-format/size and API quota/429 tests pass locally. A guarded disposable Postgres run also passed durable 429 and API upload flows, plus an idempotent startup migration. Concurrent upload quota and deployed-worker behavior remain pending.
- **Residual risk:** A small free deployment can still be saturated by distributed requests before application limits run. Paid/edge protection and anomaly detection are deferred.

## SEC-007 — Log outcomes without family content

**Status:** Existing structured request logging and bounded process-local metrics; no V3 external alerting pipeline is planned for this release.

- **Threat:** Logs or portfolio screenshots leak bearer tokens, OAuth codes, medical notes, stories, full request URLs, or family images.
- **Decision:** Record generated request IDs, route templates, status, outcome, and timing while omitting bodies, raw query strings, and auth headers. Keep role-visible audit events inside the circle, redact sensitive fields in viewer-facing audit/revision payloads, and use only synthetic evidence in portfolio materials.
- **Why:** Operators need enough signal to investigate failures without turning logs into another copy of the family archive.
- **Alternatives:** Full request logging (more debugging context but unacceptable content exposure); no logs (hides incidents and regressions).
- **Trade-off:** Sanitized logs are less useful for reconstructing exact inputs; use a request ID and targeted tests for diagnosis. Process-local metrics are not a global multi-instance dashboard.
- **Implementation:** `app/api/observability.py`, `app/api/privacy.py`, audit routes in `app/api/main.py`, and Uvicorn access-log setting in `Dockerfile`/deployment configuration.
- **Verification:** Existing route-template/query-redaction tests in `tests/test_api.py`; final integrated check should include synthetic 401/403/429 responses and confirm their status rates can be inspected without query/body content.
- **Residual risk:** Metrics remain process-local without production aggregation or alerts. Infrastructure/provider logs outside this app need their own access/retention review. Authorized users can still see audit information appropriate to their circle role.

## SEC-008 — Limit real-data use until consent and recovery are designed

**Status:** Existing relationship deletion confirmation and V3 ownership-transfer confirmation reduce accidental UI actions; a tested restore path and living-person data controls are not implemented.

- **Threat:** A living relative's sensitive details are entered without consent, or valuable family history is changed/deleted with no tested way to restore it.
- **Decision:** Keep the app limited to approved testers; use fictional data in V3 tests and portfolio evidence. Do not expand onboarding for sensitive real family or medical records until living-person visibility, correction, export, deletion, medical-note consent, retention, and independent backup/restore are designed and tested. Treat destructive edits and ownership transfers as high-risk operations in the next product design pass.
- **Why:** A circle owner/editor role does not prove consent of every person represented, and audit/revision rows are not a verified off-platform backup.
- **Alternatives:** Permit real records now with an owner warning (does not solve consent or recovery); block all collaboration (removes the central product value).
- **Trade-off:** The approved cohort can test interaction flows, but Viraasat should not be the sole copy of valuable records or be presented as a mature sensitive-record system.
- **Implementation:** `app/web/app.js` confirms relationship deletion and explicitly warns that ownership transfer demotes the current owner to viewer. The API audits these actions. Scope limits are documented in `docs/V3_SECURITY_PRD.md` and `docs/DEPLOY_FREE_DEMO.md`; user-facing consent/export/deletion and independent restore remain **not yet implemented**.
- **Verification:** A future synthetic restore drill and consent/role tests are needed before this status can change. No such proof is claimed here.
- **Residual risk:** Testers may still enter real data, including material shared by other people; the product should make the limits and consent expectations clear before broader release.

## SEC-009 — Enforce the approved tester cohort in the application

**Status:** V3 allowlist and local regression tests pass; hosted verification is pending.

- **Threat:** A valid Google account reaches the demo even though the owner has not approved it, or an older app session regains access after the V3 migration.
- **Decision:** Require a configured list of verified Google email addresses at hosted startup. Check the verified email at the OAuth callback and check recorded approval against the current list on every app session or derived ticket. On an account's first V3 login, revoke its pre-approval app sessions.
- **Why:** Google sign-in proves identity, while a separate application rule decides who may test the product. Google consent-screen test users are an additional gate, not the only gate.
- **Alternatives:** Rely on Google test-user settings alone (outside the API's control); open registration (requires broader abuse, consent, and operational work); manually approve every login (slows testing).
- **Trade-off:** The owner must keep the Render environment list current, and changing it requires a restart. Existing V2 testers must log in again. Removing an address blocks access while it is absent; revoke app sessions as well for permanent removal.
- **Implementation:** `app/api/hosted.py` verifies the provider email and stores it in `approved_accounts`; `app/api/main.py` checks approval for sessions and realtime tickets. Hosted configuration fails closed when the list is missing.
- **Verification:** `tests/test_hosted.py` covers unlisted Google identity denial, removal blocking existing session/ticket access, startup configuration, and first-login revocation of V2 sessions. Local provider mocks only; Render/Supabase validation remains pending.
- **Residual risk:** Operator access to Render/Supabase is high trust. An approved tester may share content they can legitimately see, and the current application does not continuously poll Google for account revocation.
