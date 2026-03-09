from __future__ import annotations

import sqlite3
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "app" / "api" / "mvp.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS circles (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              created_at TEXT NOT NULL
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
            """
        )


class CircleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class CircleOut(BaseModel):
    id: str
    name: str
    created_at: str


class PersonCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    religion: Optional[str] = None
    sex: Optional[str] = None
    birth_date: Optional[str] = None
    death_date: Optional[str] = None
    birth_place: Optional[str] = None
    occupation: Optional[str] = None
    hobbies: Optional[str] = None
    personality: Optional[str] = None
    medical_notes: Optional[str] = None
    bio_text: Optional[str] = None


class PersonOut(PersonCreate):
    id: str
    circle_id: str
    created_at: str
    updated_at: str


class RelationshipCreate(BaseModel):
    from_person_id: str
    to_person_id: str
    relationship_type: str = Field(min_length=1, max_length=100)


class RelationshipOut(BaseModel):
    id: str
    circle_id: str
    from_person_id: str
    to_person_id: str
    relationship_type: str
    created_at: str


class SubgraphOut(BaseModel):
    persons: list[PersonOut]
    relationships: list[RelationshipOut]


@dataclass
class Edge:
    from_person_id: str
    to_person_id: str
    relationship_type: str


app = FastAPI(title="Family Tree MVP API", version="0.1.0")
WEB_INDEX_PATH = BASE_DIR / "app" / "web" / "index.html"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def web_app() -> FileResponse:
    return FileResponse(WEB_INDEX_PATH)


@app.post("/circles", response_model=CircleOut)
def create_circle(payload: CircleCreate) -> CircleOut:
    circle_id = str(uuid4())
    now = utc_now()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO circles (id, name, created_at) VALUES (?, ?, ?)",
            (circle_id, payload.name.strip(), now),
        )
    return CircleOut(id=circle_id, name=payload.name.strip(), created_at=now)


@app.get("/circles", response_model=list[CircleOut])
def list_circles() -> list[CircleOut]:
    with get_conn() as conn:
        rows = conn.execute("SELECT id, name, created_at FROM circles ORDER BY created_at DESC").fetchall()
    return [CircleOut(**dict(r)) for r in rows]


@app.post("/circles/{circle_id}/persons", response_model=PersonOut)
def create_person(circle_id: str, payload: PersonCreate) -> PersonOut:
    person_id = str(uuid4())
    now = utc_now()
    with get_conn() as conn:
        circle = conn.execute("SELECT id FROM circles WHERE id = ?", (circle_id,)).fetchone()
        if not circle:
            raise HTTPException(status_code=404, detail="Circle not found")

        conn.execute(
            """
            INSERT INTO persons (
              id, circle_id, full_name, religion, sex, birth_date, death_date, birth_place,
              occupation, hobbies, personality, medical_notes, bio_text, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                person_id,
                circle_id,
                payload.full_name.strip(),
                payload.religion,
                payload.sex,
                payload.birth_date,
                payload.death_date,
                payload.birth_place,
                payload.occupation,
                payload.hobbies,
                payload.personality,
                payload.medical_notes,
                payload.bio_text,
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM persons WHERE id = ?", (person_id,)).fetchone()
    return PersonOut(**dict(row))


@app.get("/circles/{circle_id}/persons", response_model=list[PersonOut])
def list_persons(circle_id: str) -> list[PersonOut]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM persons WHERE circle_id = ? ORDER BY created_at DESC",
            (circle_id,),
        ).fetchall()
    return [PersonOut(**dict(r)) for r in rows]


@app.post("/circles/{circle_id}/relationships", response_model=RelationshipOut)
def create_relationship(circle_id: str, payload: RelationshipCreate) -> RelationshipOut:
    rel_id = str(uuid4())
    now = utc_now()

    with get_conn() as conn:
        person_rows = conn.execute(
            "SELECT id FROM persons WHERE circle_id = ? AND id IN (?, ?)",
            (circle_id, payload.from_person_id, payload.to_person_id),
        ).fetchall()
        if len(person_rows) != 2:
            raise HTTPException(status_code=400, detail="Both persons must exist in circle")

        try:
            conn.execute(
                """
                INSERT INTO relationships (
                  id, circle_id, from_person_id, to_person_id, relationship_type, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    rel_id,
                    circle_id,
                    payload.from_person_id,
                    payload.to_person_id,
                    payload.relationship_type.strip(),
                    now,
                ),
            )
        except sqlite3.IntegrityError as err:
            raise HTTPException(status_code=409, detail=str(err)) from err
        row = conn.execute("SELECT * FROM relationships WHERE id = ?", (rel_id,)).fetchone()
    return RelationshipOut(**dict(row))


@app.get("/circles/{circle_id}/relationships", response_model=list[RelationshipOut])
def list_relationships(circle_id: str) -> list[RelationshipOut]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM relationships WHERE circle_id = ? ORDER BY created_at DESC",
            (circle_id,),
        ).fetchall()
    return [RelationshipOut(**dict(r)) for r in rows]


def _load_edges(circle_id: str, direction: str) -> dict[str, list[Edge]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT from_person_id, to_person_id, relationship_type
            FROM relationships
            WHERE circle_id = ?
            """,
            (circle_id,),
        ).fetchall()

    adjacency: dict[str, list[Edge]] = {}
    for row in rows:
        edge = Edge(
            from_person_id=row["from_person_id"],
            to_person_id=row["to_person_id"],
            relationship_type=row["relationship_type"],
        )
        if direction == "descendants":
            adjacency.setdefault(edge.from_person_id, []).append(edge)
        else:
            reversed_edge = Edge(
                from_person_id=edge.to_person_id,
                to_person_id=edge.from_person_id,
                relationship_type=edge.relationship_type,
            )
            adjacency.setdefault(reversed_edge.from_person_id, []).append(reversed_edge)
    return adjacency


def _traverse(root_person_id: str, adjacency: dict[str, list[Edge]], max_depth: int) -> tuple[set[str], set[tuple[str, str, str]]]:
    seen: set[str] = {root_person_id}
    seen_edges: set[tuple[str, str, str]] = set()
    queue: deque[tuple[str, int]] = deque([(root_person_id, 0)])

    while queue:
        node, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for edge in adjacency.get(node, []):
            seen_edges.add((edge.from_person_id, edge.to_person_id, edge.relationship_type))
            if edge.to_person_id not in seen:
                seen.add(edge.to_person_id)
                queue.append((edge.to_person_id, depth + 1))

    return seen, seen_edges


@app.get("/circles/{circle_id}/graph/subgraph", response_model=SubgraphOut)
def get_subgraph(
    circle_id: str,
    root_person_id: str = Query(...),
    direction: Literal["ancestors", "descendants"] = Query(...),
    depth: int = Query(2, ge=1, le=10),
) -> SubgraphOut:
    adjacency = _load_edges(circle_id, direction)
    seen_person_ids, seen_edges = _traverse(root_person_id, adjacency, depth)

    with get_conn() as conn:
        placeholders = ",".join("?" for _ in seen_person_ids)
        person_rows = conn.execute(
            f"SELECT * FROM persons WHERE circle_id = ? AND id IN ({placeholders})",
            (circle_id, *seen_person_ids),
        ).fetchall()

    persons = [PersonOut(**dict(row)) for row in person_rows]
    rels = [
        RelationshipOut(
            id=str(uuid4()),
            circle_id=circle_id,
            from_person_id=e[0],
            to_person_id=e[1],
            relationship_type=e[2],
            created_at=utc_now(),
        )
        for e in sorted(seen_edges)
    ]
    return SubgraphOut(persons=persons, relationships=rels)
