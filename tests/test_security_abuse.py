"""Durable limits and invitation lifecycle against the production-shaped schema."""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.db_runtime import configure_database, execute, fetch_all, fetch_one, get_conn, init_db
from app.api.security_abuse import (
    RateLimitPolicy,
    claim_invitation_response,
    create_invitation_record,
    enforce_rate_limit,
    expire_pending_invitations,
    require_storage_capacity,
    revoke_invitation_record,
)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "abuse.db"
    configure_database(db_path=path)
    init_db(tmp_path / "media")
    at = datetime(2026, 9, 29, tzinfo=timezone.utc).isoformat()
    with get_conn() as conn:
        for user_id in ("owner", "guest", "stranger", "second"):
            execute(conn, "INSERT INTO users (id, display_name, created_at) VALUES (?, ?, ?)", (user_id, user_id, at))
        for circle_id in ("circle-a", "circle-b"):
            execute(conn, "INSERT INTO circles (id, name, created_at) VALUES (?, ?, ?)", (circle_id, circle_id, at))
        for person_id, circle_id in (("person-a", "circle-a"), ("person-b", "circle-b")):
            execute(conn, "INSERT INTO persons (id, circle_id, full_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (person_id, circle_id, person_id, at, at))
    return path


def _add_media(conn, asset_id: str, circle_id: str, person_id: str, uploader: str, size: int) -> None:
    execute(conn,
            """INSERT INTO media_assets
               (id, circle_id, person_id, uploader_user_id, original_filename, stored_filename,
                mime_type, bytes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'image/png', ?, ?)""",
            (asset_id, circle_id, person_id, uploader, asset_id + ".png", asset_id + ".png",
             size, datetime(2026, 9, 29, tzinfo=timezone.utc).isoformat()))


def test_rate_limit_is_durable_subject_scoped_and_resets(database: Path) -> None:
    at = datetime(2026, 9, 29, 12, 0, 1, tzinfo=timezone.utc)
    limit = RateLimitPolicy(2, 60)
    enforce_rate_limit("upload", "owner", policy=limit, now=at)
    enforce_rate_limit("upload", "owner", policy=limit, now=at)
    with pytest.raises(HTTPException) as error:
        enforce_rate_limit("upload", "owner", policy=limit, now=at)
    assert error.value.status_code == 429
    assert error.value.headers == {"Retry-After": "59"}
    # The rejected attempt did not roll the committed count back.
    with get_conn() as conn:
        row = fetch_one(conn, "SELECT subject_hash, request_count FROM security_rate_limit_counters")
        assert row["request_count"] == 2
        assert "owner" not in row["subject_hash"]
    enforce_rate_limit("upload", "guest", policy=limit, now=at)
    enforce_rate_limit("upload", "owner", policy=limit, now=at + timedelta(seconds=60))


def test_storage_quota_checks_circle_and_account_across_circles(database: Path) -> None:
    with get_conn() as conn:
        _add_media(conn, "first", "circle-a", "person-a", "owner", 7)
    with get_conn() as conn:
        require_storage_capacity(conn, circle_id="circle-a", account_id="owner", additional_bytes=3,
                                 circle_limit=10, account_limit=20)
        _add_media(conn, "second", "circle-a", "person-a", "owner", 3)
    with get_conn() as conn:
        with pytest.raises(HTTPException, match="Circle media storage limit reached") as error:
            require_storage_capacity(conn, circle_id="circle-a", account_id="guest", additional_bytes=1,
                                     circle_limit=10, account_limit=20)
        assert error.value.status_code == 413
    with get_conn() as conn:
        with pytest.raises(HTTPException, match="Account media storage limit reached") as error:
            require_storage_capacity(conn, circle_id="circle-b", account_id="owner", additional_bytes=1,
                                     circle_limit=20, account_limit=10)
        assert error.value.status_code == 413
    with get_conn() as conn:
        require_storage_capacity(conn, circle_id="circle-b", account_id="guest", additional_bytes=1,
                                 circle_limit=20, account_limit=10)


def test_invitation_replay_wrong_account_expiry_and_reinvite(database: Path) -> None:
    at = datetime(2026, 9, 29, tzinfo=timezone.utc)
    with get_conn() as conn:
        first = create_invitation_record(conn, circle_id="circle-a", invited_user_id="guest",
                                         role="viewer", invited_by="owner", now=at)
        retry = create_invitation_record(conn, circle_id="circle-a", invited_user_id="guest",
                                         role="viewer", invited_by="owner", now=at)
        assert retry["id"] == first["id"]
        assert first["newly_created"] is True and retry["newly_created"] is False
        with pytest.raises(HTTPException) as error:
            create_invitation_record(conn, circle_id="circle-a", invited_user_id="guest",
                                     role="editor", invited_by="owner", now=at)
        assert error.value.status_code == 409
    with get_conn() as conn:
        with pytest.raises(HTTPException) as error:
            claim_invitation_response(conn, invitation_id=first["id"], invited_user_id="stranger",
                                      action="accept", now=at)
        assert error.value.status_code == 403
    with get_conn() as conn:
        with pytest.raises(HTTPException) as error:
            claim_invitation_response(conn, invitation_id=first["id"], invited_user_id="guest",
                                      action="accept", now=at + timedelta(days=8))
        assert error.value.status_code == 410
    with get_conn() as conn:
        assert expire_pending_invitations(conn, now=at + timedelta(days=8), circle_id="circle-a") == 1
        old = fetch_one(conn, "SELECT * FROM circle_invitations WHERE id = ?", (first["id"],))
        assert old["status"] == "cancelled" and old["expired_at"]
        second = create_invitation_record(conn, circle_id="circle-a", invited_user_id="guest",
                                          role="editor", invited_by="owner", now=at + timedelta(days=8))
        assert second["id"] != first["id"]
    with get_conn() as conn:
        accepted = claim_invitation_response(conn, invitation_id=second["id"], invited_user_id="guest",
                                             action="accept", now=at + timedelta(days=8))
        assert accepted["status"] == "accepted" and accepted["role"] == "editor"
    with get_conn() as conn:
        with pytest.raises(HTTPException) as error:
            claim_invitation_response(conn, invitation_id=second["id"], invited_user_id="guest",
                                      action="accept", now=at + timedelta(days=8))
        assert error.value.status_code == 409
        # An accepted invitation is immutable; a later invitation has its own ID.
        third = create_invitation_record(conn, circle_id="circle-a", invited_user_id="guest",
                                         role="viewer", invited_by="owner", now=at + timedelta(days=9))
        assert third["id"] not in {first["id"], second["id"]}


def test_revoke_keeps_history_and_is_one_way(database: Path) -> None:
    at = datetime(2026, 9, 29, tzinfo=timezone.utc)
    with get_conn() as conn:
        invite = create_invitation_record(conn, circle_id="circle-a", invited_user_id="guest",
                                          role="viewer", invited_by="owner", now=at)
    with get_conn() as conn:
        revoked = revoke_invitation_record(conn, invitation_id=invite["id"], circle_id="circle-a", now=at)
        assert revoked["status"] == "cancelled" and revoked["revoked_at"]
    with get_conn() as conn:
        with pytest.raises(HTTPException) as error:
            claim_invitation_response(conn, invitation_id=invite["id"], invited_user_id="guest",
                                      action="accept", now=at)
        assert error.value.status_code == 409
        history = fetch_all(conn, "SELECT id, status, revoked_at FROM circle_invitations WHERE circle_id = ?", ("circle-a",))
        assert len(history) == 1 and history[0]["revoked_at"]
        replacement = create_invitation_record(conn, circle_id="circle-a", invited_user_id="guest",
                                               role="viewer", invited_by="owner", now=at + timedelta(hours=1))
        assert replacement["id"] != invite["id"]


def test_old_sqlite_invites_migrate_without_erasing_history(database: Path, tmp_path: Path) -> None:
    # Simulate the existing V2 table and its all-status unique constraint.
    with get_conn() as conn:
        execute(conn, "DROP TABLE circle_invitations")
        execute(conn, """CREATE TABLE circle_invitations (
          id TEXT PRIMARY KEY, circle_id TEXT NOT NULL, invited_user_id TEXT NOT NULL,
          role TEXT NOT NULL, status TEXT NOT NULL, invited_by TEXT NOT NULL,
          created_at TEXT NOT NULL, responded_at TEXT,
          UNIQUE (circle_id, invited_user_id, status))""")
        execute(conn, """INSERT INTO circle_invitations
            (id, circle_id, invited_user_id, role, status, invited_by, created_at)
            VALUES ('legacy', 'circle-a', 'guest', 'viewer', 'pending', 'owner', '2026-09-01T00:00:00+00:00')""")
    init_db(tmp_path / "media")
    with get_conn() as conn:
        row = fetch_one(conn, "SELECT * FROM circle_invitations WHERE id = 'legacy'")
        assert row["expires_at"] == row["created_at"]
        assert row["status"] == "pending"
        assert expire_pending_invitations(conn, now=datetime(2026, 9, 29, tzinfo=timezone.utc)) == 1
        newer = create_invitation_record(conn, circle_id="circle-a", invited_user_id="guest",
                                         role="viewer", invited_by="owner")
        assert newer["id"] != "legacy"
    init_db(tmp_path / "media")  # idempotent on next startup


def test_partial_pending_index_rejects_concurrent_duplicate(database: Path) -> None:
    at = datetime(2026, 9, 29, tzinfo=timezone.utc)
    with get_conn() as conn:
        invite = create_invitation_record(conn, circle_id="circle-a", invited_user_id="guest",
                                          role="viewer", invited_by="owner", now=at)
    with pytest.raises(sqlite3.IntegrityError):
        with get_conn() as conn:
            execute(conn,
                    """INSERT INTO circle_invitations
                       (id, circle_id, invited_user_id, role, status, invited_by, created_at, expires_at)
                       VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
                    ("duplicate", "circle-a", "guest", "viewer", "owner", at.isoformat(), invite["expires_at"]))
