"""Durable abuse limits and invitation lifecycle for the small hosted cohort.

The database, rather than a Python process, owns these counters.  In particular,
the atomic UPSERT and the storage row locks work across Render workers/restarts.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

from app.api.db_runtime import execute, fetch_one, fetch_value, get_conn


@dataclass(frozen=True)
class RateLimitPolicy:
    requests: int
    window_seconds: int


# Deliberately generous for a small approved cohort.  Limits are per trusted
# subject supplied by the caller (user ID after authentication, peer IP before).
RATE_LIMITS = {
    "auth.start": RateLimitPolicy(30, 3600),
    "auth.callback": RateLimitPolicy(30, 3600),
    "invitation.create": RateLimitPolicy(20, 86400),
    "invitation.respond": RateLimitPolicy(40, 86400),
    "upload": RateLimitPolicy(30, 86400),
    "read.heavy": RateLimitPolicy(240, 60),
}

INVITATION_TTL = timedelta(days=7)
MAX_CIRCLE_MEDIA_BYTES = 250 * 1024 * 1024
MAX_ACCOUNT_MEDIA_BYTES = 100 * 1024 * 1024


def _now(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("Security timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def enforce_rate_limit(
    scope: str,
    subject: str,
    *,
    policy: RateLimitPolicy | None = None,
    now: datetime | None = None,
) -> None:
    """Consume one attempt and raise 429 on excess.

    This owns its transaction so a caller's subsequent HTTPException cannot roll
    back the counter.  Call before opening a separate write transaction.
    """
    policy = policy or RATE_LIMITS[scope]
    if policy.requests < 1 or policy.window_seconds < 1 or policy.window_seconds > 86400:
        raise ValueError("Invalid rate-limit policy")
    if not subject:
        raise ValueError("Rate-limit subject cannot be empty")
    timestamp = int(_now(now).timestamp())
    window_start = timestamp - timestamp % policy.window_seconds
    # Hosted deployments already have a server-only secret.  HMAC avoids
    # making low-entropy subjects such as peer IPs trivially reversible from a
    # database snapshot.  Local review mode has no such key and uses SHA-256.
    hash_key = os.getenv("ABUSE_SUBJECT_HASH_KEY") or os.getenv("SUPABASE_SECRET_KEY")
    subject_bytes = f"{scope}\x00{subject}".encode()
    subject_hash = (hmac.new(hash_key.encode(), subject_bytes, hashlib.sha256).hexdigest()
                    if hash_key else hashlib.sha256(subject_bytes).hexdigest())
    with get_conn() as conn:
        result = fetch_one(
            conn,
            """
            INSERT INTO security_rate_limit_counters
              (scope, subject_hash, window_start, request_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT (scope, subject_hash, window_start)
            DO UPDATE SET request_count = security_rate_limit_counters.request_count + 1
              WHERE security_rate_limit_counters.request_count < ?
            RETURNING request_count
            """,
            (scope, subject_hash, window_start, policy.requests),
        )
        # At most one day of counters is needed for every configured window.
        execute(conn, "DELETE FROM security_rate_limit_counters WHERE window_start < ?", (timestamp - 86400,))
    if result is None:
        retry_after = max(1, window_start + policy.window_seconds - timestamp)
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def require_storage_capacity(
    conn,
    *,
    circle_id: str,
    account_id: str,
    additional_bytes: int,
    circle_limit: int = MAX_CIRCLE_MEDIA_BYTES,
    account_limit: int = MAX_ACCOUNT_MEDIA_BYTES,
) -> None:
    """Check aggregate media quota inside the *same* transaction as asset INSERT.

    The no-op updates lock the account, then the circle.  This serializes quota
    checks across workers before reading SUM(media_assets.bytes).  All upload
    paths must use this helper immediately before their metadata INSERT.
    """
    if additional_bytes < 0 or circle_limit < 1 or account_limit < 1:
        raise ValueError("Invalid storage quota")
    if execute(conn, "UPDATE users SET display_name = display_name WHERE id = ?", (account_id,)).rowcount != 1:
        raise HTTPException(status_code=404, detail="Account not found")
    if execute(conn, "UPDATE circles SET name = name WHERE id = ?", (circle_id,)).rowcount != 1:
        raise HTTPException(status_code=404, detail="Circle not found")
    circle_used = int(fetch_value(conn, "SELECT COALESCE(SUM(bytes), 0) FROM media_assets WHERE circle_id = ?", (circle_id,)))
    account_used = int(fetch_value(conn, "SELECT COALESCE(SUM(bytes), 0) FROM media_assets WHERE uploader_user_id = ?", (account_id,)))
    if circle_used + additional_bytes > circle_limit:
        raise HTTPException(status_code=413, detail="Circle media storage limit reached")
    if account_used + additional_bytes > account_limit:
        raise HTTPException(status_code=413, detail="Account media storage limit reached")


def expire_pending_invitations(conn, *, now: datetime | None = None, circle_id: str | None = None) -> int:
    """Record expiry in owner-visible history; a new invitation can then be made."""
    at = _now(now).isoformat()
    if circle_id is None:
        result = execute(
            conn,
            """UPDATE circle_invitations SET status = 'cancelled', responded_at = ?, expired_at = ?
               WHERE status = 'pending' AND expires_at <= ?""",
            (at, at, at),
        )
    else:
        result = execute(
            conn,
            """UPDATE circle_invitations SET status = 'cancelled', responded_at = ?, expired_at = ?
               WHERE status = 'pending' AND circle_id = ? AND expires_at <= ?""",
            (at, at, circle_id, at),
        )
    return max(0, result.rowcount)


def create_invitation_record(
    conn,
    *,
    circle_id: str,
    invited_user_id: str,
    role: str,
    invited_by: str,
    now: datetime | None = None,
) -> dict:
    """Create once; an identical retry returns the same pending invitation."""
    if role not in {"editor", "viewer"}:
        raise ValueError("Only editor and viewer invitations are allowed")
    at = _now(now)
    expire_pending_invitations(conn, now=at, circle_id=circle_id)
    existing = fetch_one(
        conn,
        """SELECT * FROM circle_invitations
           WHERE circle_id = ? AND invited_user_id = ? AND status = 'pending'""",
        (circle_id, invited_user_id),
    )
    if existing:
        if existing["role"] != role:
            raise HTTPException(status_code=409, detail="Revoke the pending invitation before changing its role")
        result = dict(existing)
        result["newly_created"] = False
        return result
    invitation_id = str(uuid4())
    created = fetch_one(
        conn,
        """INSERT INTO circle_invitations
             (id, circle_id, invited_user_id, role, status, invited_by, created_at,
              responded_at, expires_at, revoked_at, expired_at)
           VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, ?, NULL, NULL)
           ON CONFLICT DO NOTHING RETURNING *""",
        (invitation_id, circle_id, invited_user_id, role, invited_by, at.isoformat(),
         (at + INVITATION_TTL).isoformat()),
    )
    if created is not None:
        result = dict(created)
        result["newly_created"] = True
        return result
    # Concurrent retry won the partial unique index.  Return the same row for
    # an identical request; never create two pending invitations.
    existing = fetch_one(
        conn,
        """SELECT * FROM circle_invitations
           WHERE circle_id = ? AND invited_user_id = ? AND status = 'pending'""",
        (circle_id, invited_user_id),
    )
    if existing is None:
        raise HTTPException(status_code=409, detail="Invitation could not be created")
    if existing["role"] != role:
        raise HTTPException(status_code=409, detail="Revoke the pending invitation before changing its role")
    result = dict(existing)
    result["newly_created"] = False
    return result


def claim_invitation_response(
    conn,
    *,
    invitation_id: str,
    invited_user_id: str,
    action: str,
    now: datetime | None = None,
) -> dict:
    """Atomically consume an invitation before membership changes in this transaction."""
    if action not in {"accept", "decline"}:
        raise ValueError("Invalid invitation action")
    row = fetch_one(conn, "SELECT * FROM circle_invitations WHERE id = ?", (invitation_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if row["invited_user_id"] != invited_user_id:
        raise HTTPException(status_code=403, detail="Not allowed to respond to this invitation")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail="Invitation already responded")
    at = _now(now)
    if at >= datetime.fromisoformat(row["expires_at"]):
        raise HTTPException(status_code=410, detail="Invitation expired")
    updated = fetch_one(
        conn,
        """UPDATE circle_invitations SET status = ?, responded_at = ?
           WHERE id = ? AND invited_user_id = ? AND status = 'pending' AND expires_at > ?
           RETURNING *""",
        ("accepted" if action == "accept" else "declined", at.isoformat(),
         invitation_id, invited_user_id, at.isoformat()),
    )
    if updated is None:
        raise HTTPException(status_code=409, detail="Invitation already responded")
    return dict(updated)


def revoke_invitation_record(
    conn,
    *,
    invitation_id: str,
    circle_id: str,
    now: datetime | None = None,
) -> dict:
    """Owner authorization is required by the caller before invoking this helper."""
    row = fetch_one(conn, "SELECT * FROM circle_invitations WHERE id = ? AND circle_id = ?", (invitation_id, circle_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail="Invitation already responded")
    at = _now(now).isoformat()
    updated = fetch_one(
        conn,
        """UPDATE circle_invitations
           SET status = 'cancelled', responded_at = ?, revoked_at = ?
           WHERE id = ? AND circle_id = ? AND status = 'pending' RETURNING *""",
        (at, at, invitation_id, circle_id),
    )
    if updated is None:
        raise HTTPException(status_code=409, detail="Invitation already responded")
    return dict(updated)
