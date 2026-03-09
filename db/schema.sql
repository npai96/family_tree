-- MVP PostgreSQL schema for collaborative genealogy platform
-- Target: PostgreSQL 14+

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Enums
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'circle_role') THEN
    CREATE TYPE circle_role AS ENUM ('owner', 'editor', 'viewer');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'change_request_status') THEN
    CREATE TYPE change_request_status AS ENUM ('pending', 'approved', 'rejected');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'media_kind') THEN
    CREATE TYPE media_kind AS ENUM ('image', 'video', 'audio', 'document');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'upload_status') THEN
    CREATE TYPE upload_status AS ENUM ('initiated', 'uploaded', 'processed', 'failed');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'moderation_status') THEN
    CREATE TYPE moderation_status AS ENUM ('pending', 'approved', 'blocked');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'event_type') THEN
    CREATE TYPE event_type AS ENUM ('world', 'political', 'social', 'technology', 'family');
  END IF;
END $$;

-- Users
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  display_name TEXT NOT NULL,
  email TEXT UNIQUE,
  phone TEXT UNIQUE,
  locale TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT users_has_contact CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

-- Circles and memberships
CREATE TABLE IF NOT EXISTS circles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  description TEXT,
  owner_user_id UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS circle_memberships (
  circle_id UUID NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role circle_role NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (circle_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_circle_memberships_user ON circle_memberships(user_id);

-- Persons and relationships
CREATE TABLE IF NOT EXISTS persons (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  circle_id UUID NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  full_name TEXT NOT NULL,
  religion TEXT,
  sex TEXT,
  birth_date DATE,
  death_date DATE,
  birth_place_name TEXT,
  birth_place_lat DOUBLE PRECISION,
  birth_place_lng DOUBLE PRECISION,
  lived_places_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  occupation TEXT,
  hobbies TEXT,
  personality TEXT,
  medical_notes TEXT,
  bio_text TEXT,
  visibility_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT persons_birth_before_death CHECK (
    death_date IS NULL OR birth_date IS NULL OR death_date >= birth_date
  )
);

CREATE INDEX IF NOT EXISTS idx_persons_circle ON persons(circle_id);
CREATE INDEX IF NOT EXISTS idx_persons_name ON persons(circle_id, full_name);
CREATE INDEX IF NOT EXISTS idx_persons_lived_places_gin ON persons USING GIN (lived_places_json);

CREATE TABLE IF NOT EXISTS relationships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  circle_id UUID NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  from_person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  to_person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  relationship_type TEXT NOT NULL,
  confidence_score NUMERIC(3,2) CHECK (confidence_score >= 0 AND confidence_score <= 1),
  source_note TEXT,
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT relationships_not_self CHECK (from_person_id <> to_person_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_relationships_unique_edge
  ON relationships(circle_id, from_person_id, to_person_id, relationship_type);
CREATE INDEX IF NOT EXISTS idx_relationships_from ON relationships(circle_id, from_person_id);
CREATE INDEX IF NOT EXISTS idx_relationships_to ON relationships(circle_id, to_person_id);

-- Context and timeline
CREATE TABLE IF NOT EXISTS context_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  circle_id UUID NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  title TEXT NOT NULL,
  event_type event_type NOT NULL,
  location_name TEXT,
  lat DOUBLE PRECISION,
  lng DOUBLE PRECISION,
  description TEXT,
  image_media_asset_id UUID,
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_context_events_circle_date ON context_events(circle_id, date);

CREATE TABLE IF NOT EXISTS person_context_links (
  person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  context_event_id UUID NOT NULL REFERENCES context_events(id) ON DELETE CASCADE,
  relevance_note TEXT,
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (person_id, context_event_id)
);

-- Collaboration
CREATE TABLE IF NOT EXISTS change_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  circle_id UUID NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  entity_type TEXT NOT NULL,
  entity_id UUID NOT NULL,
  proposed_patch_json JSONB NOT NULL,
  status change_request_status NOT NULL DEFAULT 'pending',
  proposed_by UUID NOT NULL REFERENCES users(id),
  reviewed_by UUID REFERENCES users(id),
  review_comment TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  reviewed_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_change_requests_circle_status
  ON change_requests(circle_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS entity_revisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type TEXT NOT NULL,
  entity_id UUID NOT NULL,
  revision_no INTEGER NOT NULL,
  snapshot_json JSONB NOT NULL,
  changed_by UUID REFERENCES users(id),
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (entity_type, entity_id, revision_no)
);

CREATE INDEX IF NOT EXISTS idx_entity_revisions_lookup
  ON entity_revisions(entity_type, entity_id, changed_at DESC);

CREATE TABLE IF NOT EXISTS discussion_threads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  circle_id UUID NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  entity_type TEXT NOT NULL,
  entity_id UUID NOT NULL,
  created_by UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (circle_id, entity_type, entity_id)
);

CREATE TABLE IF NOT EXISTS discussion_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  thread_id UUID NOT NULL REFERENCES discussion_threads(id) ON DELETE CASCADE,
  sender_user_id UUID NOT NULL REFERENCES users(id),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_discussion_messages_thread_time
  ON discussion_messages(thread_id, created_at);

-- Media
CREATE TABLE IF NOT EXISTS media_assets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  circle_id UUID NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  owner_user_id UUID NOT NULL REFERENCES users(id),
  attached_entity_type TEXT NOT NULL,
  attached_entity_id UUID NOT NULL,
  kind media_kind NOT NULL,
  storage_key_original TEXT NOT NULL UNIQUE,
  mime_type TEXT NOT NULL,
  bytes BIGINT NOT NULL CHECK (bytes >= 0),
  checksum_sha256 TEXT,
  upload_status upload_status NOT NULL DEFAULT 'initiated',
  moderation_status moderation_status NOT NULL DEFAULT 'pending',
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_media_assets_entity
  ON media_assets(circle_id, attached_entity_type, attached_entity_id);
CREATE INDEX IF NOT EXISTS idx_media_assets_owner
  ON media_assets(owner_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_media_assets_status
  ON media_assets(upload_status, moderation_status);

CREATE TABLE IF NOT EXISTS media_derivatives (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  media_asset_id UUID NOT NULL REFERENCES media_assets(id) ON DELETE CASCADE,
  variant_name TEXT NOT NULL,
  storage_key TEXT NOT NULL UNIQUE,
  mime_type TEXT NOT NULL,
  bytes BIGINT CHECK (bytes >= 0),
  width INTEGER,
  height INTEGER,
  duration_ms INTEGER,
  bitrate INTEGER,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (media_asset_id, variant_name)
);

CREATE INDEX IF NOT EXISTS idx_media_derivatives_media ON media_derivatives(media_asset_id);

-- Outbox for eventual sync (e.g., Postgres -> Neo4j)
CREATE TABLE IF NOT EXISTS outbox_events (
  id BIGSERIAL PRIMARY KEY,
  aggregate_type TEXT NOT NULL,
  aggregate_id UUID NOT NULL,
  event_type TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_outbox_unprocessed
  ON outbox_events(created_at)
  WHERE processed_at IS NULL;

COMMIT;
