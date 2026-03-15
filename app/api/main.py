from __future__ import annotations

import sqlite3
import json
import shutil
import secrets
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "app" / "api" / "mvp.db"
WEB_INDEX_PATH = BASE_DIR / "app" / "web" / "index.html"
MEDIA_DIR = BASE_DIR / "app" / "media"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(
            """
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
            """
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Family Tree MVP API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class UserCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class UserOut(BaseModel):
    id: str
    display_name: str
    created_at: str


class AuthLoginRequest(BaseModel):
    user_id: Optional[str] = None
    display_name: Optional[str] = None


class AuthLoginOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOut
    expires_at: str


class CircleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class CircleOut(BaseModel):
    id: str
    name: str
    created_at: str


class CircleMembershipOut(BaseModel):
    circle_id: str
    user_id: str
    role: Literal["owner", "editor", "viewer"]
    created_at: str


class CircleMembershipCreate(BaseModel):
    user_id: str
    role: Literal["editor", "viewer"]


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


class PersonUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
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
    revision_reason: Optional[str] = None


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


class ChangeRequestCreate(BaseModel):
    entity_type: Literal["person"]
    entity_id: str
    proposed_patch_json: dict[str, Any]


class ChangeRequestReview(BaseModel):
    review_comment: Optional[str] = None


class ChangeRequestOut(BaseModel):
    id: str
    circle_id: str
    entity_type: str
    entity_id: str
    proposed_patch_json: str
    status: Literal["pending", "approved", "rejected"]
    proposed_by: str
    reviewed_by: Optional[str] = None
    review_comment: Optional[str] = None
    created_at: str
    reviewed_at: Optional[str] = None


class ContextEventCreate(BaseModel):
    date: str
    title: str = Field(min_length=1, max_length=200)
    event_type: Literal["world", "political", "social", "technology", "family"]
    location_name: Optional[str] = None
    description: Optional[str] = None


class ContextEventOut(BaseModel):
    id: str
    circle_id: str
    date: str
    title: str
    event_type: str
    location_name: Optional[str] = None
    description: Optional[str] = None
    created_by: str
    created_at: str


class PersonContextLinkCreate(BaseModel):
    context_event_id: str
    relevance_note: Optional[str] = None


class PersonContextLinkOut(BaseModel):
    person_id: str
    context_event_id: str
    circle_id: str
    relevance_note: Optional[str] = None
    created_by: str
    created_at: str


class TimelineItem(BaseModel):
    date: str
    kind: Literal["life", "context"]
    title: str
    detail: Optional[str] = None
    ref_id: Optional[str] = None


class PersonPlaceCreate(BaseModel):
    place_name: str = Field(min_length=1, max_length=200)
    country: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    notes: Optional[str] = None


class PersonPlaceOut(BaseModel):
    id: str
    circle_id: str
    person_id: str
    place_name: str
    country: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    notes: Optional[str] = None
    created_by: str
    created_at: str


class DiscussionThreadCreate(BaseModel):
    entity_type: Literal["person", "relationship", "change_request"]
    entity_id: str


class DiscussionThreadOut(BaseModel):
    id: str
    circle_id: str
    entity_type: str
    entity_id: str
    created_by: str
    created_at: str


class DiscussionMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class DiscussionMessageOut(BaseModel):
    id: str
    thread_id: str
    sender_user_id: str
    content: str
    created_at: str


class EntityRevisionOut(BaseModel):
    id: str
    circle_id: str
    entity_type: str
    entity_id: str
    revision_no: int
    snapshot_json: str
    reason: Optional[str] = None
    changed_by: str
    created_at: str


class DuplicateHintOut(BaseModel):
    person_id: str
    full_name: str
    birth_date: Optional[str] = None
    birth_place: Optional[str] = None
    score: int
    reasons: list[str]


class MediaAssetOut(BaseModel):
    id: str
    circle_id: str
    person_id: str
    uploader_user_id: str
    original_filename: str
    stored_filename: str
    mime_type: Optional[str] = None
    bytes: int
    created_at: str


class SubgraphOut(BaseModel):
    persons: list[PersonOut]
    relationships: list[RelationshipOut]


@dataclass
class Edge:
    edge_id: str
    from_person_id: str
    to_person_id: str
    relationship_type: str
    created_at: str


class CircleWSManager:
    def __init__(self) -> None:
        self.connections: dict[str, set[WebSocket]] = {}

    async def connect(self, circle_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self.connections.setdefault(circle_id, set()).add(ws)

    def disconnect(self, circle_id: str, ws: WebSocket) -> None:
        if circle_id not in self.connections:
            return
        self.connections[circle_id].discard(ws)
        if not self.connections[circle_id]:
            self.connections.pop(circle_id, None)

    async def broadcast(self, circle_id: str, payload: dict[str, Any]) -> None:
        peers = list(self.connections.get(circle_id, set()))
        stale: list[WebSocket] = []
        for ws in peers:
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(circle_id, ws)


ws_manager = CircleWSManager()
SUPPORTED_RELATIONSHIP_TYPES = {
    "parent_of",
    "child_of",
    "spouse_of",
    "sibling_of",
    "aunt_uncle_of",
    "niece_nephew_of",
    "cousin_of",
}


def _require_user(conn: sqlite3.Connection, user_id: Optional[str]) -> str:
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id header")
    row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid X-User-Id")
    return user_id


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


def _user_id_from_session_token(conn: sqlite3.Connection, token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    row = conn.execute(
        """
        SELECT user_id, expires_at, revoked_at
        FROM auth_sessions
        WHERE token = ?
        """,
        (token,),
    ).fetchone()
    if not row:
        return None
    if row["revoked_at"] is not None:
        return None
    if row["expires_at"] < utc_now():
        return None
    return str(row["user_id"])


def _require_authenticated_user(
    conn: sqlite3.Connection,
    x_user_id: Optional[str],
    authorization: Optional[str],
) -> str:
    if x_user_id:
        return _require_user(conn, x_user_id)
    token = _extract_bearer_token(authorization)
    user_id = _user_id_from_session_token(conn, token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing or invalid auth token")
    return _require_user(conn, user_id)


def _get_role(conn: sqlite3.Connection, circle_id: str, user_id: str) -> str:
    row = conn.execute(
        "SELECT role FROM circle_memberships WHERE circle_id = ? AND user_id = ?",
        (circle_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="Not a member of this circle")
    return str(row["role"])


def _require_circle_role(conn: sqlite3.Connection, circle_id: str, user_id: str, allowed_roles: set[str]) -> str:
    role = _get_role(conn, circle_id, user_id)
    if role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Insufficient role for this action")
    return role


def _safe_person_patch(patch: dict[str, Any]) -> tuple[str, list[Any]]:
    allowed_keys = {
        "full_name",
        "religion",
        "sex",
        "birth_date",
        "death_date",
        "birth_place",
        "occupation",
        "hobbies",
        "personality",
        "medical_notes",
        "bio_text",
    }
    keys = [k for k in patch.keys() if k in allowed_keys]
    if not keys:
        raise HTTPException(status_code=400, detail="No valid person fields to update")
    set_clause = ", ".join(f"{k} = ?" for k in keys) + ", updated_at = ?"
    values = [patch[k] for k in keys]
    values.append(utc_now())
    return set_clause, values


def _normalize_relationship_type(raw: str) -> str:
    value = raw.strip().lower().replace(" ", "_").replace("-", "_")
    return value


def _validate_person_dates(birth_date: Optional[str], death_date: Optional[str]) -> None:
    if birth_date and death_date and death_date < birth_date:
        raise HTTPException(status_code=400, detail="death_date must be on/after birth_date")


def _find_person_duplicates(
    conn: sqlite3.Connection,
    circle_id: str,
    full_name: str,
    birth_date: Optional[str],
    birth_place: Optional[str],
    exclude_person_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, full_name, birth_date, birth_place FROM persons WHERE circle_id = ?",
        (circle_id,),
    ).fetchall()
    candidate_name = full_name.strip().lower()
    candidate_birth_place = (birth_place or "").strip().lower()
    hints: list[dict[str, Any]] = []
    for row in rows:
        if exclude_person_id and row["id"] == exclude_person_id:
            continue
        score = 0
        reasons: list[str] = []
        row_name = (row["full_name"] or "").strip().lower()
        if row_name == candidate_name and candidate_name:
            score += 60
            reasons.append("exact_name_match")
        if birth_date and row["birth_date"] and row["birth_date"] == birth_date:
            score += 25
            reasons.append("birth_date_match")
        row_birth_place = (row["birth_place"] or "").strip().lower()
        if candidate_birth_place and row_birth_place and row_birth_place == candidate_birth_place:
            score += 15
            reasons.append("birth_place_match")
        if score >= 60:
            hints.append(
                {
                    "person_id": row["id"],
                    "full_name": row["full_name"],
                    "birth_date": row["birth_date"],
                    "birth_place": row["birth_place"],
                    "score": score,
                    "reasons": reasons,
                }
            )
    hints.sort(key=lambda h: h["score"], reverse=True)
    return hints


def _would_create_parent_cycle(conn: sqlite3.Connection, circle_id: str, parent_id: str, child_id: str) -> bool:
    if parent_id == child_id:
        return True
    stack = [child_id]
    visited: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur == parent_id:
            return True
        if cur in visited:
            continue
        visited.add(cur)
        rows = conn.execute(
            """
            SELECT to_person_id
            FROM relationships
            WHERE circle_id = ? AND from_person_id = ? AND relationship_type = 'parent_of'
            """,
            (circle_id, cur),
        ).fetchall()
        stack.extend([row["to_person_id"] for row in rows])
    return False


def _insert_person_revision(
    conn: sqlite3.Connection,
    circle_id: str,
    person_id: str,
    changed_by: str,
    reason: Optional[str],
) -> None:
    person = conn.execute(
        "SELECT * FROM persons WHERE id = ? AND circle_id = ?",
        (person_id, circle_id),
    ).fetchone()
    if not person:
        return
    next_revision = conn.execute(
        """
        SELECT COALESCE(MAX(revision_no), 0) + 1 AS next_rev
        FROM entity_revisions
        WHERE entity_type = 'person' AND entity_id = ?
        """,
        (person_id,),
    ).fetchone()["next_rev"]
    conn.execute(
        """
        INSERT INTO entity_revisions (
          id, circle_id, entity_type, entity_id, revision_no, snapshot_json, reason, changed_by, created_at
        ) VALUES (?, ?, 'person', ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            circle_id,
            person_id,
            int(next_revision),
            json.dumps(dict(person)),
            reason,
            changed_by,
            utc_now(),
        ),
    )


def _load_edges(circle_id: str, direction: str) -> dict[str, list[Edge]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, from_person_id, to_person_id, relationship_type, created_at
            FROM relationships
            WHERE circle_id = ?
            """,
            (circle_id,),
        ).fetchall()

    adjacency: dict[str, list[Edge]] = {}
    for row in rows:
        edge = Edge(
            edge_id=row["id"],
            from_person_id=row["from_person_id"],
            to_person_id=row["to_person_id"],
            relationship_type=row["relationship_type"],
            created_at=row["created_at"],
        )
        if direction == "descendants":
            adjacency.setdefault(edge.from_person_id, []).append(edge)
        else:
            reversed_edge = Edge(
                edge_id=f"reverse:{edge.edge_id}",
                from_person_id=edge.to_person_id,
                to_person_id=edge.from_person_id,
                relationship_type=edge.relationship_type,
                created_at=edge.created_at,
            )
            adjacency.setdefault(reversed_edge.from_person_id, []).append(reversed_edge)
    return adjacency


def _traverse(root_person_id: str, adjacency: dict[str, list[Edge]], max_depth: int) -> tuple[set[str], dict[str, Edge]]:
    seen: set[str] = {root_person_id}
    seen_edges: dict[str, Edge] = {}
    queue: deque[tuple[str, int]] = deque([(root_person_id, 0)])

    while queue:
        node, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for edge in adjacency.get(node, []):
            seen_edges[edge.edge_id] = edge
            if edge.to_person_id not in seen:
                seen.add(edge.to_person_id)
                queue.append((edge.to_person_id, depth + 1))
    return seen, seen_edges


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def web_app() -> FileResponse:
    return FileResponse(WEB_INDEX_PATH)


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.websocket("/ws/circles/{circle_id}")
async def circle_ws(
    circle_id: str,
    websocket: WebSocket,
    user_id: Optional[str] = None,
    token: Optional[str] = None,
) -> None:
    with get_conn() as conn:
        token_user_id = _user_id_from_session_token(conn, token)
        resolved_user_id = user_id or token_user_id
        if not resolved_user_id:
            await websocket.close(code=1008)
            return
        _require_user(conn, resolved_user_id)
        _get_role(conn, circle_id, resolved_user_id)

    await ws_manager.connect(circle_id, websocket)
    await ws_manager.broadcast(
        circle_id,
        {"type": "presence.updated", "circle_id": circle_id, "user_id": resolved_user_id, "state": "joined"},
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(circle_id, websocket)
        await ws_manager.broadcast(
            circle_id,
            {"type": "presence.updated", "circle_id": circle_id, "user_id": resolved_user_id, "state": "left"},
        )


@app.post("/users", response_model=UserOut)
def create_user(payload: UserCreate) -> UserOut:
    user_id = str(uuid4())
    now = utc_now()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (id, display_name, created_at) VALUES (?, ?, ?)",
            (user_id, payload.display_name.strip(), now),
        )
    return UserOut(id=user_id, display_name=payload.display_name.strip(), created_at=now)


@app.get("/users", response_model=list[UserOut])
def list_users() -> list[UserOut]:
    with get_conn() as conn:
        rows = conn.execute("SELECT id, display_name, created_at FROM users ORDER BY created_at DESC").fetchall()
    return [UserOut(**dict(row)) for row in rows]


@app.post("/auth/login", response_model=AuthLoginOut)
def auth_login(payload: AuthLoginRequest) -> AuthLoginOut:
    now = utc_now()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    token = secrets.token_urlsafe(32)
    with get_conn() as conn:
        user_row = None
        if payload.user_id:
            user_row = conn.execute(
                "SELECT id, display_name, created_at FROM users WHERE id = ?",
                (payload.user_id,),
            ).fetchone()
        elif payload.display_name and payload.display_name.strip():
            user_row = conn.execute(
                "SELECT id, display_name, created_at FROM users WHERE lower(display_name) = lower(?) ORDER BY created_at ASC LIMIT 1",
                (payload.display_name.strip(),),
            ).fetchone()
            if not user_row:
                new_id = str(uuid4())
                conn.execute(
                    "INSERT INTO users (id, display_name, created_at) VALUES (?, ?, ?)",
                    (new_id, payload.display_name.strip(), now),
                )
                user_row = conn.execute(
                    "SELECT id, display_name, created_at FROM users WHERE id = ?",
                    (new_id,),
                ).fetchone()
        else:
            raise HTTPException(status_code=400, detail="Provide either user_id or display_name")

        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        conn.execute(
            """
            INSERT INTO auth_sessions (token, user_id, created_at, expires_at, revoked_at)
            VALUES (?, ?, ?, ?, NULL)
            """,
            (token, user_row["id"], now, expires_at),
        )

    return AuthLoginOut(
        access_token=token,
        user=UserOut(**dict(user_row)),
        expires_at=expires_at,
    )


@app.get("/auth/me", response_model=UserOut)
def auth_me(
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> UserOut:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        row = conn.execute(
            "SELECT id, display_name, created_at FROM users WHERE id = ?",
            (actor_user_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut(**dict(row))


@app.post("/circles", response_model=CircleOut)
def create_circle(
    payload: CircleCreate,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> CircleOut:
    circle_id = str(uuid4())
    now = utc_now()
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        conn.execute(
            "INSERT INTO circles (id, name, created_at) VALUES (?, ?, ?)",
            (circle_id, payload.name.strip(), now),
        )
        conn.execute(
            "INSERT INTO circle_memberships (circle_id, user_id, role, created_at) VALUES (?, ?, 'owner', ?)",
            (circle_id, actor_user_id, now),
        )
    return CircleOut(id=circle_id, name=payload.name.strip(), created_at=now)


@app.get("/circles", response_model=list[CircleOut])
def list_circles(
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> list[CircleOut]:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        rows = conn.execute(
            """
            SELECT c.id, c.name, c.created_at
            FROM circles c
            INNER JOIN circle_memberships m ON m.circle_id = c.id
            WHERE m.user_id = ?
            ORDER BY c.created_at DESC
            """,
            (actor_user_id,),
        ).fetchall()
    return [CircleOut(**dict(row)) for row in rows]


@app.get("/circles/{circle_id}/members", response_model=list[CircleMembershipOut])
def list_members(
    circle_id: str,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> list[CircleMembershipOut]:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        rows = conn.execute(
            "SELECT circle_id, user_id, role, created_at FROM circle_memberships WHERE circle_id = ? ORDER BY created_at",
            (circle_id,),
        ).fetchall()
    return [CircleMembershipOut(**dict(row)) for row in rows]


@app.post("/circles/{circle_id}/members", response_model=CircleMembershipOut)
def add_member(
    circle_id: str,
    payload: CircleMembershipCreate,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> CircleMembershipOut:
    now = utc_now()
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _require_circle_role(conn, circle_id, actor_user_id, {"owner"})
        _require_user(conn, payload.user_id)
        existing = conn.execute(
            """
            SELECT circle_id, user_id, role, created_at
            FROM circle_memberships
            WHERE circle_id = ? AND user_id = ?
            """,
            (circle_id, payload.user_id),
        ).fetchone()
        if existing:
            if existing["role"] == "owner":
                raise HTTPException(status_code=409, detail="Owner role cannot be changed via this endpoint")
            if existing["role"] != payload.role:
                conn.execute(
                    """
                    UPDATE circle_memberships
                    SET role = ?
                    WHERE circle_id = ? AND user_id = ?
                    """,
                    (payload.role, circle_id, payload.user_id),
                )
                existing = conn.execute(
                    """
                    SELECT circle_id, user_id, role, created_at
                    FROM circle_memberships
                    WHERE circle_id = ? AND user_id = ?
                    """,
                    (circle_id, payload.user_id),
                ).fetchone()
            return CircleMembershipOut(**dict(existing))

        conn.execute(
            "INSERT INTO circle_memberships (circle_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
            (circle_id, payload.user_id, payload.role, now),
        )
    return CircleMembershipOut(circle_id=circle_id, user_id=payload.user_id, role=payload.role, created_at=now)


@app.post("/circles/{circle_id}/persons", response_model=PersonOut)
def create_person(
    circle_id: str,
    payload: PersonCreate,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> PersonOut:
    person_id = str(uuid4())
    now = utc_now()
    normalized_name = payload.full_name.strip()
    _validate_person_dates(payload.birth_date, payload.death_date)
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _require_circle_role(conn, circle_id, actor_user_id, {"owner", "editor"})
        dup_hints = _find_person_duplicates(
            conn,
            circle_id,
            full_name=normalized_name,
            birth_date=payload.birth_date,
            birth_place=payload.birth_place,
        )
        if any("exact_name_match" in hint["reasons"] and "birth_date_match" in hint["reasons"] for hint in dup_hints):
            raise HTTPException(status_code=409, detail="Likely duplicate person exists (exact name + birth date)")
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
                normalized_name,
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
        _insert_person_revision(conn, circle_id, person_id, actor_user_id, "person_created")
        row = conn.execute("SELECT * FROM persons WHERE id = ?", (person_id,)).fetchone()
    return PersonOut(**dict(row))


@app.get("/circles/{circle_id}/persons", response_model=list[PersonOut])
def list_persons(
    circle_id: str,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> list[PersonOut]:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        rows = conn.execute(
            "SELECT * FROM persons WHERE circle_id = ? ORDER BY created_at DESC",
            (circle_id,),
        ).fetchall()
    return [PersonOut(**dict(row)) for row in rows]


@app.patch("/circles/{circle_id}/persons/{person_id}", response_model=PersonOut)
def update_person(
    circle_id: str,
    person_id: str,
    payload: PersonUpdate,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> PersonOut:
    patch = payload.model_dump(exclude_unset=True)
    revision_reason = patch.pop("revision_reason", None)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    if "full_name" in patch:
        full_name = (patch.get("full_name") or "").strip()
        if not full_name:
            raise HTTPException(status_code=400, detail="full_name cannot be empty")
        patch["full_name"] = full_name

    optional_string_fields = {
        "religion",
        "sex",
        "birth_date",
        "death_date",
        "birth_place",
        "occupation",
        "hobbies",
        "personality",
        "medical_notes",
        "bio_text",
    }
    for field in optional_string_fields:
        if field in patch and isinstance(patch[field], str):
            patch[field] = patch[field].strip() or None

    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _require_circle_role(conn, circle_id, actor_user_id, {"owner", "editor"})
        existing = conn.execute(
            "SELECT * FROM persons WHERE id = ? AND circle_id = ?",
            (person_id, circle_id),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Person not found in circle")

        birth_date = patch.get("birth_date", existing["birth_date"])
        death_date = patch.get("death_date", existing["death_date"])
        _validate_person_dates(birth_date, death_date)

        set_clause, values = _safe_person_patch(patch)
        conn.execute(
            f"UPDATE persons SET {set_clause} WHERE id = ? AND circle_id = ?",
            (*values, person_id, circle_id),
        )
        _insert_person_revision(
            conn,
            circle_id,
            person_id,
            actor_user_id,
            revision_reason or "person_updated",
        )
        row = conn.execute("SELECT * FROM persons WHERE id = ? AND circle_id = ?", (person_id, circle_id)).fetchone()
    return PersonOut(**dict(row))


@app.get("/circles/{circle_id}/persons/duplicate-hints", response_model=list[DuplicateHintOut])
def person_duplicate_hints(
    circle_id: str,
    full_name: str = Query(..., min_length=1),
    birth_date: Optional[str] = Query(default=None),
    birth_place: Optional[str] = Query(default=None),
    exclude_person_id: Optional[str] = Query(default=None),
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> list[DuplicateHintOut]:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        hints = _find_person_duplicates(
            conn,
            circle_id,
            full_name=full_name,
            birth_date=birth_date,
            birth_place=birth_place,
            exclude_person_id=exclude_person_id,
        )
    return [DuplicateHintOut(**hint) for hint in hints]


@app.get("/circles/{circle_id}/persons/{person_id}/revisions", response_model=list[EntityRevisionOut])
def list_person_revisions(
    circle_id: str,
    person_id: str,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> list[EntityRevisionOut]:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        person = conn.execute(
            "SELECT id FROM persons WHERE id = ? AND circle_id = ?",
            (person_id, circle_id),
        ).fetchone()
        if not person:
            raise HTTPException(status_code=404, detail="Person not found in circle")
        rows = conn.execute(
            """
            SELECT id, circle_id, entity_type, entity_id, revision_no, snapshot_json, reason, changed_by, created_at
            FROM entity_revisions
            WHERE circle_id = ? AND entity_type = 'person' AND entity_id = ?
            ORDER BY revision_no DESC
            """,
            (circle_id, person_id),
        ).fetchall()
    return [EntityRevisionOut(**dict(row)) for row in rows]


@app.post("/circles/{circle_id}/persons/{person_id}/places", response_model=PersonPlaceOut)
def create_person_place(
    circle_id: str,
    person_id: str,
    payload: PersonPlaceCreate,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> PersonPlaceOut:
    place_id = str(uuid4())
    now = utc_now()
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _require_circle_role(conn, circle_id, actor_user_id, {"owner", "editor"})
        person = conn.execute(
            "SELECT id FROM persons WHERE id = ? AND circle_id = ?",
            (person_id, circle_id),
        ).fetchone()
        if not person:
            raise HTTPException(status_code=404, detail="Person not found in circle")

        conn.execute(
            """
            INSERT INTO person_places (
              id, circle_id, person_id, place_name, country, lat, lng, from_date, to_date, notes, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                place_id,
                circle_id,
                person_id,
                payload.place_name.strip(),
                payload.country,
                payload.lat,
                payload.lng,
                payload.from_date,
                payload.to_date,
                payload.notes,
                actor_user_id,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM person_places WHERE id = ?", (place_id,)).fetchone()
    return PersonPlaceOut(**dict(row))


@app.get("/circles/{circle_id}/persons/{person_id}/places", response_model=list[PersonPlaceOut])
def list_person_places(
    circle_id: str,
    person_id: str,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> list[PersonPlaceOut]:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        person = conn.execute(
            "SELECT id FROM persons WHERE id = ? AND circle_id = ?",
            (person_id, circle_id),
        ).fetchone()
        if not person:
            raise HTTPException(status_code=404, detail="Person not found in circle")
        rows = conn.execute(
            """
            SELECT *
            FROM person_places
            WHERE circle_id = ? AND person_id = ?
            ORDER BY COALESCE(from_date, created_at) ASC, created_at ASC
            """,
            (circle_id, person_id),
        ).fetchall()
    return [PersonPlaceOut(**dict(row)) for row in rows]


@app.get("/circles/{circle_id}/persons/{person_id}/migration-geojson")
def person_migration_geojson(
    circle_id: str,
    person_id: str,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        person = conn.execute(
            "SELECT full_name FROM persons WHERE id = ? AND circle_id = ?",
            (person_id, circle_id),
        ).fetchone()
        if not person:
            raise HTTPException(status_code=404, detail="Person not found in circle")
        rows = conn.execute(
            """
            SELECT *
            FROM person_places
            WHERE circle_id = ? AND person_id = ? AND lat IS NOT NULL AND lng IS NOT NULL
            ORDER BY COALESCE(from_date, created_at) ASC, created_at ASC
            """,
            (circle_id, person_id),
        ).fetchall()

    coords = [[float(r["lng"]), float(r["lat"])] for r in rows]
    point_features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r["lng"]), float(r["lat"])]},
            "properties": {
                "place_name": r["place_name"],
                "country": r["country"],
                "from_date": r["from_date"],
                "to_date": r["to_date"],
                "notes": r["notes"],
            },
        }
        for r in rows
    ]
    features: list[dict[str, Any]] = point_features
    if len(coords) >= 2:
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {"person_id": person_id, "full_name": person["full_name"]},
            }
        ] + point_features
    return {"type": "FeatureCollection", "features": features}


@app.post("/circles/{circle_id}/persons/{person_id}/media", response_model=MediaAssetOut)
async def upload_person_media(
    circle_id: str,
    person_id: str,
    file: UploadFile = File(...),
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> MediaAssetOut:
    asset_id = str(uuid4())
    now = utc_now()
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _require_circle_role(conn, circle_id, actor_user_id, {"owner", "editor"})
        person = conn.execute(
            "SELECT id FROM persons WHERE id = ? AND circle_id = ?",
            (person_id, circle_id),
        ).fetchone()
        if not person:
            raise HTTPException(status_code=404, detail="Person not found in circle")

    person_dir = MEDIA_DIR / circle_id / person_id
    person_dir.mkdir(parents=True, exist_ok=True)
    original_name = file.filename or "upload.bin"
    stored_name = f"{asset_id}_{original_name}"
    stored_path = person_dir / stored_name

    with stored_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    bytes_size = stored_path.stat().st_size

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO media_assets (
              id, circle_id, person_id, uploader_user_id, original_filename, stored_filename, mime_type, bytes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                circle_id,
                person_id,
                actor_user_id,
                original_name,
                stored_name,
                file.content_type,
                bytes_size,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM media_assets WHERE id = ?", (asset_id,)).fetchone()
    return MediaAssetOut(**dict(row))


@app.get("/circles/{circle_id}/persons/{person_id}/media", response_model=list[MediaAssetOut])
def list_person_media(
    circle_id: str,
    person_id: str,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> list[MediaAssetOut]:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        rows = conn.execute(
            """
            SELECT *
            FROM media_assets
            WHERE circle_id = ? AND person_id = ?
            ORDER BY created_at DESC
            """,
            (circle_id, person_id),
        ).fetchall()
    return [MediaAssetOut(**dict(row)) for row in rows]


@app.get("/circles/{circle_id}/media/{asset_id}/download")
def download_media(
    circle_id: str,
    asset_id: str,
    user_id: Optional[str] = Query(default=None),
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> FileResponse:
    auth_user_id = x_user_id or user_id
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, auth_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        row = conn.execute(
            "SELECT * FROM media_assets WHERE id = ? AND circle_id = ?",
            (asset_id, circle_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Media asset not found")

    file_path = MEDIA_DIR / circle_id / row["person_id"] / row["stored_filename"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Media file missing on disk")
    return FileResponse(
        file_path,
        media_type=row["mime_type"] or "application/octet-stream",
        filename=row["original_filename"],
    )


@app.post("/circles/{circle_id}/relationships", response_model=RelationshipOut)
def create_relationship(
    circle_id: str,
    payload: RelationshipCreate,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> RelationshipOut:
    rel_id = str(uuid4())
    now = utc_now()
    normalized_type = _normalize_relationship_type(payload.relationship_type)
    if normalized_type not in SUPPORTED_RELATIONSHIP_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported relationship_type. Allowed: {', '.join(sorted(SUPPORTED_RELATIONSHIP_TYPES))}",
        )
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _require_circle_role(conn, circle_id, actor_user_id, {"owner", "editor"})
        person_rows = conn.execute(
            "SELECT id FROM persons WHERE circle_id = ? AND id IN (?, ?)",
            (circle_id, payload.from_person_id, payload.to_person_id),
        ).fetchall()
        if len(person_rows) != 2:
            raise HTTPException(status_code=400, detail="Both persons must exist in circle")
        if normalized_type == "parent_of" and _would_create_parent_cycle(
            conn,
            circle_id,
            payload.from_person_id,
            payload.to_person_id,
        ):
            raise HTTPException(status_code=400, detail="parent_of would create a cycle in ancestry graph")
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
                    normalized_type,
                    now,
                ),
            )
        except sqlite3.IntegrityError as err:
            raise HTTPException(status_code=409, detail=str(err)) from err
        row = conn.execute("SELECT * FROM relationships WHERE id = ?", (rel_id,)).fetchone()
    return RelationshipOut(**dict(row))


@app.get("/circles/{circle_id}/relationships", response_model=list[RelationshipOut])
def list_relationships(
    circle_id: str,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> list[RelationshipOut]:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        rows = conn.execute(
            "SELECT * FROM relationships WHERE circle_id = ? ORDER BY created_at DESC",
            (circle_id,),
        ).fetchall()
    return [RelationshipOut(**dict(row)) for row in rows]


@app.delete("/circles/{circle_id}/relationships/{relationship_id}")
def delete_relationship(
    circle_id: str,
    relationship_id: str,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> dict[str, str]:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _require_circle_role(conn, circle_id, actor_user_id, {"owner", "editor"})
        row = conn.execute(
            "SELECT id FROM relationships WHERE id = ? AND circle_id = ?",
            (relationship_id, circle_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Relationship not found")
        conn.execute(
            "DELETE FROM relationships WHERE id = ? AND circle_id = ?",
            (relationship_id, circle_id),
        )
    return {"status": "deleted", "relationship_id": relationship_id}


@app.post("/circles/{circle_id}/context-events", response_model=ContextEventOut)
def create_context_event(
    circle_id: str,
    payload: ContextEventCreate,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> ContextEventOut:
    event_id = str(uuid4())
    now = utc_now()
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _require_circle_role(conn, circle_id, actor_user_id, {"owner", "editor"})
        conn.execute(
            """
            INSERT INTO context_events (
              id, circle_id, date, title, event_type, location_name, description, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                circle_id,
                payload.date,
                payload.title.strip(),
                payload.event_type,
                payload.location_name,
                payload.description,
                actor_user_id,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM context_events WHERE id = ?", (event_id,)).fetchone()
    return ContextEventOut(**dict(row))


@app.get("/circles/{circle_id}/context-events", response_model=list[ContextEventOut])
def list_context_events(
    circle_id: str,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> list[ContextEventOut]:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        rows = conn.execute(
            """
            SELECT *
            FROM context_events
            WHERE circle_id = ?
            ORDER BY date ASC, created_at ASC
            """,
            (circle_id,),
        ).fetchall()
    return [ContextEventOut(**dict(row)) for row in rows]


@app.get("/circles/{circle_id}/context-events/{context_event_id}/persons", response_model=list[PersonOut])
def list_context_event_persons(
    circle_id: str,
    context_event_id: str,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> list[PersonOut]:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        event = conn.execute(
            "SELECT id FROM context_events WHERE id = ? AND circle_id = ?",
            (context_event_id, circle_id),
        ).fetchone()
        if not event:
            raise HTTPException(status_code=404, detail="Context event not found in circle")
        rows = conn.execute(
            """
            SELECT p.*
            FROM persons p
            INNER JOIN person_context_links pcl ON pcl.person_id = p.id
            WHERE pcl.circle_id = ? AND pcl.context_event_id = ?
            ORDER BY p.full_name ASC
            """,
            (circle_id, context_event_id),
        ).fetchall()
    return [PersonOut(**dict(row)) for row in rows]


@app.post("/circles/{circle_id}/persons/{person_id}/context-links", response_model=PersonContextLinkOut)
def link_context_event_to_person(
    circle_id: str,
    person_id: str,
    payload: PersonContextLinkCreate,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> PersonContextLinkOut:
    now = utc_now()
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _require_circle_role(conn, circle_id, actor_user_id, {"owner", "editor"})

        person = conn.execute(
            "SELECT id FROM persons WHERE id = ? AND circle_id = ?",
            (person_id, circle_id),
        ).fetchone()
        if not person:
            raise HTTPException(status_code=404, detail="Person not found in circle")

        event = conn.execute(
            "SELECT id FROM context_events WHERE id = ? AND circle_id = ?",
            (payload.context_event_id, circle_id),
        ).fetchone()
        if not event:
            raise HTTPException(status_code=404, detail="Context event not found in circle")

        try:
            conn.execute(
                """
                INSERT INTO person_context_links (
                  person_id, context_event_id, circle_id, relevance_note, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    person_id,
                    payload.context_event_id,
                    circle_id,
                    payload.relevance_note,
                    actor_user_id,
                    now,
                ),
            )
        except sqlite3.IntegrityError:
            row = conn.execute(
                """
                SELECT person_id, context_event_id, circle_id, relevance_note, created_by, created_at
                FROM person_context_links
                WHERE person_id = ? AND context_event_id = ?
                """,
                (person_id, payload.context_event_id),
            ).fetchone()
            return PersonContextLinkOut(**dict(row))

        row = conn.execute(
            """
            SELECT person_id, context_event_id, circle_id, relevance_note, created_by, created_at
            FROM person_context_links
            WHERE person_id = ? AND context_event_id = ?
            """,
            (person_id, payload.context_event_id),
        ).fetchone()
    return PersonContextLinkOut(**dict(row))


@app.get("/circles/{circle_id}/persons/{person_id}/timeline", response_model=list[TimelineItem])
def get_person_timeline(
    circle_id: str,
    person_id: str,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> list[TimelineItem]:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)

        person = conn.execute(
            "SELECT * FROM persons WHERE id = ? AND circle_id = ?",
            (person_id, circle_id),
        ).fetchone()
        if not person:
            raise HTTPException(status_code=404, detail="Person not found in circle")

        rows = conn.execute(
            """
            SELECT ce.*
            FROM context_events ce
            INNER JOIN person_context_links pcl
              ON pcl.context_event_id = ce.id
            WHERE ce.circle_id = ? AND pcl.person_id = ?
            ORDER BY ce.date ASC
            """,
            (circle_id, person_id),
        ).fetchall()
        place_rows = conn.execute(
            """
            SELECT *
            FROM person_places
            WHERE circle_id = ? AND person_id = ? AND from_date IS NOT NULL
            ORDER BY from_date ASC, created_at ASC
            """,
            (circle_id, person_id),
        ).fetchall()

    timeline: list[TimelineItem] = []
    if person["birth_date"]:
        timeline.append(
            TimelineItem(
                date=person["birth_date"],
                kind="life",
                title=f"Birth of {person['full_name']}",
                detail=person["birth_place"] or None,
                ref_id=person_id,
            )
        )
    for row in rows:
        timeline.append(
            TimelineItem(
                date=row["date"],
                kind="context",
                title=row["title"],
                detail=row["description"],
                ref_id=row["id"],
            )
        )
    for row in place_rows:
        timeline.append(
            TimelineItem(
                date=row["from_date"],
                kind="life",
                title=f"Moved to {row['place_name']}",
                detail=row["country"],
                ref_id=person_id,
            )
        )
    if person["death_date"]:
        timeline.append(
            TimelineItem(
                date=person["death_date"],
                kind="life",
                title=f"Death of {person['full_name']}",
                detail=None,
                ref_id=person_id,
            )
        )
    timeline.sort(key=lambda x: x.date)
    return timeline


@app.get("/circles/{circle_id}/graph/subgraph", response_model=SubgraphOut)
def get_subgraph(
    circle_id: str,
    root_person_id: str = Query(...),
    direction: Literal["ancestors", "descendants"] = Query(...),
    depth: int = Query(2, ge=1, le=10),
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> SubgraphOut:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        root_exists = conn.execute(
            "SELECT id FROM persons WHERE id = ? AND circle_id = ?",
            (root_person_id, circle_id),
        ).fetchone()
        if not root_exists:
            raise HTTPException(status_code=404, detail="Root person not found in circle")

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
            id=edge.edge_id,
            circle_id=circle_id,
            from_person_id=edge.from_person_id,
            to_person_id=edge.to_person_id,
            relationship_type=edge.relationship_type,
            created_at=edge.created_at,
        )
        for edge in seen_edges.values()
    ]
    return SubgraphOut(persons=persons, relationships=rels)


@app.post("/circles/{circle_id}/threads", response_model=DiscussionThreadOut)
async def create_or_get_thread(
    circle_id: str,
    payload: DiscussionThreadCreate,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> DiscussionThreadOut:
    thread_id = str(uuid4())
    now = utc_now()
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        existing = conn.execute(
            """
            SELECT id, circle_id, entity_type, entity_id, created_by, created_at
            FROM discussion_threads
            WHERE circle_id = ? AND entity_type = ? AND entity_id = ?
            """,
            (circle_id, payload.entity_type, payload.entity_id),
        ).fetchone()
        if existing:
            return DiscussionThreadOut(**dict(existing))
        conn.execute(
            """
            INSERT INTO discussion_threads (id, circle_id, entity_type, entity_id, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (thread_id, circle_id, payload.entity_type, payload.entity_id, actor_user_id, now),
        )
        row = conn.execute(
            "SELECT id, circle_id, entity_type, entity_id, created_by, created_at FROM discussion_threads WHERE id = ?",
            (thread_id,),
        ).fetchone()
    out = DiscussionThreadOut(**dict(row))
    await ws_manager.broadcast(
        circle_id,
        {"type": "thread.created", "circle_id": circle_id, "thread": out.model_dump()},
    )
    return out


@app.get("/circles/{circle_id}/threads/{thread_id}/messages", response_model=list[DiscussionMessageOut])
def list_thread_messages(
    circle_id: str,
    thread_id: str,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> list[DiscussionMessageOut]:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        thread = conn.execute(
            "SELECT id FROM discussion_threads WHERE id = ? AND circle_id = ?",
            (thread_id, circle_id),
        ).fetchone()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        rows = conn.execute(
            """
            SELECT id, thread_id, sender_user_id, content, created_at
            FROM discussion_messages
            WHERE thread_id = ?
            ORDER BY created_at ASC
            """,
            (thread_id,),
        ).fetchall()
    return [DiscussionMessageOut(**dict(row)) for row in rows]


@app.post("/circles/{circle_id}/threads/{thread_id}/messages", response_model=DiscussionMessageOut)
async def create_thread_message(
    circle_id: str,
    thread_id: str,
    payload: DiscussionMessageCreate,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> DiscussionMessageOut:
    message_id = str(uuid4())
    now = utc_now()
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        thread = conn.execute(
            "SELECT id FROM discussion_threads WHERE id = ? AND circle_id = ?",
            (thread_id, circle_id),
        ).fetchone()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        conn.execute(
            """
            INSERT INTO discussion_messages (id, thread_id, sender_user_id, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (message_id, thread_id, actor_user_id, payload.content.strip(), now),
        )
        row = conn.execute(
            "SELECT id, thread_id, sender_user_id, content, created_at FROM discussion_messages WHERE id = ?",
            (message_id,),
        ).fetchone()
    out = DiscussionMessageOut(**dict(row))
    await ws_manager.broadcast(
        circle_id,
        {"type": "thread.message.created", "circle_id": circle_id, "thread_id": thread_id, "message": out.model_dump()},
    )
    return out


@app.post("/circles/{circle_id}/change-requests", response_model=ChangeRequestOut)
def create_change_request(
    circle_id: str,
    payload: ChangeRequestCreate,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> ChangeRequestOut:
    cr_id = str(uuid4())
    now = utc_now()
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        if payload.entity_type == "person":
            row = conn.execute(
                "SELECT id FROM persons WHERE id = ? AND circle_id = ?",
                (payload.entity_id, circle_id),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Target person not found in circle")
        conn.execute(
            """
            INSERT INTO change_requests (
              id, circle_id, entity_type, entity_id, proposed_patch_json, status, proposed_by, created_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                cr_id,
                circle_id,
                payload.entity_type,
                payload.entity_id,
                json.dumps(payload.proposed_patch_json),
                actor_user_id,
                now,
            ),
        )
        out = conn.execute("SELECT * FROM change_requests WHERE id = ?", (cr_id,)).fetchone()
    return ChangeRequestOut(**dict(out))


@app.get("/circles/{circle_id}/change-requests", response_model=list[ChangeRequestOut])
def list_change_requests(
    circle_id: str,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> list[ChangeRequestOut]:
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _get_role(conn, circle_id, actor_user_id)
        rows = conn.execute(
            """
            SELECT * FROM change_requests
            WHERE circle_id = ?
            ORDER BY created_at DESC
            """,
            (circle_id,),
        ).fetchall()
    return [ChangeRequestOut(**dict(row)) for row in rows]


@app.post("/circles/{circle_id}/change-requests/{change_request_id}/approve", response_model=ChangeRequestOut)
def approve_change_request(
    circle_id: str,
    change_request_id: str,
    payload: ChangeRequestReview,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> ChangeRequestOut:
    reviewed_at = utc_now()
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _require_circle_role(conn, circle_id, actor_user_id, {"owner", "editor"})
        row = conn.execute(
            "SELECT * FROM change_requests WHERE id = ? AND circle_id = ?",
            (change_request_id, circle_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Change request not found")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail="Change request already reviewed")
        if row["entity_type"] != "person":
            raise HTTPException(status_code=400, detail="Unsupported entity type")

        proposed_patch = json.loads(row["proposed_patch_json"])
        set_clause, values = _safe_person_patch(proposed_patch)
        conn.execute(
            f"UPDATE persons SET {set_clause} WHERE id = ? AND circle_id = ?",
            (*values, row["entity_id"], circle_id),
        )
        _insert_person_revision(
            conn,
            circle_id,
            row["entity_id"],
            actor_user_id,
            f"change_request_approved:{change_request_id}",
        )
        conn.execute(
            """
            UPDATE change_requests
            SET status = 'approved', reviewed_by = ?, review_comment = ?, reviewed_at = ?
            WHERE id = ?
            """,
            (actor_user_id, payload.review_comment, reviewed_at, change_request_id),
        )
        out = conn.execute("SELECT * FROM change_requests WHERE id = ?", (change_request_id,)).fetchone()
    return ChangeRequestOut(**dict(out))


@app.post("/circles/{circle_id}/change-requests/{change_request_id}/reject", response_model=ChangeRequestOut)
def reject_change_request(
    circle_id: str,
    change_request_id: str,
    payload: ChangeRequestReview,
    x_user_id: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> ChangeRequestOut:
    reviewed_at = utc_now()
    with get_conn() as conn:
        actor_user_id = _require_authenticated_user(conn, x_user_id, authorization)
        _require_circle_role(conn, circle_id, actor_user_id, {"owner", "editor"})
        row = conn.execute(
            "SELECT * FROM change_requests WHERE id = ? AND circle_id = ?",
            (change_request_id, circle_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Change request not found")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail="Change request already reviewed")
        conn.execute(
            """
            UPDATE change_requests
            SET status = 'rejected', reviewed_by = ?, review_comment = ?, reviewed_at = ?
            WHERE id = ?
            """,
            (actor_user_id, payload.review_comment, reviewed_at, change_request_id),
        )
        out = conn.execute("SELECT * FROM change_requests WHERE id = ?", (change_request_id,)).fetchone()
    return ChangeRequestOut(**dict(out))
