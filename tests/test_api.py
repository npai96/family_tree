from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.api.main as main


def build_client(tmp_path: Path) -> TestClient:
    main.DB_PATH = tmp_path / "test.db"
    main.MEDIA_DIR = tmp_path / "media"
    main.init_db()
    return TestClient(main.app)


def create_user(client: TestClient, name: str) -> str:
    response = client.post("/users", json={"display_name": name})
    assert response.status_code == 200
    return response.json()["id"]


def test_health(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_end_to_end_graph_flow_with_membership(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    editor_id = create_user(client, "Editor")

    circle = client.post("/circles", json={"name": "Pai Family"}, headers={"X-User-Id": owner_id})
    assert circle.status_code == 200
    circle_id = circle.json()["id"]

    add_member = client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": editor_id, "role": "editor"},
        headers={"X-User-Id": owner_id},
    )
    assert add_member.status_code == 200

    parent = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Anand Pai", "religion": "Hindu"},
        headers={"X-User-Id": editor_id},
    )
    assert parent.status_code == 200
    parent_id = parent.json()["id"]

    child = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Maya Pai", "religion": "Hindu"},
        headers={"X-User-Id": editor_id},
    )
    assert child.status_code == 200
    child_id = child.json()["id"]

    rel = client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": parent_id, "to_person_id": child_id, "relationship_type": "parent_of"},
        headers={"X-User-Id": editor_id},
    )
    assert rel.status_code == 200

    descendants = client.get(
        f"/circles/{circle_id}/graph/subgraph",
        params={"root_person_id": parent_id, "direction": "descendants", "depth": 3},
        headers={"X-User-Id": owner_id},
    )
    assert descendants.status_code == 200
    assert len(descendants.json()["persons"]) == 2
    assert len(descendants.json()["relationships"]) == 1


def test_change_request_approval_updates_person(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    viewer_id = create_user(client, "Viewer")

    circle = client.post("/circles", json={"name": "Nair Family"}, headers={"X-User-Id": owner_id})
    circle_id = circle.json()["id"]

    member = client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": viewer_id, "role": "viewer"},
        headers={"X-User-Id": owner_id},
    )
    assert member.status_code == 200

    person = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Lakshmi Nair", "religion": "Hindu"},
        headers={"X-User-Id": owner_id},
    )
    person_id = person.json()["id"]

    change_request = client.post(
        f"/circles/{circle_id}/change-requests",
        json={"entity_type": "person", "entity_id": person_id, "proposed_patch_json": {"religion": "Spiritual"}},
        headers={"X-User-Id": viewer_id},
    )
    assert change_request.status_code == 200
    cr_id = change_request.json()["id"]

    approve = client.post(
        f"/circles/{circle_id}/change-requests/{cr_id}/approve",
        json={"review_comment": "Approved"},
        headers={"X-User-Id": owner_id},
    )
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    persons = client.get(f"/circles/{circle_id}/persons", headers={"X-User-Id": owner_id})
    assert persons.status_code == 200
    assert persons.json()[0]["religion"] == "Spiritual"

    revisions = client.get(
        f"/circles/{circle_id}/persons/{person_id}/revisions",
        headers={"X-User-Id": owner_id},
    )
    assert revisions.status_code == 200
    rev_rows = revisions.json()
    assert len(rev_rows) >= 2
    assert rev_rows[0]["reason"].startswith("change_request_approved:")
    latest_snapshot = rev_rows[0]["snapshot_json"]
    assert '"religion": "Spiritual"' in latest_snapshot


def test_add_member_is_idempotent_and_can_update_non_owner_role(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    editor_id = create_user(client, "Editor")

    circle = client.post("/circles", json={"name": "Pai Family"}, headers={"X-User-Id": owner_id})
    circle_id = circle.json()["id"]

    first_add = client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": editor_id, "role": "editor"},
        headers={"X-User-Id": owner_id},
    )
    assert first_add.status_code == 200
    assert first_add.json()["role"] == "editor"

    second_add_same_role = client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": editor_id, "role": "editor"},
        headers={"X-User-Id": owner_id},
    )
    assert second_add_same_role.status_code == 200
    assert second_add_same_role.json()["role"] == "editor"

    update_role = client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": editor_id, "role": "viewer"},
        headers={"X-User-Id": owner_id},
    )
    assert update_role.status_code == 200
    assert update_role.json()["role"] == "viewer"


def test_context_events_and_person_timeline(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    editor_id = create_user(client, "Editor")

    circle = client.post("/circles", json={"name": "Context Family"}, headers={"X-User-Id": owner_id})
    circle_id = circle.json()["id"]

    add_editor = client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": editor_id, "role": "editor"},
        headers={"X-User-Id": owner_id},
    )
    assert add_editor.status_code == 200

    person = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Ravi Kumar", "birth_date": "1950-01-01", "birth_place": "Chennai"},
        headers={"X-User-Id": editor_id},
    )
    assert person.status_code == 200
    person_id = person.json()["id"]

    event = client.post(
        f"/circles/{circle_id}/context-events",
        json={
            "date": "1971-12-16",
            "title": "South Asia geopolitical turning point",
            "event_type": "political",
            "location_name": "South Asia",
            "description": "A major historical shift in the region",
        },
        headers={"X-User-Id": editor_id},
    )
    assert event.status_code == 200
    event_id = event.json()["id"]

    link = client.post(
        f"/circles/{circle_id}/persons/{person_id}/context-links",
        json={"context_event_id": event_id, "relevance_note": "He discussed this often"},
        headers={"X-User-Id": editor_id},
    )
    assert link.status_code == 200

    timeline = client.get(
        f"/circles/{circle_id}/persons/{person_id}/timeline",
        headers={"X-User-Id": owner_id},
    )
    assert timeline.status_code == 200
    body = timeline.json()
    assert len(body) == 2
    assert body[0]["date"] == "1950-01-01"
    assert body[0]["kind"] == "life"
    assert body[0]["ref_id"] == person_id
    assert body[1]["date"] == "1971-12-16"
    assert body[1]["kind"] == "context"
    assert body[1]["ref_id"] == event_id

    event_persons = client.get(
        f"/circles/{circle_id}/context-events/{event_id}/persons",
        headers={"X-User-Id": owner_id},
    )
    assert event_persons.status_code == 200
    linked = event_persons.json()
    assert len(linked) == 1
    assert linked[0]["id"] == person_id


def test_media_upload_list_and_download(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    editor_id = create_user(client, "Editor")

    circle = client.post("/circles", json={"name": "Media Family"}, headers={"X-User-Id": owner_id})
    circle_id = circle.json()["id"]
    add_editor = client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": editor_id, "role": "editor"},
        headers={"X-User-Id": owner_id},
    )
    assert add_editor.status_code == 200

    person = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Media Person"},
        headers={"X-User-Id": editor_id},
    )
    person_id = person.json()["id"]

    upload = client.post(
        f"/circles/{circle_id}/persons/{person_id}/media",
        files={"file": ("note.txt", b"hello family media", "text/plain")},
        headers={"X-User-Id": editor_id},
    )
    assert upload.status_code == 200
    asset = upload.json()
    asset_id = asset["id"]
    assert asset["bytes"] > 0
    assert asset["original_filename"] == "note.txt"

    listed = client.get(
        f"/circles/{circle_id}/persons/{person_id}/media",
        headers={"X-User-Id": owner_id},
    )
    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 1
    assert body[0]["id"] == asset_id

    downloaded = client.get(
        f"/circles/{circle_id}/media/{asset_id}/download",
        headers={"X-User-Id": owner_id},
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"hello family media"

    downloaded_via_query = client.get(
        f"/circles/{circle_id}/media/{asset_id}/download",
        params={"user_id": owner_id},
    )
    assert downloaded_via_query.status_code == 200
    assert downloaded_via_query.content == b"hello family media"


def test_person_places_and_migration_geojson(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    editor_id = create_user(client, "Editor")

    circle = client.post("/circles", json={"name": "Migration Family"}, headers={"X-User-Id": owner_id})
    circle_id = circle.json()["id"]
    add_editor = client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": editor_id, "role": "editor"},
        headers={"X-User-Id": owner_id},
    )
    assert add_editor.status_code == 200

    person = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Arun Pai"},
        headers={"X-User-Id": editor_id},
    )
    person_id = person.json()["id"]

    place1 = client.post(
        f"/circles/{circle_id}/persons/{person_id}/places",
        json={
            "place_name": "Udupi",
            "country": "India",
            "lat": 13.3409,
            "lng": 74.7421,
            "from_date": "1960-01-01",
        },
        headers={"X-User-Id": editor_id},
    )
    assert place1.status_code == 200

    place2 = client.post(
        f"/circles/{circle_id}/persons/{person_id}/places",
        json={
            "place_name": "Singapore",
            "country": "Singapore",
            "lat": 1.3521,
            "lng": 103.8198,
            "from_date": "1980-01-01",
        },
        headers={"X-User-Id": editor_id},
    )
    assert place2.status_code == 200

    listed = client.get(
        f"/circles/{circle_id}/persons/{person_id}/places",
        headers={"X-User-Id": owner_id},
    )
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 2
    assert rows[0]["place_name"] == "Udupi"
    assert rows[1]["place_name"] == "Singapore"

    geojson = client.get(
        f"/circles/{circle_id}/persons/{person_id}/migration-geojson",
        headers={"X-User-Id": owner_id},
    )
    assert geojson.status_code == 200
    fc = geojson.json()
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 3  # one line + two points
    assert fc["features"][0]["geometry"]["type"] == "LineString"


def test_discussion_threads_messages_and_ws(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    editor_id = create_user(client, "Editor")

    circle = client.post("/circles", json={"name": "Chat Family"}, headers={"X-User-Id": owner_id})
    circle_id = circle.json()["id"]
    add_editor = client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": editor_id, "role": "editor"},
        headers={"X-User-Id": owner_id},
    )
    assert add_editor.status_code == 200

    person = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Chat Person"},
        headers={"X-User-Id": editor_id},
    )
    person_id = person.json()["id"]

    thread = client.post(
        f"/circles/{circle_id}/threads",
        json={"entity_type": "person", "entity_id": person_id},
        headers={"X-User-Id": owner_id},
    )
    assert thread.status_code == 200
    thread_id = thread.json()["id"]

    with client.websocket_connect(f"/ws/circles/{circle_id}?user_id={owner_id}") as ws:
        joined = ws.receive_json()
        assert joined["type"] == "presence.updated"
        assert joined["state"] == "joined"

        msg = client.post(
            f"/circles/{circle_id}/threads/{thread_id}/messages",
            json={"content": "Oral history note"},
            headers={"X-User-Id": editor_id},
        )
        assert msg.status_code == 200

        event = ws.receive_json()
        assert event["type"] == "thread.message.created"
        assert event["thread_id"] == thread_id
        assert event["message"]["content"] == "Oral history note"

    listed = client.get(
        f"/circles/{circle_id}/threads/{thread_id}/messages",
        headers={"X-User-Id": owner_id},
    )
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["content"] == "Oral history note"
