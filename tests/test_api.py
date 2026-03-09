from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

import app.api.main as main


def build_client(tmp_path: Path) -> TestClient:
    main.DB_PATH = tmp_path / "test.db"
    main.init_db()
    return TestClient(main.app)


def test_health(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_circle_person_relationship_and_subgraph(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    circle = client.post("/circles", json={"name": "Pai Family"}).json()
    circle_id = circle["id"]

    parent = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Anand Pai", "religion": "Hindu"},
    ).json()
    child = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Maya Pai", "religion": "Hindu"},
    ).json()

    rel = client.post(
        f"/circles/{circle_id}/relationships",
        json={
            "from_person_id": parent["id"],
            "to_person_id": child["id"],
            "relationship_type": "parent_of",
        },
    )
    assert rel.status_code == 200

    descendants = client.get(
        f"/circles/{circle_id}/graph/subgraph",
        params={
            "root_person_id": parent["id"],
            "direction": "descendants",
            "depth": 3,
        },
    )
    assert descendants.status_code == 200
    desc_body = descendants.json()
    assert len(desc_body["persons"]) == 2
    assert len(desc_body["relationships"]) == 1

    ancestors = client.get(
        f"/circles/{circle_id}/graph/subgraph",
        params={
            "root_person_id": child["id"],
            "direction": "ancestors",
            "depth": 3,
        },
    )
    assert ancestors.status_code == 200
    anc_body = ancestors.json()
    assert len(anc_body["persons"]) == 2
    assert len(anc_body["relationships"]) == 1
