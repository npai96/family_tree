#!/usr/bin/env python3
"""Create a disposable 500-person/800-relationship SQLite review dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api.db_runtime import configure_database, execute, execute_many, get_conn, init_db


CREATED_AT = "2026-01-01T00:00:00+00:00"
USER_ID = "benchmark-user"
CIRCLE_ID = "benchmark-circle"


def build_relationships(node_count: int, edge_count: int) -> list[tuple[str, str, str, str, str, str]]:
    relationships: list[tuple[str, str, str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    # A ternary tree reaches 500 people within six hops, below the API's depth limit of ten.
    for child_index in range(1, node_count):
        parent_index = (child_index - 1) // 3
        from_id = f"benchmark-person-{parent_index:04d}"
        to_id = f"benchmark-person-{child_index:04d}"
        seen.add((from_id, to_id, "parent_of"))
        relationships.append(
            (f"benchmark-relationship-{len(relationships):04d}", CIRCLE_ID, from_id, to_id, "parent_of", CREATED_AT)
        )
    if len(relationships) == edge_count:
        return relationships

    lateral_types = ("spouse_of", "sibling_of", "cousin_of")
    for offset in range(1, node_count):
        for left_index in range(node_count):
            right_index = (left_index + offset) % node_count
            if left_index >= right_index:
                continue
            left_id = f"benchmark-person-{left_index:04d}"
            right_id = f"benchmark-person-{right_index:04d}"
            for relationship_type in lateral_types:
                key = (left_id, right_id, relationship_type)
                if key in seen:
                    continue
                seen.add(key)
                relationships.append(
                    (
                        f"benchmark-relationship-{len(relationships):04d}",
                        CIRCLE_ID,
                        left_id,
                        right_id,
                        relationship_type,
                        CREATED_AT,
                    )
                )
                if len(relationships) == edge_count:
                    return relationships

    return relationships


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path, help="New SQLite file to create; existing files are refused")
    parser.add_argument("--nodes", type=int, default=500)
    parser.add_argument("--edges", type=int, default=800)
    args = parser.parse_args()

    if args.nodes < 2:
        parser.error("--nodes must be at least 2")
    if args.edges < args.nodes - 1:
        parser.error("--edges must leave room for the connected parent tree")
    max_edges = (args.nodes - 1) + 3 * args.nodes * (args.nodes - 1) // 2
    if args.edges > max_edges:
        parser.error(f"--edges cannot exceed {max_edges} for {args.nodes} nodes")
    database_path = args.database.expanduser().resolve()
    if database_path.exists():
        parser.error(f"refusing to overwrite existing database: {database_path}")

    configure_database(db_path=database_path)
    init_db(database_path.parent / f"{database_path.stem}-media")

    people = [
        (
            f"benchmark-person-{index:04d}",
            CIRCLE_ID,
            f"Benchmark Person {index + 1}",
            None,
            None,
            f"{1850 + (index % 150):04d}-01-01",
            None,
            f"Benchmark Place {index % 24 + 1}",
            f"Occupation {index % 18 + 1}",
            None,
            None,
            None,
            None,
            CREATED_AT,
            CREATED_AT,
        )
        for index in range(args.nodes)
    ]
    relationships = build_relationships(args.nodes, args.edges)

    with get_conn() as conn:
        execute(conn, "INSERT INTO users (id, display_name, created_at) VALUES (?, ?, ?)", (USER_ID, "Graph Benchmark", CREATED_AT))
        execute(conn, "INSERT INTO circles (id, name, created_at) VALUES (?, ?, ?)", (CIRCLE_ID, "Graph Performance Baseline", CREATED_AT))
        execute(
            conn,
            "INSERT INTO circle_memberships (circle_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
            (CIRCLE_ID, USER_ID, "owner", CREATED_AT),
        )
        execute_many(
            conn,
            """
            INSERT INTO persons (
              id, circle_id, full_name, religion, sex, birth_date, death_date,
              birth_place, occupation, hobbies, personality, medical_notes,
              bio_text, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            people,
        )
        execute_many(
            conn,
            """
            INSERT INTO relationships (
              id, circle_id, from_person_id, to_person_id, relationship_type, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            relationships,
        )

    print(
        json.dumps(
            {
                "database": str(database_path),
                "user_id": USER_ID,
                "circle_id": CIRCLE_ID,
                "root_person_id": "benchmark-person-0000",
                "nodes": len(people),
                "edges": len(relationships),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
