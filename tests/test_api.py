from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.api.main as main


def build_client(tmp_path: Path) -> TestClient:
    main.DB_PATH = tmp_path / "test.db"
    main.MEDIA_DIR = tmp_path / "media"
    main.ALLOW_LEGACY_X_USER_ID = True
    main.init_db()
    return TestClient(main.app)


def create_user(client: TestClient, name: str) -> str:
    response = client.post("/users", json={"display_name": name})
    assert response.status_code == 200
    return response.json()["id"]


def auth_headers_for(client: TestClient, user_id: str) -> dict[str, str]:
    login = client.post("/auth/login", json={"user_id": user_id})
    assert login.status_code == 200
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


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

    ancestors = client.get(
        f"/circles/{circle_id}/graph/subgraph",
        params={"root_person_id": child_id, "direction": "ancestors", "depth": 3},
        headers={"X-User-Id": owner_id},
    )
    assert ancestors.status_code == 200
    ancestor_edges = ancestors.json()["relationships"]
    assert len(ancestor_edges) == 1
    assert ancestor_edges[0]["from_person_id"] == child_id
    assert ancestor_edges[0]["to_person_id"] == parent_id
    assert ancestor_edges[0]["relationship_type"] == "child_of"


def test_subgraph_excludes_spouse_edges_from_lineage_traversal(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    circle = client.post("/circles", json={"name": "Lineage Family"}, headers={"X-User-Id": owner_id})
    circle_id = circle.json()["id"]

    mom_id = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Mom"},
        headers={"X-User-Id": owner_id},
    ).json()["id"]
    dad_id = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Dad"},
        headers={"X-User-Id": owner_id},
    ).json()["id"]
    child_id = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Child"},
        headers={"X-User-Id": owner_id},
    ).json()["id"]

    assert client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": mom_id, "to_person_id": child_id, "relationship_type": "parent_of"},
        headers={"X-User-Id": owner_id},
    ).status_code == 200
    assert client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": dad_id, "to_person_id": child_id, "relationship_type": "parent_of"},
        headers={"X-User-Id": owner_id},
    ).status_code == 200
    assert client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": mom_id, "to_person_id": dad_id, "relationship_type": "spouse_of"},
        headers={"X-User-Id": owner_id},
    ).status_code == 200

    descendants = client.get(
        f"/circles/{circle_id}/graph/subgraph",
        params={"root_person_id": mom_id, "direction": "descendants", "depth": 2},
        headers={"X-User-Id": owner_id},
    )
    assert descendants.status_code == 200
    desc_node_ids = {p["id"] for p in descendants.json()["persons"]}
    desc_edge_types = {r["relationship_type"] for r in descendants.json()["relationships"]}
    assert dad_id not in desc_node_ids
    assert desc_edge_types == {"parent_of"}

    ancestors = client.get(
        f"/circles/{circle_id}/graph/subgraph",
        params={"root_person_id": dad_id, "direction": "ancestors", "depth": 2},
        headers={"X-User-Id": owner_id},
    )
    assert ancestors.status_code == 200
    anc_node_ids = {p["id"] for p in ancestors.json()["persons"]}
    anc_edge_types = {r["relationship_type"] for r in ancestors.json()["relationships"]}
    assert mom_id not in anc_node_ids
    assert anc_edge_types in (set(), {"child_of"})


def test_subgraph_family_expanded_can_include_lateral_relations(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    circle = client.post("/circles", json={"name": "Family Expanded"}, headers={"X-User-Id": owner_id})
    circle_id = circle.json()["id"]

    mom_id = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Mom"},
        headers={"X-User-Id": owner_id},
    ).json()["id"]
    dad_id = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Dad"},
        headers={"X-User-Id": owner_id},
    ).json()["id"]
    child_id = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Child"},
        headers={"X-User-Id": owner_id},
    ).json()["id"]

    assert client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": mom_id, "to_person_id": child_id, "relationship_type": "parent_of"},
        headers={"X-User-Id": owner_id},
    ).status_code == 200
    assert client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": dad_id, "to_person_id": child_id, "relationship_type": "parent_of"},
        headers={"X-User-Id": owner_id},
    ).status_code == 200
    assert client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": mom_id, "to_person_id": dad_id, "relationship_type": "spouse_of"},
        headers={"X-User-Id": owner_id},
    ).status_code == 200

    descendants_family = client.get(
        f"/circles/{circle_id}/graph/subgraph",
        params={
            "root_person_id": mom_id,
            "direction": "descendants",
            "depth": 2,
            "mode": "family_expanded",
            "lateral_types": "spouse_of",
            "lateral_depth": 1,
        },
        headers={"X-User-Id": owner_id},
    )
    assert descendants_family.status_code == 200
    node_ids = {p["id"] for p in descendants_family.json()["persons"]}
    edge_types = {r["relationship_type"] for r in descendants_family.json()["relationships"]}
    assert dad_id in node_ids
    assert "spouse_of" in edge_types


def test_subgraph_timeline_and_migration_geojson(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    circle = client.post("/circles", json={"name": "Subgraph Context"}, headers={"X-User-Id": owner_id})
    circle_id = circle.json()["id"]

    parent_id = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Parent", "birth_date": "1960-01-01", "birth_place": "Chennai"},
        headers={"X-User-Id": owner_id},
    ).json()["id"]
    child_id = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Child", "birth_date": "1990-01-01"},
        headers={"X-User-Id": owner_id},
    ).json()["id"]
    assert client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": parent_id, "to_person_id": child_id, "relationship_type": "parent_of"},
        headers={"X-User-Id": owner_id},
    ).status_code == 200

    event = client.post(
        f"/circles/{circle_id}/context-events",
        json={
            "date": "2000-01-01",
            "title": "Regional event",
            "event_type": "social",
            "description": "Context for family",
        },
        headers={"X-User-Id": owner_id},
    )
    event_id = event.json()["id"]
    assert client.post(
        f"/circles/{circle_id}/persons/{child_id}/context-links",
        json={"context_event_id": event_id, "relevance_note": "affected schooling"},
        headers={"X-User-Id": owner_id},
    ).status_code == 200

    assert client.post(
        f"/circles/{circle_id}/persons/{child_id}/places",
        json={
            "place_name": "Bengaluru",
            "country": "India",
            "lat": 12.9716,
            "lng": 77.5946,
            "from_date": "2005-01-01",
        },
        headers={"X-User-Id": owner_id},
    ).status_code == 200
    assert client.post(
        f"/circles/{circle_id}/persons/{child_id}/places",
        json={
            "place_name": "Singapore",
            "country": "Singapore",
            "lat": 1.3521,
            "lng": 103.8198,
            "from_date": "2015-01-01",
        },
        headers={"X-User-Id": owner_id},
    ).status_code == 200

    timeline = client.get(
        f"/circles/{circle_id}/graph/subgraph/timeline",
        params={
            "root_person_id": child_id,
            "direction": "ancestors",
            "depth": 2,
            "mode": "lineage",
            "from_date": "1980-01-01",
            "to_date": "2010-12-31",
        },
        headers={"X-User-Id": owner_id},
    )
    assert timeline.status_code == 200
    tl = timeline.json()
    assert len(tl) >= 2
    assert all("1980-01-01" <= row["date"] <= "2010-12-31" for row in tl)

    migration_now = client.get(
        f"/circles/{circle_id}/graph/subgraph/migration-geojson",
        params={
            "root_person_id": child_id,
            "direction": "ancestors",
            "depth": 2,
            "mode": "lineage",
        },
        headers={"X-User-Id": owner_id},
    )
    assert migration_now.status_code == 200
    fc = migration_now.json()
    assert fc["type"] == "FeatureCollection"
    assert any(f["geometry"]["type"] == "Point" for f in fc["features"])

    migration_cutoff = client.get(
        f"/circles/{circle_id}/graph/subgraph/migration-geojson",
        params={
            "root_person_id": child_id,
            "direction": "ancestors",
            "depth": 2,
            "mode": "lineage",
            "up_to_date": "2010-12-31",
        },
        headers={"X-User-Id": owner_id},
    )
    assert migration_cutoff.status_code == 200
    fc_cutoff = migration_cutoff.json()
    point_dates = [
        f["properties"].get("from_date")
        for f in fc_cutoff["features"]
        if f["geometry"]["type"] == "Point"
    ]
    assert all((d is None) or (d <= "2010-12-31") for d in point_dates)


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


def test_duplicate_hints_and_duplicate_blocking(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    circle = client.post("/circles", json={"name": "Dup Family"}, headers={"X-User-Id": owner_id})
    circle_id = circle.json()["id"]

    first = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Ravi Pai", "birth_date": "1970-01-01", "birth_place": "Mumbai"},
        headers={"X-User-Id": owner_id},
    )
    assert first.status_code == 200

    hints = client.get(
        f"/circles/{circle_id}/persons/duplicate-hints",
        params={"full_name": "Ravi Pai", "birth_date": "1970-01-01", "birth_place": "Mumbai"},
        headers={"X-User-Id": owner_id},
    )
    assert hints.status_code == 200
    rows = hints.json()
    assert len(rows) == 1
    assert rows[0]["score"] >= 60

    second = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Ravi Pai", "birth_date": "1970-01-01", "birth_place": "Mumbai"},
        headers={"X-User-Id": owner_id},
    )
    assert second.status_code == 409


def test_relationship_validation_and_parent_cycle_block(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    circle = client.post("/circles", json={"name": "Rel Family"}, headers={"X-User-Id": owner_id})
    circle_id = circle.json()["id"]

    a = client.post(f"/circles/{circle_id}/persons", json={"full_name": "A"}, headers={"X-User-Id": owner_id}).json()["id"]
    b = client.post(f"/circles/{circle_id}/persons", json={"full_name": "B"}, headers={"X-User-Id": owner_id}).json()["id"]
    c = client.post(f"/circles/{circle_id}/persons", json={"full_name": "C"}, headers={"X-User-Id": owner_id}).json()["id"]

    invalid = client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": a, "to_person_id": b, "relationship_type": "mentor_of"},
        headers={"X-User-Id": owner_id},
    )
    assert invalid.status_code == 400

    r1 = client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": a, "to_person_id": b, "relationship_type": "parent_of"},
        headers={"X-User-Id": owner_id},
    )
    assert r1.status_code == 200
    r2 = client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": b, "to_person_id": c, "relationship_type": "parent_of"},
        headers={"X-User-Id": owner_id},
    )
    assert r2.status_code == 200

    cycle = client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": c, "to_person_id": a, "relationship_type": "parent_of"},
        headers={"X-User-Id": owner_id},
    )
    assert cycle.status_code == 400


def test_relationship_delete_permissions(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    editor_id = create_user(client, "Editor")
    viewer_id = create_user(client, "Viewer")

    circle = client.post("/circles", json={"name": "Delete Family"}, headers={"X-User-Id": owner_id})
    circle_id = circle.json()["id"]
    add_editor = client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": editor_id, "role": "editor"},
        headers={"X-User-Id": owner_id},
    )
    assert add_editor.status_code == 200
    add_viewer = client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": viewer_id, "role": "viewer"},
        headers={"X-User-Id": owner_id},
    )
    assert add_viewer.status_code == 200

    a = client.post(f"/circles/{circle_id}/persons", json={"full_name": "A"}, headers={"X-User-Id": owner_id}).json()["id"]
    b = client.post(f"/circles/{circle_id}/persons", json={"full_name": "B"}, headers={"X-User-Id": owner_id}).json()["id"]
    rel = client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": a, "to_person_id": b, "relationship_type": "parent_of"},
        headers={"X-User-Id": owner_id},
    )
    assert rel.status_code == 200
    rel_id = rel.json()["id"]

    forbidden = client.delete(
        f"/circles/{circle_id}/relationships/{rel_id}",
        headers={"X-User-Id": viewer_id},
    )
    assert forbidden.status_code == 403

    deleted = client.delete(
        f"/circles/{circle_id}/relationships/{rel_id}",
        headers={"X-User-Id": editor_id},
    )
    assert deleted.status_code == 200

    rels = client.get(f"/circles/{circle_id}/relationships", headers={"X-User-Id": owner_id})
    assert rels.status_code == 200
    assert rels.json() == []


def test_relationship_update_permissions_and_cycle_checks(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    editor_id = create_user(client, "Editor")
    viewer_id = create_user(client, "Viewer")

    circle = client.post("/circles", json={"name": "Update Family"}, headers={"X-User-Id": owner_id})
    circle_id = circle.json()["id"]
    assert client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": editor_id, "role": "editor"},
        headers={"X-User-Id": owner_id},
    ).status_code == 200
    assert client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": viewer_id, "role": "viewer"},
        headers={"X-User-Id": owner_id},
    ).status_code == 200

    a = client.post(f"/circles/{circle_id}/persons", json={"full_name": "A"}, headers={"X-User-Id": owner_id}).json()["id"]
    b = client.post(f"/circles/{circle_id}/persons", json={"full_name": "B"}, headers={"X-User-Id": owner_id}).json()["id"]
    c = client.post(f"/circles/{circle_id}/persons", json={"full_name": "C"}, headers={"X-User-Id": owner_id}).json()["id"]

    rel_ab = client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": a, "to_person_id": b, "relationship_type": "parent_of"},
        headers={"X-User-Id": owner_id},
    )
    assert rel_ab.status_code == 200
    rel_ab_id = rel_ab.json()["id"]

    rel_bc = client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": b, "to_person_id": c, "relationship_type": "parent_of"},
        headers={"X-User-Id": owner_id},
    )
    assert rel_bc.status_code == 200

    forbidden = client.patch(
        f"/circles/{circle_id}/relationships/{rel_ab_id}",
        json={"relationship_type": "spouse_of"},
        headers={"X-User-Id": viewer_id},
    )
    assert forbidden.status_code == 403

    updated = client.patch(
        f"/circles/{circle_id}/relationships/{rel_ab_id}",
        json={"relationship_type": "child_of"},
        headers={"X-User-Id": editor_id},
    )
    assert updated.status_code == 200
    assert updated.json()["relationship_type"] == "child_of"

    # Turning A->B into parent_of while B->C exists should still be valid.
    valid_parent = client.patch(
        f"/circles/{circle_id}/relationships/{rel_ab_id}",
        json={"relationship_type": "parent_of"},
        headers={"X-User-Id": editor_id},
    )
    assert valid_parent.status_code == 200

    # Updating A->B to C->B as parent_of creates cycle: B->C and C->B.
    cycle = client.patch(
        f"/circles/{circle_id}/relationships/{rel_ab_id}",
        json={"from_person_id": c, "to_person_id": b, "relationship_type": "parent_of"},
        headers={"X-User-Id": editor_id},
    )
    assert cycle.status_code == 400


def test_undirected_relationships_are_canonical_and_delete_reverse_duplicates(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    circle = client.post("/circles", json={"name": "Undirected Family"}, headers={"X-User-Id": owner_id})
    circle_id = circle.json()["id"]

    a = client.post(f"/circles/{circle_id}/persons", json={"full_name": "A"}, headers={"X-User-Id": owner_id}).json()["id"]
    b = client.post(f"/circles/{circle_id}/persons", json={"full_name": "B"}, headers={"X-User-Id": owner_id}).json()["id"]

    first = client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": b, "to_person_id": a, "relationship_type": "spouse_of"},
        headers={"X-User-Id": owner_id},
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["from_person_id"] == min(a, b)
    assert first_body["to_person_id"] == max(a, b)

    second = client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": a, "to_person_id": b, "relationship_type": "spouse_of"},
        headers={"X-User-Id": owner_id},
    )
    assert second.status_code == 409

    # Inject legacy reverse duplicate directly to ensure delete cleans both rows.
    with main.get_conn() as conn:
        canonical_from = first_body["from_person_id"]
        canonical_to = first_body["to_person_id"]
        conn.execute(
            """
            INSERT INTO relationships (id, circle_id, from_person_id, to_person_id, relationship_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("legacy-reverse-id", circle_id, canonical_to, canonical_from, "spouse_of", main.utc_now()),
        )

    deleted = client.delete(
        f"/circles/{circle_id}/relationships/{first_body['id']}",
        headers={"X-User-Id": owner_id},
    )
    assert deleted.status_code == 200
    rels = client.get(f"/circles/{circle_id}/relationships", headers={"X-User-Id": owner_id})
    assert rels.status_code == 200
    assert rels.json() == []


def test_person_patch_updates_profile_and_revisions(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    editor_id = create_user(client, "Editor")
    viewer_id = create_user(client, "Viewer")

    circle = client.post("/circles", json={"name": "Profile Family"}, headers={"X-User-Id": owner_id})
    circle_id = circle.json()["id"]
    add_editor = client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": editor_id, "role": "editor"},
        headers={"X-User-Id": owner_id},
    )
    assert add_editor.status_code == 200
    add_viewer = client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": viewer_id, "role": "viewer"},
        headers={"X-User-Id": owner_id},
    )
    assert add_viewer.status_code == 200

    person = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Meera", "birth_date": "1980-01-01"},
        headers={"X-User-Id": owner_id},
    )
    assert person.status_code == 200
    person_id = person.json()["id"]

    forbidden = client.patch(
        f"/circles/{circle_id}/persons/{person_id}",
        json={"occupation": "Engineer"},
        headers={"X-User-Id": viewer_id},
    )
    assert forbidden.status_code == 403

    updated = client.patch(
        f"/circles/{circle_id}/persons/{person_id}",
        json={
            "occupation": "Engineer",
            "hobbies": "Classical music",
            "birth_place": "Pune",
            "revision_reason": "profile_edit",
        },
        headers={"X-User-Id": editor_id},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["occupation"] == "Engineer"
    assert body["hobbies"] == "Classical music"
    assert body["birth_place"] == "Pune"

    revisions = client.get(
        f"/circles/{circle_id}/persons/{person_id}/revisions",
        headers={"X-User-Id": owner_id},
    )
    assert revisions.status_code == 200
    rev_rows = revisions.json()
    assert len(rev_rows) >= 2
    assert rev_rows[0]["reason"] == "profile_edit"
    assert '"occupation": "Engineer"' in rev_rows[0]["snapshot_json"]


def test_auth_login_and_bearer_access(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")

    login = client.post("/auth/login", json={"user_id": owner_id})
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["id"] == owner_id

    circle = client.post(
        "/circles",
        json={"name": "Bearer Family"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert circle.status_code == 200
    circle_id = circle.json()["id"]

    person = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Bearer User"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert person.status_code == 200


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


def test_auth_hardening_rejects_legacy_header_when_disabled(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    main.ALLOW_LEGACY_X_USER_ID = False
    try:
        denied = client.post("/circles", json={"name": "No Header Auth"}, headers={"X-User-Id": owner_id})
        assert denied.status_code == 401

        auth_headers = auth_headers_for(client, owner_id)
        allowed = client.post("/circles", json={"name": "Bearer Only"}, headers=auth_headers)
        assert allowed.status_code == 200
    finally:
        main.ALLOW_LEGACY_X_USER_ID = True


def test_invitation_transfer_and_audit_flow(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    editor_id = create_user(client, "Editor")
    viewer_id = create_user(client, "Viewer")

    owner_headers = auth_headers_for(client, owner_id)
    editor_headers = auth_headers_for(client, editor_id)
    viewer_headers = auth_headers_for(client, viewer_id)

    circle = client.post("/circles", json={"name": "Invite Family"}, headers=owner_headers)
    assert circle.status_code == 200
    circle_id = circle.json()["id"]

    invite = client.post(
        f"/circles/{circle_id}/invitations",
        json={"invited_user_id": editor_id, "role": "editor"},
        headers=owner_headers,
    )
    assert invite.status_code == 200
    invitation_id = invite.json()["id"]

    my_invites = client.get("/invitations", headers=editor_headers)
    assert my_invites.status_code == 200
    assert any(row["id"] == invitation_id and row["status"] == "pending" for row in my_invites.json())

    accepted = client.post(
        f"/invitations/{invitation_id}/respond",
        json={"action": "accept"},
        headers=editor_headers,
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"

    members = client.get(f"/circles/{circle_id}/members", headers=owner_headers)
    assert members.status_code == 200
    role_by_user = {row["user_id"]: row["role"] for row in members.json()}
    assert role_by_user[editor_id] == "editor"

    add_viewer = client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": viewer_id, "role": "viewer"},
        headers=owner_headers,
    )
    assert add_viewer.status_code == 200

    transfer = client.post(
        f"/circles/{circle_id}/ownership/transfer",
        json={"new_owner_user_id": viewer_id},
        headers=owner_headers,
    )
    assert transfer.status_code == 200
    assert transfer.json()["user_id"] == viewer_id
    assert transfer.json()["role"] == "owner"

    former_owner_members = client.get(f"/circles/{circle_id}/members", headers=viewer_headers)
    assert former_owner_members.status_code == 200
    role_by_user = {row["user_id"]: row["role"] for row in former_owner_members.json()}
    assert role_by_user[owner_id] == "viewer"
    assert role_by_user[viewer_id] == "owner"

    audit = client.get(f"/circles/{circle_id}/audit-logs", headers=viewer_headers)
    assert audit.status_code == 200
    actions = [row["action"] for row in audit.json()]
    assert "circle.created" in actions
    assert "invitation.created" in actions
    assert "invitation.accepted" in actions
    assert "ownership.transferred" in actions

    # Former owner should no longer be able to execute owner-only operations.
    former_owner_add = client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": owner_id, "role": "viewer"},
        headers=owner_headers,
    )
    assert former_owner_add.status_code == 403
