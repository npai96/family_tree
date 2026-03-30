-- Runtime PostgreSQL schema matching the current SQLite-backed API shape.
-- This is intentionally closer to app/api/main.py than db/schema.sql.
-- Goal: create a low-risk migration target for the existing API before deeper schema redesign.

BEGIN;

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS circles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS circle_memberships (
  circle_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
  created_at TEXT NOT NULL,
  PRIMARY KEY (circle_id, user_id),
  FOREIGN KEY (circle_id) REFERENCES circles(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS persons (
  id TEXT PRIMARY KEY,
  circle_id TEXT NOT NULL,
  full_name TEXT NOT NULL,
  religion TEXT,
  sex TEXT,
  birth_date TEXT,
  death_date TEXT,
  birth_place TEXT,
  occupation TEXT,
  hobbies TEXT,
  personality TEXT,
  medical_notes TEXT,
  bio_text TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (circle_id) REFERENCES circles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS relationships (
  id TEXT PRIMARY KEY,
  circle_id TEXT NOT NULL,
  from_person_id TEXT NOT NULL,
  to_person_id TEXT NOT NULL,
  relationship_type TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (circle_id, from_person_id, to_person_id, relationship_type),
  CHECK (from_person_id <> to_person_id),
  FOREIGN KEY (circle_id) REFERENCES circles(id) ON DELETE CASCADE,
  FOREIGN KEY (from_person_id) REFERENCES persons(id) ON DELETE CASCADE,
  FOREIGN KEY (to_person_id) REFERENCES persons(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS change_requests (
  id TEXT PRIMARY KEY,
  circle_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  proposed_patch_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
  proposed_by TEXT NOT NULL,
  reviewed_by TEXT,
  review_comment TEXT,
  created_at TEXT NOT NULL,
  reviewed_at TEXT,
  FOREIGN KEY (circle_id) REFERENCES circles(id) ON DELETE CASCADE,
  FOREIGN KEY (proposed_by) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS context_events (
  id TEXT PRIMARY KEY,
  circle_id TEXT NOT NULL,
  date TEXT NOT NULL,
  title TEXT NOT NULL,
  event_type TEXT NOT NULL CHECK (event_type IN ('world', 'political', 'social', 'technology', 'family')),
  location_name TEXT,
  description TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (circle_id) REFERENCES circles(id) ON DELETE CASCADE,
  FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS person_context_links (
  person_id TEXT NOT NULL,
  context_event_id TEXT NOT NULL,
  circle_id TEXT NOT NULL,
  relevance_note TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (person_id, context_event_id),
  FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE CASCADE,
  FOREIGN KEY (context_event_id) REFERENCES context_events(id) ON DELETE CASCADE,
  FOREIGN KEY (circle_id) REFERENCES circles(id) ON DELETE CASCADE,
  FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS media_assets (
  id TEXT PRIMARY KEY,
  circle_id TEXT NOT NULL,
  person_id TEXT NOT NULL,
  uploader_user_id TEXT NOT NULL,
  original_filename TEXT NOT NULL,
  stored_filename TEXT NOT NULL,
  mime_type TEXT,
  bytes BIGINT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (circle_id) REFERENCES circles(id) ON DELETE CASCADE,
  FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE CASCADE,
  FOREIGN KEY (uploader_user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS person_places (
  id TEXT PRIMARY KEY,
  circle_id TEXT NOT NULL,
  person_id TEXT NOT NULL,
  place_name TEXT NOT NULL,
  country TEXT,
  lat DOUBLE PRECISION,
  lng DOUBLE PRECISION,
  from_date TEXT,
  to_date TEXT,
  notes TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (circle_id) REFERENCES circles(id) ON DELETE CASCADE,
  FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE CASCADE,
  FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS discussion_threads (
  id TEXT PRIMARY KEY,
  circle_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (circle_id, entity_type, entity_id),
  FOREIGN KEY (circle_id) REFERENCES circles(id) ON DELETE CASCADE,
  FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS discussion_messages (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  sender_user_id TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (thread_id) REFERENCES discussion_threads(id) ON DELETE CASCADE,
  FOREIGN KEY (sender_user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS entity_revisions (
  id TEXT PRIMARY KEY,
  circle_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  revision_no INTEGER NOT NULL,
  snapshot_json TEXT NOT NULL,
  reason TEXT,
  changed_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (entity_type, entity_id, revision_no),
  FOREIGN KEY (circle_id) REFERENCES circles(id) ON DELETE CASCADE,
  FOREIGN KEY (changed_by) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS auth_sessions (
  token TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS circle_invitations (
  id TEXT PRIMARY KEY,
  circle_id TEXT NOT NULL,
  invited_user_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('editor', 'viewer')),
  status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'declined', 'cancelled')),
  invited_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  responded_at TEXT,
  UNIQUE (circle_id, invited_user_id, status),
  FOREIGN KEY (circle_id) REFERENCES circles(id) ON DELETE CASCADE,
  FOREIGN KEY (invited_user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (invited_by) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id TEXT PRIMARY KEY,
  circle_id TEXT NOT NULL,
  actor_user_id TEXT NOT NULL,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT,
  payload_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (circle_id) REFERENCES circles(id) ON DELETE CASCADE,
  FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE CASCADE
);

COMMIT;
