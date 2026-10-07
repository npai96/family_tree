# Viraasat V3 security implementation report

**Status:** V3 is deployed for a small approved-tester demo, with user-reported hosted checks on 2026-10-07; **it is not a security certification for real family records**. The V2-to-V3 migration and hosted-session path passed tests on disposable local PostgreSQL. The exact Render source commit and production configuration have not been independently audited. A disposable Supabase migration rehearsal and complete Auth/Storage backup-and-restore drill remain unperformed.

| Evidence item | Status |
|---|---|
| V3 implementation commit | `f3bc5fc`; Google account-selection follow-up `a1762d1`. The owner reported successful Render deploys. Reconfirm the exact live source SHA in Render before citing it as independent release evidence. |
| V3 API and frontend test command/result | Earlier disposable-Postgres full suite: `RUN_POSTGRES_TESTS=true .venv/bin/pytest -q`: **112 passed**, including 12 PostgreSQL tests; `node --test tests/*.js`: **16 passed**. On 2026-10-07, `.venv/bin/pytest -q tests/test_hosted.py tests/test_api.py` passed **96 tests**, with **12 PostgreSQL tests skipped** because that disposable instance was not started; `git diff --check` passed. `make test` could not start because this Mac's Xcode license is unaccepted; the underlying commands ran directly. |
| Container packaging and startup | The production `Dockerfile` built successfully as a local image. The image started with disposable test-mode settings and `/health` returned `status: ok`, `db_backend: sqlite`, and `auth_mode: review_unverified`. The temporary container was stopped. This does not test the hosted Supabase configuration. |
| Disposable local Postgres and privacy test | Docker Postgres 16: all guarded integration tests passed. A populated V2 schema upgraded to V3 twice without losing sample users, a person, a session, or an invitation. The Supabase privacy SQL enabled RLS and removed `anon`/`authenticated` read privileges on 19 tables in this local rehearsal. The backend still uses a privileged owner role, so **per-circle RLS is not claimed**. The destructive suite never targeted Supabase. |
| Hosted Render release and smoke check | Owner-reported: approved owner/viewer Google sign-in; an unlisted account denied; fictional Rao circle and edit persisted; viewer fields read-only with medical-note privacy notice; Safari and Incognito Chrome sessions both lost access after **Sign out on all devices**; a previously opened private image URL returned `{"detail":"Missing or invalid media access ticket"}` after sign-out. The viewer initially failed because Render's approved-email list had the wrong address; correcting it and deploying restored sign-in. No signed-in direct-API probe or independent review of Render/Supabase settings was performed. |
| Synthetic screenshots reviewed and saved | Four local review-mode screenshots under `docs/portfolio-assets/security/` show fictional owner/viewer UI, invitation expiry/revocation, and medical-note redaction. They are not hosted security proof and are not published. |

## 1. Executive summary

Viraasat's most important security boundary is family membership. A Google sign-in establishes an identity; an application allowlist admits a small tester cohort; neither grants access to every circle. V3 defines named server-side circle actions, rechecks open realtime connections, moves hosted browser sessions into secure cookies with CSRF checks, revokes pre-approval V2 sessions on first V3 login, and bounds invitations, reads, and uploads in shared database state. Synthetic SQLite and disposable PostgreSQL checks pass, including two simultaneous first logins and durable throttling. The owner has also exercised core hosted login, role, revocation, and private-media flows; those observations are narrower than a full provider/configuration audit.

## 2. Original trust model

In V2, the browser completed Google sign-in through Supabase and held an app bearer session in localStorage. FastAPI resolved that session to a local user, checked circle membership/role, then used a privileged Postgres runtime connection and server-only Storage secret. Sessions had a fourteen-day expiry and were stored as SHA-256 digests. The Storage bucket was private; the API rechecked membership and proxied media, sometimes after a scoped session-bound ticket. Uvicorn access logs were disabled, while app request logs recorded route templates and outcomes rather than raw URLs or bodies. Browser database roles lacked table grants, but the privileged runtime role meant Postgres RLS was **not** a second per-circle authorization boundary for API requests.

## 3. Threats identified

The [threat model](security-threat-model.md) covers cross-family ID substitution, viewer escalation, resource enumeration, private-media misuse, stolen/expired sessions, invitation replay, accidental destructive changes, unsafe uploads and free-tier exhaustion, leaked secrets, and private content in logs/screenshots. Highest impact is unauthorized access to another family or medical notes. The two-family test matrix is the primary application-level proof target.

## 4. Controls implemented and release evidence

### Inspected V2 baseline

- Account identity is verified with Supabase Auth in hosted mode; review-mode identity selection is disabled in production configuration.
- FastAPI checks circle membership and required roles; `app/api/privacy.py` redacts medical notes from viewer-facing person, revision, change-request, and audit payloads.
- Hashed, expiring app sessions and scoped, session-bound media/WebSocket tickets support app-level logout/revocation. A private Supabase Storage bucket is accessed only by the server; hosted uploads accept JPEG/PNG after type/size checks.
- Request telemetry records generated request IDs, route templates, status/outcome, and timing without request bodies, auth headers, or query strings. Metrics are process-local.

### V3 controls and evidence

| Control | Code location | Regression evidence | Deployed evidence |
|---|---|---|---|
| Centralized named-action policy and cross-family matrix | `app/api/authorization.py`; `app/api/main.py`; [route matrix](security-route-matrix.md) | Two-family ID/role and WebSocket revocation tests pass locally; a PostgreSQL hosted-flow test covers sign-in, invitation, viewer redaction, denied edits, and session/ticket revocation. A focused SQLite cookie test sends a viewer PATCH with valid CSRF, receives 403, and confirms no profile change. | Owner saw read-only viewer profile and medical-note privacy notice. No direct hosted API mutation probe. |
| Approved tester admission and legacy-session transition | `app/api/hosted.py`; `app/api/main.py`; `approved_accounts` table | Denied unlisted Google callback, deapproval, missing-list startup, and first-login V2 revocation tests pass locally. | Owner saw an unlisted account denied; a mismatched Render email denied the viewer until corrected and redeployed. |
| Hosted `HttpOnly`/`Secure`/`SameSite` session cookie and CSRF guard | `app/api/hosted.py`, `app/api/cookie_auth.py`, `app/web/app.js` | Hosted cookie/CSRF tests pass locally. | Real Google sign-in and sign-out worked; cookie flags and CSRF rejection were not independently inspected in the hosted browser. |
| Account-wide app-session revocation | `app/api/hosted.py`, `scripts/revoke_hosted_sessions.py` | Hosted self/operator tests and ticket invalidation pass locally. | Owner reported Safari and Incognito Chrome both signed out after account-wide revocation. |
| Private media ticket revocation | `app/api/main.py`; `app/api/hosted.py` | Ticket/session binding and logout tests pass locally. | A copied image link returned `Missing or invalid media access ticket` after app sign-out. |
| Invitation expiry, revocation, replay safety | `app/api/security_abuse.py`; `app/api/main.py`; invitation UI | Helper and API lifecycle tests pass locally | Pending |
| Request-rate and aggregate media quota limits | `app/api/security_abuse.py`; `app/api/main.py` | Helper and API cap/429 tests pass; PostgreSQL rate counter and API flows pass. Concurrent upload quota proof remains pending | Pending |
| Sanitized 401/403/429 status visibility | Existing `app/api/observability.py`; no new external pipeline | Structured route log tests pass locally; production metrics unavailable | No production aggregation/alerting claimed |
| Database per-circle RLS, if chosen | Not implemented | Real Postgres test required | Not claimed |

### Before / after / risk reduced

The “after” column describes the implementation. The specific hosted behaviors observed by the owner are listed above; do not infer that every control was independently tested in production.

| Area | Confirmed before | V3 after | Risk reduced |
|---|---|---|---|
| Authorization | Endpoint-specific membership/role helpers in `app/api/main.py` | Named fail-closed actions; synthetic two-family/WebSocket tests pass | Reduces risk of inconsistent route checks and stale realtime membership locally |
| Demo admission | Google consent-screen Testing setting only | Server checks verified email against configured tester list at callback and during sessions/tickets | Blocks unlisted Google identities in local tests; owner observed hosted rejection before a corrected Render allowlist permitted viewer sign-in |
| Sessions | Hashed app tokens, localStorage bearer in hosted UI, per-session logout, fourteen-day expiry | `__Host-ft_session`, `X-FT-CSRF`, legacy bearer rotation, self/operator revoke-all; local tests pass | Reduces JavaScript-readable token exposure; owner observed cross-browser app-session revocation |
| Invitations | Target-account and pending-state checks; no explicit expiry/revocation | Seven-day expiry, owner revocation, idempotent creation, atomic response; API tests pass | Reduces indefinite/replayed invite risk locally |
| Media/abuse | Private API-proxied objects, per-file type/size limits | Durable rate and circle/uploader caps; API tests pass | Bounds tested request/storage abuse, subject to hosted quota validation |
| Database | Browser grants revoked; backend uses privileged owner | No per-circle RLS claim without role migration and real Postgres test | Not claimed |
| Auditability | Structured route-template request logs and circle audit rows | Existing logs/metrics make 401/403/429 statuses observable; final integrated capture pending | No new aggregation or alerting claim |

## 5. Major decisions and trade-offs

The [decision records](security-decisions.md) explain why the API owns circle authorization, why private media remains proxied instead of switching to short-lived Supabase signed URLs, why account-wide revocation is preferable to relying on provider logout, and why per-circle RLS is a separate role/migration gate. V3 uses hosted HTTP-only cookies with CSRF protection; local tests cover the API and derived media tickets, and the owner observed cross-browser revocation and media-ticket denial. Database-backed limits cost writes but can survive a Render restart, unlike process-local counters. The PostgreSQL first-login concurrency and restart-migration checks pass; concurrent upload and deployed-worker behavior remain untested.

## 6. Tests and evidence

Local synthetic tests cover foreign circle/nested IDs, viewer edits and medical-note redaction, unapproved identity denial, first-login V2 revocation, revoked sessions and tickets, cookie CSRF, over-quota uploads, 429 limits, and invitation replay/wrong-recipient/expiry/revocation. Commands and prior full-suite counts are in the evidence table above. On 2026-10-07, five focused tests passed against the current checkout, including a new viewer-cookie PATCH denial test; `git diff --check` passed. Disposable PostgreSQL tests additionally exercised database-backed flows, simultaneous first logins, durable throttling, and an additive V2 migration. A non-bypassing runtime role would still be required to claim per-circle RLS. The hosted checks above are user-reported; `/health` configuration and direct API denial were not independently probed during this final smoke pass.

## 7. Observability added

Existing `app/api/observability.py` emits structured request events with request IDs, route templates, outcomes, statuses, and timing; 401/403/429 responses can be identified from their status. Route metrics are process-local and gated off by default in production. The V3 limiter adds durable counters for enforcement, but no external logging service, alert pipeline, or multi-instance security dashboard is part of this release. No production telemetry capture is claimed.

## 8. Screenshots and assets produced

The [screenshot plan](security-screenshot-plan.md) specifies role contrast, cross-family denial, private-media flow, tests, sanitized telemetry, and architecture using synthetic families. Four reviewed PNGs under `docs/portfolio-assets/security/` show a fictional owner, viewer, invitation lifecycle, and medical-note restriction. Their visible review-mode banner makes the local-test context explicit. They are source assets, not a public portfolio publication or proof of hosted Google authentication. An RLS screenshot must not be created unless a non-bypassing runtime role and real policy test exist.

## 9. Remaining risks

The V3 browser removes V2's localStorage bearer. A pre-approval V2 session requires Google re-login and is revoked then; an already-approved legacy session can rotate into a cookie. An older deployed V2 page or compromised same-origin script can still use a current approved session until revocation. Same-origin malicious code can make requests through the browser even after cookie migration. Removing a tester email blocks access while absent, but permanent removal also requires app-session revocation. Google provider account revocation is not a continuous app-session check. Authorized recipients can retain and redistribute content. The privileged Postgres runtime role means API mistakes remain the family-isolation risk. Free-tier capacity and process-local telemetry limit abuse detection; there is no verified independent backup/restore drill or complete living-person consent/export/deletion model. Hosted observations are not a penetration test or full provider configuration audit.

## 10. P2 backlog

- Evaluate non-owning Postgres runtime role and per-circle RLS after a disposable real-Postgres integration environment exists.
- Add tested export/deletion, living-person consent, and documented retention/restore controls before inviting real relatives to contribute sensitive material.
- Aggregate metrics and add actionable anomaly alerts only when traffic and hosting justify them.
- Evaluate stronger browser isolation and account/provider revocation hooks; do not treat the cookie as protection from a compromised same-origin script.
- Plan capacity/abuse escalation and secret-rotation drills for a broader audience; keep the Google cohort limited until then.

## Resume / portfolio evidence

**Publication boundary:** V3 is live for approved testers according to the owner's Render and browser checks. Portfolio copy may describe the exact observed flows above as user-reported acceptance, alongside local test evidence. Do not present the demo as security-certified or imply that untested migration, backup, consent, rate-limit, and RLS claims were proved in production.

Candidate bullets (each under 35 words):

1. Centralized Viraasat's owner/editor/viewer rules into named server-side actions and added synthetic two-family and realtime revocation tests for cross-circle access.
2. Moved hosted browser sessions to HTTP-only cookies with CSRF checks; local tests and owner-reported two-browser checks cover account-wide revocation and private-media ticket denial.
3. Added expiring, revocable invitations and database-backed request/storage limits, with API tests for replay, wrong-account acceptance, quota rejection, and throttling.

Portfolio summary (**draft; review wording and evidence before publication**):

> Viraasat is a shared family archive, so a Google sign-in cannot by itself decide whose stories someone may see. For V3, I mapped the trust boundary from Supabase Auth through FastAPI to Postgres and private image storage, then centralized circle permissions in server-side rules. Local tests with fictional families check that changing an ID cannot cross the family boundary and that viewers cannot read medical notes or edit records. The approved-tester demo is now hosted; in live checks, a viewer could read the shared family but not edit cards or see medical notes. Account-wide sign-out removed access in Safari and Incognito Chrome, and a later sign-out invalidated an already opened image link. I still separate those observed flows from broader claims about backups, consent, and database-level isolation.

Interview talking points (**distinguish local tests from hosted observations**):

1. **Problem:** A valid Google login could be mistaken for family access. **Decision:** Treat FastAPI membership/role policy as the family boundary. **Trade-off:** Every route must apply it. **Result:** Named-action and two-family tests pass locally; the owner observed viewer read-only and medical-note notice in the hosted app. A direct hosted write probe remains unperformed.
2. **Problem:** Media URLs can outlive access. **Decision:** Keep a private bucket and membership-checked API proxy with session-bound tickets. **Trade-off:** More backend bandwidth. **Result:** Ticket invalidation passes local tests; the owner observed an opened image link fail after sign-out in the hosted app.
3. **Problem:** RLS being enabled could be confused with per-family defense in depth. **Decision:** Document the privileged-role limitation and gate role migration on real Postgres tests. **Trade-off:** API remains the principal isolation layer. **Result:** No unsupported RLS claim in the V3 evidence package.
