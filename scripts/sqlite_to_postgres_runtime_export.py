#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


TABLES = [
    "users",
    "circles",
    "circle_memberships",
    "persons",
    "relationships",
    "change_requests",
    "context_events",
    "person_context_links",
    "media_assets",
    "person_places",
    "discussion_threads",
    "discussion_messages",
    "entity_revisions",
    "auth_sessions",
    "circle_invitations",
    "audit_logs",
]


def sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def export_table(conn: sqlite3.Connection, table_name: str) -> str:
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]
    rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()

    if not rows:
        return f"-- {table_name}: no rows\n"

    column_list = ", ".join(columns)
    value_rows = []
    for row in rows:
        value_rows.append(f"({', '.join(sql_literal(value) for value in row)})")

    return (
        f"-- {table_name}: {len(rows)} rows\n"
        f"INSERT INTO {table_name} ({column_list}) VALUES\n  "
        + ",\n  ".join(value_rows)
        + ";\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Export current SQLite runtime data into PostgreSQL INSERT statements.")
    parser.add_argument("--sqlite-path", default="app/api/mvp.db", help="Path to the source SQLite database.")
    parser.add_argument(
        "--output",
        default="db/generated/runtime_seed.sql",
        help="Where to write the PostgreSQL INSERT statements.",
    )
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite database not found at {sqlite_path}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(sqlite_path)
    try:
        statements = [
            "-- Generated from the current SQLite runtime schema.",
            "-- Load after db/runtime_postgres.sql if you want a PostgreSQL copy of the current MVP data.",
            "BEGIN;",
        ]

        for table_name in TABLES:
            statements.append(export_table(conn, table_name))

        statements.append("COMMIT;")
        output_path.write_text("\n".join(statements))
    finally:
        conn.close()

    print(f"Wrote PostgreSQL seed export to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
