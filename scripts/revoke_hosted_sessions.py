"""Manually revoke a Supabase account's app sessions after removing hosted access.

Run from the repository root with the production database environment already set.
The default is a dry run; --apply performs the update. Never paste credentials here.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from uuid import UUID

from app.api.db_runtime import execute, fetch_one, get_conn, get_db_backend


def revoke_sessions(conn, user_id: str, now: str, *, apply: bool) -> int:
    row = fetch_one(conn, """SELECT COUNT(*) AS count FROM auth_sessions
        WHERE user_id = ? AND auth_source = 'supabase'
          AND revoked_at IS NULL AND expires_at > ?""", (user_id, now))
    count = int(row["count"])
    if apply and count:
        execute(conn, """UPDATE auth_sessions SET revoked_at = ?
            WHERE user_id = ? AND auth_source = 'supabase' AND revoked_at IS NULL""",
                (now, user_id))
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_id", type=UUID, help="Supabase Auth user UUID")
    parser.add_argument("--apply", action="store_true", help="Revoke all active hosted app sessions")
    args = parser.parse_args()

    if os.getenv("APP_ENV") != "production" or not os.getenv("SUPABASE_URL") or get_db_backend() != "postgres":
        parser.error("Requires the production Supabase/Postgres environment")

    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        count = revoke_sessions(conn, str(args.user_id), now, apply=args.apply)

    verb = "Revoked" if args.apply else "Would revoke"
    print(f"{verb} {count} active hosted app session(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
