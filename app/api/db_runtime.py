from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from app.api.db_config import DEFAULT_SQLITE_PATH, DatabaseConfig, build_database_config, load_database_config

try:
    import psycopg
    from psycopg.errors import IntegrityError as PsycopgIntegrityError
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional at import time in some local envs
    psycopg = None
    PsycopgIntegrityError = None
    dict_row = None


SQLITE_INIT_SQL = """
PRAGMA foreign_keys = ON;

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
  bytes INTEGER NOT NULL,
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
  lat REAL,
  lng REAL,
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
"""


_DATABASE_CONFIG = load_database_config()
POSTGRES_RUNTIME_ENABLED = os.getenv("POSTGRES_RUNTIME_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
INTEGRITY_ERRORS: tuple[type[BaseException], ...] = (
    (sqlite3.IntegrityError,) + ((PsycopgIntegrityError,) if PsycopgIntegrityError is not None else ())
)


def configure_database(*, database_url: str | None = None, db_path: Path | str | None = None) -> DatabaseConfig:
    global _DATABASE_CONFIG

    if database_url is not None:
        _DATABASE_CONFIG = build_database_config(database_url=database_url, db_path_env="")
        return _DATABASE_CONFIG

    if db_path is not None:
        _DATABASE_CONFIG = build_database_config(database_url="", db_path_env=str(db_path))
        return _DATABASE_CONFIG

    _DATABASE_CONFIG = load_database_config()
    return _DATABASE_CONFIG


def get_database_config() -> DatabaseConfig:
    return _DATABASE_CONFIG


def get_db_backend() -> str:
    return _DATABASE_CONFIG.backend


def get_sqlite_path() -> Path:
    return _DATABASE_CONFIG.sqlite_path or DEFAULT_SQLITE_PATH


def _adapt_sql_placeholders(sql: str) -> str:
    if get_db_backend() != "postgres":
        return sql
    return sql.replace("?", "%s")


def get_conn() -> Any:
    if get_db_backend() == "postgres":
        if not POSTGRES_RUNTIME_ENABLED:
            raise RuntimeError(
                "PostgreSQL connection plumbing exists, but runtime is still intentionally gated off. "
                "Keep SQLite as the active API backend for now and continue following docs/POSTGRES_MIGRATION_GUIDE.md."
            )
        if psycopg is None or dict_row is None:
            raise RuntimeError("psycopg is required for PostgreSQL runtime support")
        return psycopg.connect(_DATABASE_CONFIG.database_url, row_factory=dict_row)

    if get_db_backend() != "sqlite":
        raise RuntimeError(
            f"Unsupported runtime backend {get_db_backend()!r}. "
            "Use sqlite for the API runtime for now and follow docs/POSTGRES_MIGRATION_GUIDE.md for the migration path."
        )

    conn = sqlite3.connect(get_sqlite_path())
    conn.row_factory = sqlite3.Row
    return conn


def execute(
    conn: Any,
    sql: str,
    params: Sequence[Any] | None = None,
) -> Any:
    return conn.execute(_adapt_sql_placeholders(sql), tuple(params or ()))


def fetch_one(
    conn: Any,
    sql: str,
    params: Sequence[Any] | None = None,
) -> Any:
    return execute(conn, sql, params).fetchone()


def fetch_all(
    conn: Any,
    sql: str,
    params: Sequence[Any] | None = None,
) -> list[Any]:
    return execute(conn, sql, params).fetchall()


def fetch_value(
    conn: Any,
    sql: str,
    params: Sequence[Any] | None = None,
    *,
    default: Any = None,
) -> Any:
    row = fetch_one(conn, sql, params)
    if row is None:
        return default
    if isinstance(row, dict):
        return next(iter(row.values()), default)
    return row[0]


def execute_many(
    conn: Any,
    sql: str,
    seq_of_params: Iterable[Sequence[Any]],
) -> Any:
    return conn.executemany(_adapt_sql_placeholders(sql), (tuple(params) for params in seq_of_params))


def init_db(media_dir: Path) -> None:
    sqlite_path = get_sqlite_path()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SQLITE_INIT_SQL)
