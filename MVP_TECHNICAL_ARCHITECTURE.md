# Collaborative Genealogy Platform (South Asian Roots)
## MVP Technical Architecture

## 1. Document Scope
This document defines the end-to-end MVP architecture for a collaborative, media-rich genealogy platform:
- Graph-based family structures (people + relationships)
- Timeline and historical context views
- Collaborative editing, suggestions, and discussion
- Secure media upload/storage/transcoding/delivery

This MVP is optimized for:
- Fast subgraph exploration (ancestor/descendant paths)
- Low-friction family collaboration
- Scalable media handling without storing binary media in the database

## 2. Product Goals (MVP)
1. Build and browse family trees as directed relationship graphs.
2. Support person profiles with structured metadata + rich media.
3. Let family members collaboratively propose, review, and apply edits.
4. Support filtered views (subgraphs) rather than forcing full-tree views.
5. Show timeline context for people/places/events.
6. Provide maps for person-level places lived.

## 3. Non-Goals (MVP)
1. Fully automated historical event ingestion from many external feeds.
2. Advanced AI genealogy matching/deduplication.
3. Public social network features outside invited family circles.

## 4. High-Level Architecture
## 4.1 Frontend
- Framework: Next.js (React + TypeScript)
- Visualization:
  - React Flow (interactive graph/subgraph rendering)
  - Virtualized timeline list/grid
- Mapping:
  - Google Maps JavaScript API for person-level places
- State + data:
  - TanStack Query for API caching and async state
  - WebSocket client for realtime collaboration events

## 4.2 Backend
- API service: NestJS (TypeScript)
- API style: REST for MVP (simple integration + explicit contracts)
- Realtime: WebSocket gateway for presence/chat/edit events
- Background jobs: BullMQ workers (Redis-backed)

## 4.3 Data Layer
- PostgreSQL:
  - Users, circles, memberships, permissions
  - Person metadata and denormalized read models
  - Suggestions, comments, audit history, chat metadata
  - Media metadata, upload sessions, derivatives registry
- Neo4j:
  - Person nodes and relationship edges for traversal-heavy queries
  - Fast ancestor/descendant/subgraph expansion
- Redis:
  - Queue broker for async jobs (transcoding, thumbnails, exports)
  - Short-lived cache/session/presence

## 4.4 Media Layer
- Object storage: AWS S3 (or S3-compatible alternative such as Cloudflare R2/MinIO)
- CDN: CloudFront (or equivalent)
- Transcoding:
  - Images: sharp/imagemagick-based worker derivatives
  - Video/audio: ffmpeg workers for streaming-friendly outputs

## 5. Core Domain Model (MVP)
## 5.1 Identity and Collaboration
- `users`
  - id, display_name, email/phone auth identifiers, locale, created_at
- `circles`
  - id, name, description, owner_user_id, created_at
- `circle_memberships`
  - circle_id, user_id, role (`owner`, `editor`, `viewer`)

## 5.2 Genealogy Graph
- `persons` (Postgres read model + profile metadata)
  - id (UUID), circle_id, full_name, religion, sex
  - birth_date, death_date
  - birth_place_name, birth_place_lat, birth_place_lng
  - lived_places_json (array with town/city/region/country + optional coords + date ranges)
  - occupation, hobbies, personality, medical_notes (protected)
  - bio_text
  - visibility_flags (private fields policy)
- Neo4j `Person` node mirror
  - person_id, circle_id, display fields needed for fast graph rendering
- `relationships`
  - id, circle_id, from_person_id, to_person_id
  - relationship_type (`parent`, `child`, `spouse`, `sibling`, etc.)
  - confidence_score (0-1), source_note
  - created_by, created_at
- Neo4j directed relationship mirror
  - `(:Person)-[:REL {type, confidence}]->(:Person)`

## 5.3 Context and Timeline
- `context_events`
  - id, circle_id, date, title, event_type (`world`, `political`, `social`, `technology`, `family`)
  - location_name, lat, lng, description
- `person_context_links`
  - person_id, context_event_id, relevance_note

## 5.4 Collaboration and Audit
- `change_requests`
  - id, circle_id, entity_type, entity_id
  - proposed_patch_json, status (`pending`, `approved`, `rejected`)
  - proposed_by, reviewed_by, timestamps
- `entity_revisions`
  - id, entity_type, entity_id, revision_no, snapshot_json, changed_by, changed_at
- `discussion_threads`, `discussion_messages`
  - per person/relationship/change_request chat threads

## 5.5 Media
- `media_assets`
  - id, circle_id, owner_user_id, attached_entity_type, attached_entity_id
  - kind (`image`, `video`, `audio`, `document`)
  - storage_key_original, mime_type, bytes, checksum_sha256
  - upload_status (`initiated`, `uploaded`, `processed`, `failed`)
  - moderation_status (`pending`, `approved`, `blocked`)
- `media_derivatives`
  - id, media_asset_id, variant_name (`thumb_200`, `image_1200`, `video_hls_720p`, `audio_aac`)
  - storage_key, mime_type, bytes, width, height, duration_ms, bitrate

## 6. Graph and Query Strategy
1. Postgres is source of truth for metadata and permissions.
2. Neo4j is traversal/read accelerator for graph operations.
3. Write flow for graph entities:
   - API validates + writes to Postgres in transaction.
   - Emits outbox event.
   - Sync worker applies corresponding change to Neo4j.
4. Read flow:
   - Authorization from Postgres.
   - Subgraph traversal from Neo4j.
   - Profile/media metadata hydration from Postgres.

## 7. API Design (MVP)
## 7.1 Auth and Membership
- `POST /auth/login`
- `POST /auth/refresh`
- `GET /circles/:id/members`
- `POST /circles/:id/members`

## 7.2 Persons and Relationships
- `GET /circles/:id/persons/:personId`
- `POST /circles/:id/persons`
- `PATCH /circles/:id/persons/:personId`
- `POST /circles/:id/relationships`
- `DELETE /circles/:id/relationships/:relationshipId`

## 7.3 Subgraph and Paths
- `GET /circles/:id/graph/subgraph?rootPersonId=&direction=ancestors|descendants|both&depth=`
- `GET /circles/:id/graph/path?fromPersonId=&toPersonId=`

## 7.4 Timeline and Context
- `GET /circles/:id/context-events?from=&to=`
- `POST /circles/:id/context-events`
- `POST /circles/:id/persons/:personId/context-links`

## 7.5 Collaboration
- `POST /circles/:id/change-requests`
- `POST /circles/:id/change-requests/:crId/approve`
- `POST /circles/:id/change-requests/:crId/reject`
- `GET /circles/:id/discussions/:threadId/messages`
- `POST /circles/:id/discussions/:threadId/messages`

## 7.6 Media
- `POST /circles/:id/media/initiate-upload`
- `POST /circles/:id/media/:mediaId/complete-upload`
- `GET /circles/:id/media/:mediaId`
- `GET /circles/:id/media/:mediaId/access-url?variant=`

## 8. Media Pipeline (Detailed)
## 8.1 Why media is not stored in DB
Binary media in relational/graph tables causes:
- Storage bloat and slower backups/restores
- Poor CDN integration
- Expensive DB I/O for large file transfers

Therefore, DB stores references/metadata only; object storage holds bytes.

## 8.2 Storage Layout
Bucket pattern:
- `s3://genealogy-media-{env}/circles/{circleId}/persons/{personId}/{mediaId}/original`
- `s3://.../{mediaId}/derivatives/{variant}`
- `s3://.../exports/migrations/{exportId}/...`

## 8.3 Upload Flow (Signed URL)
1. Client calls `POST /media/initiate-upload` with file metadata.
2. Backend validates:
   - membership/role
   - mime/size policy
   - quota
3. Backend creates `media_assets` row with status `initiated`.
4. Backend returns short-lived pre-signed PUT URL (e.g., 10 min).
5. Client uploads directly to S3 via signed URL.
6. Client calls `POST /media/:id/complete-upload`.
7. Backend verifies object existence/checksum and marks `uploaded`.
8. Backend enqueues processing job.

## 8.4 Processing and Derivatives
Worker consumes processing job:
1. Inspect media metadata (ffprobe/exif).
2. Create derivatives by type:
   - Image:
     - `thumb_200.webp`
     - `medium_1200.webp`
     - keep original
   - Video:
     - poster image (`poster_1080.jpg`)
     - adaptive HLS outputs (360p/720p)
   - Audio:
     - `audio_aac_128.m4a`
     - optional waveform JSON
3. Upload derivatives to S3.
4. Persist `media_derivatives`.
5. Mark `media_assets.upload_status = processed`.

## 8.5 Delivery (Signed GET + CDN)
1. Client requests asset playback URL:
   - `GET /media/:id/access-url?variant=video_hls_720p`
2. Backend checks access policy and returns:
   - signed CDN URL (preferred), or
   - signed S3 GET URL
3. Client renders best variant for device/network.

## 8.6 Security Controls
- Buckets are private (no public ACLs).
- Signed URLs are short-lived.
- Virus/malware scan stage for uploaded binaries (MVP can start async).
- Content-type allowlist and max size checks at initiation.
- Optional perceptual hash/dedupe for repeated uploads.

## 8.7 Cost and Performance Controls
- Lifecycle:
  - retain originals in standard tier
  - move rarely accessed originals to infrequent access after N days
- Cache control headers on derivatives
- Derivative-first rendering to minimize bandwidth
- Async deletion for orphaned media

## 9. Collaboration Model
1. Direct edits by `owner/editor` roles.
2. Optional “suggestion mode” for uncertain records:
   - proposed edits become `change_requests`.
   - reviewers approve/reject with comments.
3. Every accepted change creates immutable revision entries.
4. Per-entity chat thread supports oral-history reconciliation.

## 10. Privacy and Permissions
## 10.1 Roles
- `owner`: full control (members, policy, destructive actions)
- `editor`: create/update persons, relationships, events, media
- `viewer`: read-only

## 10.2 Sensitive Fields
- `medical_notes` hidden by default and role-gated.
- Living-person privacy flags for profile fields/media visibility.
- Audit log for all sensitive field reads/changes (recommended for v1.1).

## 11. Timeline + Maps Architecture
## 11.1 Timeline
- Build merged timeline from:
  - person life events (birth, migration, death)
  - linked context events
- Render with date-based vertical axis and viewport virtualization.

## 11.2 Maps
- Store coordinates per birth/lived place when available.
- Map panel for selected person:
  - markers + chronological path segments
- Migration export job:
  - worker generates geojson and optional animated video artifact

## 12. Realtime Architecture
- WebSocket channels scoped by circle and entity thread.
- Event types:
  - `presence.updated`
  - `person.updated`
  - `relationship.updated`
  - `change_request.updated`
  - `discussion.message.created`
- Conflict strategy (MVP):
  - optimistic UI + server version check
  - reject stale writes and request client refetch

## 13. Deployment Architecture
## 13.1 Environments
- `dev`, `staging`, `prod`
- Separate DB/Neo4j/Redis/S3 resources per environment

## 13.2 Runtime
- Frontend on Vercel or containerized Next.js
- API + workers on ECS/Fargate or Kubernetes
- Managed Postgres + Neo4j AuraDB + managed Redis

## 13.3 Observability
- Structured logs (request_id, user_id, circle_id)
- Metrics:
  - API latency
  - graph query latency
  - transcoding queue depth
  - derivative success/failure rates
- Error monitoring via Sentry

## 14. MVP Scale Assumptions
- 5k-50k persons per large circle over time
- Typical active sessions view 50-500 nodes at a time
- Most tree views are subgraphs, not full graph render
- Media-heavy profiles require CDN and derivative-first strategy

## 15. Testing Strategy
1. Unit:
   - relationship validation rules
   - permission checks
   - media policy validators
2. Integration:
   - Postgres + Neo4j sync/outbox correctness
   - signed upload/complete/process flow
3. E2E:
   - create person -> add relationships -> upload media -> view subgraph
4. Load:
   - concurrent subgraph queries
   - queue backlog handling for transcoding bursts

## 16. MVP Delivery Plan (12 Weeks)
1. Weeks 1-2: foundation
   - repo scaffolding, auth, circle membership, base schema
2. Weeks 3-5: genealogy core
   - person CRUD, relationships, Neo4j sync, subgraph APIs
3. Weeks 6-7: collaboration
   - change requests, revisions, discussions, realtime events
4. Weeks 8-9: media pipeline
   - signed uploads, worker derivatives, secure playback URLs
5. Weeks 10-11: timeline + maps
   - context events, linked timeline, person path map
6. Week 12: hardening
   - performance tuning, observability, security checks, launch checklist

## 17. MVP Open Decisions
1. Auth method for family onboarding:
   - email OTP, phone OTP, or social login
2. Relationship taxonomy depth:
   - broad generic types vs culturally specific relations
3. Moderation depth in MVP:
   - manual only vs basic automated content checks
4. Hosting preference:
   - fully AWS-native vs mixed managed providers

## 18. Initial Implementation Defaults
- Frontend: Next.js + React Flow + TanStack Query
- Backend: NestJS REST + WebSocket gateway
- Data: Postgres + Neo4j + Redis
- Media: S3 + CloudFront + ffmpeg workers
- Auth: JWT with rotating refresh tokens
- Access model: role-based by circle

This configuration is sufficient to launch a collaborative, media-capable genealogy MVP and safely evolve into a larger production platform.
