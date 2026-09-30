# Viraasat V3 route authorization matrix

This is the review checklist for `app/api/main.py` and `app/api/hosted.py`. `owner`, `editor`, and `viewer` refer to **membership in the circle named by the request**, not merely to a successful Google sign-in. A nested person, media asset, relationship, event, or thread ID must also belong to that circle. Unknown roles and policy actions deny access. The V3 regression suite exercises representative routes and cross-family substitutions; this matrix is a code review inventory, not a claim that every row has a separate integration test.

| Route group | Required principal / action | Nested scope or privacy rule |
|---|---|---|
| `/health`, `/runtime-config`, `/`, `/assets/*`, `/favicon.ico` | Public metadata and static UI | No family content in response. `/metrics` is disabled publicly unless separately enabled with an operator token. |
| `/auth/managed/start`, `/callback` | Hosted OAuth flow | Provider identity and configured verified-email approval checked before local session; durable pre-login limits. |
| `/auth/managed/session`, `/migrate`, `/logout`, `/revoke-all`; `/auth/me` | Current approved app session | Hosted cookie plus CSRF on unsafe cookie requests; an already-approved legacy bearer can be exchanged once for a rotated cookie. Pre-approval V2 bearers require Google re-login and are then revoked. Revoke-all affects every app session for that account. |
| `/users`, `/auth/login` | Local review mode only | Disabled when hosted Supabase auth is configured. `/auth/logout` revokes the presented app session. |
| `/demo/sample-circle`, `/circles` create/list | Signed-in account | Sample circle is private to creator; list contains only memberships. |
| `/circles/{circle_id}/members` GET | `view_circle` | Membership list for that circle only. |
| `/circles/{circle_id}/members` POST, `/ownership/transfer` | `manage_members` (owner) | Target user must exist; owner role cannot be silently replaced. |
| `/circles/{circle_id}/invitations` POST, `/{invitation_id}/revoke` | `manage_invitations` (owner) | Target account ID/invitation code; pending invite is idempotent, seven-day expiry, owner revocation. |
| `/circles/{circle_id}/invitations` GET | `view_invitations` (owner/editor) | Only that circle; expiration recorded before list. |
| `/invitations` GET, `/{invitation_id}/respond` | Authenticated invited account | Query/response bound to invited account; atomic accept/decline, no replay or role downgrade. |
| `/circles/{circle_id}/audit-logs` | `view_circle` | Circle-filtered; viewer payloads redact medical notes. |
| `/circles/{circle_id}/persons` GET, `/{person_id}/revisions`, `/duplicate-hints` | `view_circle` | Person IDs scoped to circle; viewer responses redact medical notes, including revisions. |
| `/circles/{circle_id}/persons` POST/PATCH, `/{person_id}/places` POST, `/{person_id}/context-links` POST | `edit_person` / `edit_circle` (owner/editor) | Referenced person, event, and place IDs checked in the same circle. |
| Person places, migration map, timeline GET | `view_circle` | Reads join/filter by circle and person ID. |
| Person media POST | `upload_media` (owner/editor) | Person in circle; hosted JPEG/PNG, per-file cap, durable request cap, aggregate circle/uploader caps. Permission rechecked before final insert. |
| Person media GET, `/media-previews`, `/media/{asset_id}/download` | `access_media` | Media row and person constrained to circle; private Storage reads proxied by API. |
| `/access-tickets`, `/ws/circles/{circle_id}` | `access_media` or `use_realtime` | Short-lived, hashed, session-bound ticket; WebSocket revalidates session/membership on each broadcast. |
| Relationships GET | `view_circle` | Only circle relationships and members. |
| Relationships POST/PATCH/DELETE | `edit_circle` (owner/editor) | Endpoints must belong to same circle. Deletion is audited but independent backup/restore is not yet verified. |
| Context events GET, linked persons GET | `view_circle` | Circle-scoped joins. |
| Context events POST | `edit_circle` (owner/editor) | Circle owner/editor action. |
| `/graph/subgraph`, `/timeline`, `/migration-geojson` | `view_circle` | Root person in circle; bounded traversal; durable heavy-read limit; session and membership rechecked before serializing results. |
| Threads GET/POST and messages GET/POST | `view_circle` | Discussion is allowed to viewers; entity/thread IDs constrained to circle. This is intentional collaboration, not record editing. |
| Change requests POST/GET | `view_circle` | Proposed person changes by viewers are allowed except sensitive medical notes; owner/editor review roles and circle-scoped entity IDs apply. |
| Change requests approve/reject | `edit_person` (owner/editor) | Reviewer belongs to circle; sensitive payloads are redacted from viewer reads. |

The API uses a privileged database role, so this matrix is the **per-circle security boundary**. Supabase's current RLS/grants remove direct browser table access, but do not provide a second per-circle check for this runtime role. See [decisions](security-decisions.md) and the [threat model](security-threat-model.md).
