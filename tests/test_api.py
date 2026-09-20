import asyncio
import hashlib
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import Headers
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.api.main as main
from app.api.db_config import load_database_config
from app.api.db_runtime import INTEGRITY_ERRORS, _adapt_sql_placeholders, configure_database, execute
from app.api.observability import REQUEST_METRICS, RequestMetrics, RequestObservabilityMiddleware
from app.api.privacy import person_response_select_clause, redact_sensitive_json
from app.api.security import load_runtime_security_config

try:
    import psycopg
except ImportError:  # pragma: no cover - optional in some local envs
    psycopg = None


POSTGRES_TEST_DATABASE_URL = os.getenv(
    "POSTGRES_TEST_DATABASE_URL",
    "postgresql://family_tree:family_tree_dev@127.0.0.1:5433/family_tree",
)
POSTGRES_TESTS_ENABLED = os.getenv("RUN_POSTGRES_TESTS", "false").strip().lower() in {"1", "true", "yes", "on"}
POSTGRES_RUNTIME_SQL = (ROOT / "db" / "runtime_postgres.sql").read_text()
postgres_only = pytest.mark.skipif(
    not POSTGRES_TESTS_ENABLED or psycopg is None,
    reason="Postgres-backed tests are opt-in. Set RUN_POSTGRES_TESTS=true and ensure psycopg is installed in .venv.",
)

JPEG_BYTES = b"\xff\xd8\xff\xe0family-tree-jpeg"
PNG_BYTES = b"\x89PNG\r\n\x1a\nfamily-tree-png"


def build_client(tmp_path: Path) -> TestClient:
    configure_database(db_path=tmp_path / "test.db")
    main.MEDIA_DIR = tmp_path / "media"
    main.APP_ENVIRONMENT = "test"
    main.REVIEW_AUTH_ENABLED = True
    main.ALLOW_LEGACY_X_USER_ID = True
    main.METRICS_ENABLED = True
    main.METRICS_BEARER_TOKEN_DIGEST = None
    main.init_db(main.MEDIA_DIR)
    return TestClient(main.app)


def reset_postgres_schema() -> None:
    assert psycopg is not None
    with psycopg.connect(POSTGRES_TEST_DATABASE_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE;")
            cur.execute("CREATE SCHEMA public;")


def build_postgres_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    reset_postgres_schema()
    monkeypatch.setenv("POSTGRES_RUNTIME_ENABLED", "true")
    configure_database(database_url=POSTGRES_TEST_DATABASE_URL)
    main.MEDIA_DIR = tmp_path / "media"
    main.APP_ENVIRONMENT = "test"
    main.REVIEW_AUTH_ENABLED = True
    main.ALLOW_LEGACY_X_USER_ID = True
    main.METRICS_ENABLED = True
    main.METRICS_BEARER_TOKEN_DIGEST = None
    main.init_db(main.MEDIA_DIR)
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
    assert response.json()["db_backend"] == "sqlite"
    assert response.json()["environment"] == "test"
    assert response.json()["auth_mode"] == "review_unverified"
    assert response.json()["review_auth_enabled"] is True
    assert response.json()["legacy_user_header_enabled"] is True
    assert response.json()["metrics_enabled"] is True
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert "geolocation=()" in response.headers["permissions-policy"]


def test_request_metrics_are_bounded_and_report_budget_status() -> None:
    metrics = RequestMetrics()
    for duration_ms in [10.0] * 18 + [300.0, 350.0]:
        metrics.record("GET", "/circles/{circle_id}/persons", 200, duration_ms)
    for duration_ms in [300.0] * 20:
        metrics.record("POST", "/circles/{circle_id}/persons", 201, duration_ms)
    metrics.record("BREW", "attacker-controlled-raw-path", 503, 9000.0)

    snapshot = metrics.snapshot()
    routes = {(row["method"], row["route"]): row for row in snapshot["routes"]}
    slow_read = routes[("GET", "/circles/{circle_id}/persons")]
    write = routes[("POST", "/circles/{circle_id}/persons")]
    bounded_unknown = routes[("OTHER", "<unmatched>")]

    assert snapshot["scope"] == "process"
    assert snapshot["minimum_budget_samples"] == 20
    assert snapshot["latency_bucket_upper_bounds_ms"][-1] is None
    assert slow_read["p95_upper_bound_ms"] == 400.0
    assert slow_read["p95_target_ms"] == 250.0
    assert slow_read["budget_status"] == "exceeded"
    assert write["p95_upper_bound_ms"] == 400.0
    assert write["budget_status"] == "within"
    assert bounded_unknown["server_error_count"] == 1
    assert bounded_unknown["budget_status"] == "insufficient_samples"


def test_metrics_endpoint_reports_route_templates_without_entity_ids(tmp_path: Path) -> None:
    REQUEST_METRICS.reset()
    client = build_client(tmp_path)
    owner_id = create_user(client, "Metrics Owner")
    owner_headers = auth_headers_for(client, owner_id)
    circle_id = client.post(
        "/circles",
        json={"name": "Metrics Circle"},
        headers=owner_headers,
    ).json()["id"]
    assert client.get(f"/circles/{circle_id}/persons", headers=owner_headers).status_code == 200

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body_text = response.text
    assert circle_id not in body_text
    assert owner_id not in body_text
    routes = {(row["method"], row["route"]): row for row in response.json()["routes"]}
    assert routes[("GET", "/circles/{circle_id}/persons")]["request_count"] == 1
    assert routes[("POST", "/users")]["request_count"] == 1


def test_deployed_metrics_require_explicit_enablement_and_operator_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = build_client(tmp_path)
    operator_token = "metrics-operator-token-with-32-characters"

    monkeypatch.setattr(main, "METRICS_ENABLED", False)
    assert client.get("/metrics").status_code == 404

    monkeypatch.setattr(main, "METRICS_ENABLED", True)
    monkeypatch.setattr(main, "METRICS_BEARER_TOKEN_DIGEST", main.digest_token(operator_token))
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong-token"}).status_code == 401
    allowed = client.get(
        "/metrics",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert allowed.status_code == 200
    assert allowed.headers["cache-control"] == "no-store"


def test_request_observability_headers_and_logs_redact_query_values(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    client = build_client(tmp_path)
    caplog.set_level(logging.INFO, logger="family_tree.request")
    secret_query_value = "must-not-enter-request-logs"

    response = client.get(f"/health?debug_token={secret_query_value}")
    second = client.get("/health")
    missing = client.get("/missing-route")

    request_id = response.headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{16}", request_id)
    assert second.headers["x-request-id"] != request_id
    assert re.fullmatch(r"app;dur=\d+\.\d{2}", response.headers["server-timing"])

    matching_records = [
        record for record in caplog.records
        if record.name == "family_tree.request" and request_id in record.getMessage()
    ]
    assert len(matching_records) == 1
    event = json.loads(matching_records[0].getMessage())
    assert event["event"] == "http_request"
    assert event["method"] == "GET"
    assert event["route"] == "/health"
    assert event["status_code"] == 200
    assert event["outcome"] == "success"
    assert event["duration_ms"] >= 0
    assert secret_query_value not in matching_records[0].getMessage()
    missing_record = next(
        record for record in caplog.records
        if missing.headers["x-request-id"] in record.getMessage()
    )
    missing_event = json.loads(missing_record.getMessage())
    assert missing_event["route"] == "<unmatched>"
    assert missing_event["status_code"] == 404
    assert missing_event["outcome"] == "client_error"


def test_unhandled_errors_return_a_safe_reference_without_logging_the_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken_app = FastAPI()
    broken_app.add_middleware(RequestObservabilityMiddleware)

    @broken_app.get("/explode")
    def explode() -> None:
        raise RuntimeError("private-family-value-must-not-be-logged")

    caplog.set_level(logging.ERROR, logger="family_tree.request")
    response = TestClient(broken_app).get("/explode")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Unexpected server error",
        "request_id": response.headers["x-request-id"],
    }
    assert response.headers["server-timing"].startswith("app;dur=")
    record = next(record for record in caplog.records if response.headers["x-request-id"] in record.getMessage())
    event = json.loads(record.getMessage())
    assert event["route"] == "/explode"
    assert event["outcome"] == "server_error"
    assert event["error_type"] == "RuntimeError"
    assert event["stack"][-1]["function"] == "explode"
    assert "private-family-value-must-not-be-logged" not in record.getMessage()


def test_cors_allows_only_explicit_local_browser_origins(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    allowed_origin = "http://localhost:8000"

    allowed = client.get("/health", headers={"Origin": allowed_origin})
    assert allowed.headers["access-control-allow-origin"] == allowed_origin
    assert allowed.headers["access-control-expose-headers"] == "X-Request-Id, Server-Timing"
    assert "access-control-allow-credentials" not in allowed.headers

    preflight = client.options(
        "/health",
        headers={
            "Origin": allowed_origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == allowed_origin

    untrusted = client.get("/health", headers={"Origin": "https://untrusted.example"})
    assert "access-control-allow-origin" not in untrusted.headers


def test_request_logs_use_route_templates_instead_of_entity_ids(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Log Privacy Owner")
    owner_headers = auth_headers_for(client, owner_id)
    circle_id = client.post(
        "/circles",
        json={"name": "Log Privacy Circle"},
        headers=owner_headers,
    ).json()["id"]
    private_query_value = "private-family-search"
    caplog.clear()
    caplog.set_level(logging.INFO, logger="family_tree.request")

    response = client.get(
        f"/circles/{circle_id}/persons?search={private_query_value}",
        headers=owner_headers,
    )

    request_id = response.headers["x-request-id"]
    record = next(record for record in caplog.records if request_id in record.getMessage())
    event = json.loads(record.getMessage())
    assert event["route"] == "/circles/{circle_id}/persons"
    assert circle_id not in record.getMessage()
    assert private_query_value not in record.getMessage()


def test_web_app_exposes_signed_out_recovery_state(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.get("/")
    app_asset = client.get("/assets/app.js")
    bootstrap_asset = client.get("/assets/bootstrap.js")
    page_source = "\n".join((response.text, app_asset.text, bootstrap_asset.text))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert app_asset.status_code == 200
    assert bootstrap_asset.status_code == 200
    assert "Continue your family archive" in page_source
    assert "Your session expired. Sign in again." in page_source
    assert 'className: "graph-controls-grid"' in page_source
    assert "rememberedUserStillExists" in page_source
    assert "/media-previews" in page_source
    assert ".slice(0, 80)" not in page_source
    assert "Checking this deployment" in page_source
    assert 'authState === "checking"' in page_source
    assert "/runtime-config" in page_source
    assert "Authentication is locked for this deployment" in page_source
    assert "Review auth · no identity proof" in page_source
    assert "/access-tickets" in page_source
    assert "token=${encodeURIComponent(authToken)}" not in page_source
    assert "user_id=${encodeURIComponent(activeUserId" not in page_source
    assert "family-tree-ticket.${access.ticket}" in page_source
    assert "/ws/circles/${selectedCircle}?ticket=" not in page_source
    assert 'current.startsWith("Realtime connection") ? "" : current' in page_source
    assert "LARGE_GRAPH_NODE_THRESHOLD = 180" in page_source
    assert "LARGE_GRAPH_EDGE_THRESHOLD = 320" in page_source
    assert "GRAPH_FIRST_FRAME_BUDGET_MS = 1200" in page_source
    assert "window.__familyTreeLastGraphRender = detail" in page_source
    assert "Performance overview" in page_source
    assert '.attr("class", "graph-node-card")' in page_source
    assert "graphAbortControllerRef.current.abort()" in page_source
    assert "selectedCircleRef.current !== circleId" in page_source
    assert "new URLSearchParams" in page_source
    assert '<script src="/assets/graph-utils.js"></script>' in page_source
    assert '<script src="/assets/error-utils.js"></script>' in page_source
    assert '<script src="/assets/privacy-utils.js"></script>' in page_source
    assert '<script src="/assets/person-search-utils.js"></script>' in page_source
    assert '.attr("role", "button")' in page_source
    assert '.attr("aria-pressed", "false")' in page_source
    assert "Use arrow keys to move toward connected relatives" in page_source
    assert "MEDIA_ACCEPT" in page_source
    assert "Uploading…" in page_source
    assert "loadMediaPreviews(circleId)" in page_source
    assert "Loading selected circle…" in page_source
    assert "Core family loaded · refreshing collaboration details…" in page_source
    assert "function LazyDetails" in page_source
    assert '"data-content-mounted": contentMounted ? "true" : "false"' in page_source
    assert 'React.createElement(LazyDetails, { className: "card", key: "p", summary: "People & Relationships" }, () => [' in page_source
    assert 'summary: "Media"' in page_source
    assert page_source.count("React.createElement(LazyDetails") == 11
    assert "PANEL_ROW_LIMIT = 80" in page_source
    assert "visiblePeopleRows.map" in page_source
    assert "visibleRelationshipRows.map" in page_source
    assert "personNameById[r.from_person_id]" in page_source
    assert "Show all ${persons.length} people" in page_source
    assert "Show all ${relationships.length} relationships" in page_source
    assert 'className: "person-finder"' in page_source
    assert "PERSON_SEARCH_RESULT_LIMIT = 8" in page_source
    assert "searchPersonIndex(personSearchIndex" in page_source
    assert 'role: "combobox"' in page_source
    assert 'role: "listbox"' in page_source
    assert "choosePersonSearchResult" in page_source
    assert 'className: "graph-root-choice"' in page_source
    assert "function GraphControlField" in page_source
    assert 'label: "Direction"' in page_source
    assert 'label: "Family scope"' in page_source
    assert 'label: "Side relationships"' in page_source
    assert 'name: "root_person_id"' in page_source
    assert '"aria-label": "Root person"' not in page_source
    assert "function openPersonProfile" in page_source
    assert "Open profile for ${p.full_name}" in page_source
    assert "selectPerson(personOptions[0].value)" not in page_source
    assert "function PersonPanelSubject" in page_source
    assert page_source.count("React.createElement(PersonPanelSubject") == 2
    assert "Change with finder" in page_source
    assert '"aria-label": "Media person"' not in page_source
    assert '"aria-label": "Places person"' not in page_source
    assert "mediaAccessNeeded = mediaPanelActivated" in page_source
    assert "!mediaAccessNeeded" in page_source
    assert "!discussionPanelActivated" in page_source
    assert "onFirstOpen: () => setMediaPanelActivated(true)" in page_source
    assert "onFirstOpen: () => setDiscussionPanelActivated(true)" in page_source
    assert "Loading open person panel" in page_source
    assert "function clearSelectedPersonPanelData" in page_source
    assert "personMediaRequestRef.current += 1" in page_source
    assert "personPlacesRequestRef.current += 1" in page_source
    assert "personRevisionsRequestRef.current += 1" in page_source
    assert "discussionLoadRequestRef.current += 1" in page_source
    assert "!mediaPanelActivated" in page_source
    assert "!placesPanelActivated" in page_source
    assert "!revisionsPanelActivated" in page_source
    assert "Loading revision history…" in page_source
    assert "Loading discussion…" in page_source
    assert "Loading media…" in page_source
    assert "Loading places…" in page_source
    assert "onFirstOpen: () => setPlacesPanelActivated(true)" in page_source
    assert "onFirstOpen: () => setRevisionsPanelActivated(true)" in page_source
    assert "Promise.allSettled([\n        loadPersonMedia" not in page_source
    assert "requestIsCurrent" in page_source
    assert "SELECTION_STABILIZE_MS = 80" in page_source
    assert "MANAGEMENT_DEFER_MS = 240" in page_source
    assert "const [m, p, r] = await Promise.all" in page_source
    assert "const supplementalResults = await Promise.allSettled" in page_source
    assert 'if (typeof onCoreReady === "function") onCoreReady();' in page_source
    assert "managementTimer = window.setTimeout" in page_source
    assert "if (managementTimer) window.clearTimeout(managementTimer)" in page_source
    assert page_source.index("const [m, p, r] = await Promise.all") < page_source.index("const supplementalResults = await Promise.allSettled")
    assert "Core family data loaded; a collaboration panel could not refresh" in page_source
    assert "selectedCircleRef.current = nextCircleId" in page_source
    assert "selectedPersonIdRef.current = nextPersonId" in page_source
    assert 'selectedPersonIdRef.current = ""' in page_source
    assert page_source.count("new AbortController()") >= 5
    assert "return () => controller.abort()" in page_source
    assert "window.setTimeout(refreshMediaAccess, 120)" in page_source
    assert "window.setTimeout(connectRealtime, 120)" in page_source
    assert "if (ticketController) ticketController.abort()" in page_source
    assert "responseErrorMessage" in page_source
    assert "formatApiErrorDetail" in page_source
    assert 'response.headers.get("X-Request-Id")' in page_source
    assert "(reference ${requestId})" in page_source
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "script-src 'self' 'unsafe-inline'" not in response.headers["content-security-policy"]
    assert "unpkg.com" not in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "frame-src 'none'" in response.headers["content-security-policy"]
    assert "maps.google.com" not in response.headers["content-security-policy"]
    assert "/assets/vendor/react-18.3.1.production.min.js" in page_source
    assert "/assets/vendor/react-dom-18.3.1.production.min.js" in page_source
    assert "/assets/vendor/d3-7.9.0.min.js" in page_source
    assert response.text.count('integrity="sha384-') == 3
    assert "missingRuntimeDependencies" in page_source
    assert "The interface could not load" in page_source
    assert "Retry loading Viraasat" in page_source
    assert "class AppErrorBoundary extends React.Component" in page_source
    assert "Your family data was not changed" in page_source
    assert "react.development.js" not in page_source
    assert "https://maps.google.com/maps?" not in page_source
    assert 'React.createElement("iframe"' not in page_source
    assert "Viraasat does not load an external map automatically" in page_source
    assert 'rel: "noopener noreferrer"' in page_source
    assert "buildExternalMapUrl" in page_source
    assert "Medical notes are visible only to owners and editors." in page_source
    assert "Viewer mode · profile details are read-only" in page_source
    assert 'profileFieldAccessProps = canEditRecords ? {} : { readOnly: true' in page_source
    assert 'if (!selectedPersonId || !canEditRecords) return;' in page_source
    assert "<style>" not in response.text
    assert '<script src="/assets/app.js"></script>' in response.text


def test_frontend_assets_are_allowlisted_and_revalidated(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.get("/assets/graph-utils.js")
    stylesheet = client.get("/assets/app.css")
    react = client.get("/assets/vendor/react-18.3.1.production.min.js")
    privacy_utils = client.get("/assets/privacy-utils.js")
    error_utils = client.get("/assets/error-utils.js")
    person_search_utils = client.get("/assets/person-search-utils.js")
    missing = client.get("/assets/not-allowed.js")
    revalidated = client.get(
        "/assets/graph-utils.js",
        headers={"If-None-Match": response.headers["etag"]},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["content-type"].startswith("text/javascript")
    assert "findDirectionalGraphNode" in response.text
    assert "describeGraphNode" in response.text
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert react.status_code == 200
    assert react.headers["content-type"].startswith("text/javascript")
    assert react.text.startswith("/**")
    assert privacy_utils.status_code == 200
    assert "buildExternalMapUrl" in privacy_utils.text
    assert error_utils.status_code == 200
    assert person_search_utils.status_code == 200
    assert "searchPersonIndex" in person_search_utils.text
    assert "formatApiErrorDetail" in error_utils.text
    assert revalidated.status_code == 304
    assert revalidated.content == b""
    assert revalidated.headers["etag"] == response.headers["etag"]
    assert revalidated.headers["x-content-type-options"] == "nosniff"
    assert missing.status_code == 404


def test_browser_security_headers_cover_docs_and_not_found_responses(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    docs = client.get("/docs")
    missing = client.get("/does-not-exist")

    assert docs.status_code == 200
    assert "https://cdn.jsdelivr.net" in docs.headers["content-security-policy"]
    assert missing.status_code == 404
    assert missing.headers["x-content-type-options"] == "nosniff"
    assert missing.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" not in missing.headers


@postgres_only
def test_health_postgres(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = build_postgres_client(monkeypatch, tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["db_backend"] == "postgres"
    assert response.json()["environment"] == "test"
    assert response.json()["auth_mode"] == "review_unverified"


def test_runtime_security_config_defaults_and_guards() -> None:
    local = load_runtime_security_config({})
    assert local.environment == "development"
    assert local.review_auth_enabled is True
    assert local.legacy_user_header_enabled is False
    assert local.cors_allowed_origins == (
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    )
    assert local.metrics_enabled is True
    assert local.metrics_bearer_token_digest is None
    assert local.auth_mode == "review_unverified"

    production = load_runtime_security_config({"APP_ENV": "production"})
    assert production.review_auth_enabled is False
    assert production.auth_mode == "disabled"
    assert production.cors_allowed_origins == ()
    assert production.metrics_enabled is False
    assert production.metrics_bearer_token_digest is None

    explicit_review = load_runtime_security_config({
        "APP_ENV": "production",
        "ENABLE_REVIEW_AUTH": "true",
    })
    assert explicit_review.review_auth_enabled is True
    assert explicit_review.legacy_user_header_enabled is False

    explicit_cors = load_runtime_security_config({
        "APP_ENV": "production",
        "CORS_ALLOWED_ORIGINS": "https://Family.Example.com/, http://127.0.0.1:3000, https://family.example.com",
    })
    assert explicit_cors.cors_allowed_origins == (
        "https://family.example.com",
        "http://127.0.0.1:3000",
    )

    metrics_token = "a-unique-production-metrics-token-123456"
    deployed_metrics = load_runtime_security_config({
        "APP_ENV": "production",
        "ENABLE_METRICS_ENDPOINT": "true",
        "METRICS_BEARER_TOKEN": metrics_token,
    })
    assert deployed_metrics.metrics_enabled is True
    assert deployed_metrics.metrics_bearer_token_digest == main.digest_token(metrics_token)

    with pytest.raises(RuntimeError, match="APP_ENV must be one of"):
        load_runtime_security_config({"APP_ENV": "prod"})
    with pytest.raises(RuntimeError, match="ENABLE_REVIEW_AUTH must be one of"):
        load_runtime_security_config({"ENABLE_REVIEW_AUTH": "sometimes"})
    with pytest.raises(RuntimeError, match="may only be enabled"):
        load_runtime_security_config({"APP_ENV": "production", "ALLOW_LEGACY_X_USER_ID": "true"})
    with pytest.raises(RuntimeError, match="requires ENABLE_REVIEW_AUTH"):
        load_runtime_security_config({
            "APP_ENV": "development",
            "ENABLE_REVIEW_AUTH": "false",
            "ALLOW_LEGACY_X_USER_ID": "true",
        })
    with pytest.raises(RuntimeError, match="cannot contain wildcard"):
        load_runtime_security_config({"CORS_ALLOWED_ORIGINS": "*"})
    with pytest.raises(RuntimeError, match="Invalid CORS origin"):
        load_runtime_security_config({"CORS_ALLOWED_ORIGINS": "https://family.example.com/path"})
    with pytest.raises(RuntimeError, match="at least 32 characters is required"):
        load_runtime_security_config({"APP_ENV": "production", "ENABLE_METRICS_ENDPOINT": "true"})
    with pytest.raises(RuntimeError, match="must contain at least 32 characters"):
        load_runtime_security_config({"METRICS_BEARER_TOKEN": "too-short"})


def test_runtime_config_is_public_explicit_and_not_cached(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.get("/runtime-config")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "environment": "test",
        "auth_mode": "review_unverified",
        "review_auth_enabled": True,
        "identity_verification": "none",
        "warning": (
            "Review access is enabled. User selection does not verify identity; "
            "do not expose this mode to untrusted users."
        ),
    }


def test_disabled_deployment_mode_fails_closed_for_review_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Review Owner")
    owner_headers = auth_headers_for(client, owner_id)
    circle_id = client.post(
        "/circles",
        json={"name": "Previously Open Review Circle"},
        headers=owner_headers,
    ).json()["id"]
    websocket_ticket = client.post(
        f"/circles/{circle_id}/access-tickets",
        json={"scope": "websocket"},
        headers=owner_headers,
    ).json()["ticket"]

    monkeypatch.setattr(main, "APP_ENVIRONMENT", "production")
    monkeypatch.setattr(main, "REVIEW_AUTH_ENABLED", False)
    monkeypatch.setattr(main, "ALLOW_LEGACY_X_USER_ID", False)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["auth_mode"] == "disabled"
    assert health.json()["review_auth_enabled"] is False
    assert health.json()["legacy_user_header_enabled"] is False

    runtime = client.get("/runtime-config")
    assert runtime.status_code == 200
    assert runtime.json()["environment"] == "production"
    assert runtime.json()["auth_mode"] == "disabled"
    assert runtime.json()["identity_verification"] == "unavailable"

    assert client.get("/users").status_code == 503
    assert client.post("/users", json={"display_name": "Blocked"}).status_code == 503
    assert client.post("/auth/login", json={"user_id": owner_id}).status_code == 503
    assert client.get("/auth/me", headers=owner_headers).status_code == 401
    assert client.get("/circles", headers=owner_headers).status_code == 401
    assert client.get("/circles", headers={"X-User-Id": owner_id}).status_code == 401
    assert client.post(
        f"/circles/{circle_id}/access-tickets",
        json={"scope": "media"},
        headers=owner_headers,
    ).status_code == 401

    with pytest.raises((WebSocketDisconnect, WebSocketDenialResponse)):
        with client.websocket_connect(
            f"/ws/circles/{circle_id}",
            subprotocols=["family-tree.v1", f"family-tree-ticket.{websocket_ticket}"],
        ) as websocket:
            websocket.receive_json()

    # Logout remains available so a client can still revoke a credential while access is locked.
    assert client.post("/auth/logout", headers=owner_headers).status_code == 204


def test_explicit_production_review_override_stays_visibly_unverified(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = build_client(tmp_path)
    monkeypatch.setattr(main, "APP_ENVIRONMENT", "production")
    monkeypatch.setattr(main, "REVIEW_AUTH_ENABLED", True)
    monkeypatch.setattr(main, "ALLOW_LEGACY_X_USER_ID", False)

    runtime = client.get("/runtime-config")
    assert runtime.status_code == 200
    assert runtime.json()["auth_mode"] == "review_unverified"
    assert runtime.json()["identity_verification"] == "none"
    assert "does not verify identity" in runtime.json()["warning"]

    user = client.post("/users", json={"display_name": "Explicit Reviewer"})
    assert user.status_code == 200
    login = client.post("/auth/login", json={"user_id": user.json()["id"]})
    assert login.status_code == 200


def test_database_config_supports_sqlite_database_url(monkeypatch, tmp_path: Path) -> None:
    sqlite_path = tmp_path / "url.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite://{sqlite_path}")
    monkeypatch.delenv("DB_PATH", raising=False)
    config = load_database_config()
    assert config.backend == "sqlite"
    assert config.sqlite_path == sqlite_path


def test_database_config_marks_postgres_urls(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://family_tree:family_tree_dev@127.0.0.1:5433/family_tree")
    monkeypatch.delenv("DB_PATH", raising=False)
    config = load_database_config()
    assert config.backend == "postgres"
    assert config.sqlite_path is None


def test_placeholder_adaptation_stays_sqlite_by_default() -> None:
    configure_database(db_path="/tmp/family-tree-test.db")
    assert _adapt_sql_placeholders("SELECT * FROM users WHERE id = ? AND created_at > ?") == (
        "SELECT * FROM users WHERE id = ? AND created_at > ?"
    )


def test_placeholder_adaptation_converts_for_postgres() -> None:
    configure_database(database_url="postgresql://family_tree:family_tree_dev@127.0.0.1:5433/family_tree")
    assert _adapt_sql_placeholders("SELECT * FROM users WHERE id = ? AND created_at > ?") == (
        "SELECT * FROM users WHERE id = %s AND created_at > %s"
    )
    configure_database(db_path="/tmp/family-tree-test.db")


def test_integrity_errors_include_sqlite() -> None:
    assert sqlite3.IntegrityError in INTEGRITY_ERRORS


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


@postgres_only
def test_postgres_end_to_end_graph_flow_with_membership(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = build_postgres_client(monkeypatch, tmp_path)
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


@postgres_only
def test_postgres_subgraph_timeline_and_migration_geojson(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = build_postgres_client(monkeypatch, tmp_path)
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


@postgres_only
def test_postgres_change_request_approval_updates_person(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = build_postgres_client(monkeypatch, tmp_path)
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


@postgres_only
def test_postgres_context_events_and_person_timeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = build_postgres_client(monkeypatch, tmp_path)
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
    assert body[1]["date"] == "1971-12-16"
    assert body[1]["kind"] == "context"


@postgres_only
def test_postgres_person_places_and_migration_geojson(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = build_postgres_client(monkeypatch, tmp_path)
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

    geojson = client.get(
        f"/circles/{circle_id}/persons/{person_id}/migration-geojson",
        headers={"X-User-Id": owner_id},
    )
    assert geojson.status_code == 200
    fc = geojson.json()
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 3


@postgres_only
def test_postgres_discussion_threads_messages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = build_postgres_client(monkeypatch, tmp_path)
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

    missing_thread = client.get(
        f"/circles/{circle_id}/threads",
        params={"entity_type": "person", "entity_id": person_id},
        headers={"X-User-Id": owner_id},
    )
    assert missing_thread.status_code == 200
    assert missing_thread.json() is None

    thread = client.post(
        f"/circles/{circle_id}/threads",
        json={"entity_type": "person", "entity_id": person_id},
        headers={"X-User-Id": owner_id},
    )
    assert thread.status_code == 200
    thread_id = thread.json()["id"]

    existing_thread = client.get(
        f"/circles/{circle_id}/threads",
        params={"entity_type": "person", "entity_id": person_id},
        headers={"X-User-Id": owner_id},
    )
    assert existing_thread.status_code == 200
    assert existing_thread.json()["id"] == thread_id

    msg = client.post(
        f"/circles/{circle_id}/threads/{thread_id}/messages",
        json={"content": "Oral history note"},
        headers={"X-User-Id": editor_id},
    )
    assert msg.status_code == 200

    listed = client.get(
        f"/circles/{circle_id}/threads/{thread_id}/messages",
        headers={"X-User-Id": owner_id},
    )
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["content"] == "Oral history note"


@postgres_only
def test_postgres_invitation_transfer_and_audit_flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = build_postgres_client(monkeypatch, tmp_path)
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


@postgres_only
def test_postgres_relationship_validation_update_delete_and_duplicates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = build_postgres_client(monkeypatch, tmp_path)
    owner_id = create_user(client, "Owner")
    editor_id = create_user(client, "Editor")
    viewer_id = create_user(client, "Viewer")

    circle = client.post("/circles", json={"name": "Relationship Family"}, headers={"X-User-Id": owner_id})
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

    invalid = client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": a, "to_person_id": b, "relationship_type": "mentor_of"},
        headers={"X-User-Id": owner_id},
    )
    assert invalid.status_code == 400

    rel_ab = client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": a, "to_person_id": b, "relationship_type": "parent_of"},
        headers={"X-User-Id": owner_id},
    )
    assert rel_ab.status_code == 200
    rel_ab_id = rel_ab.json()["id"]
    assert client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": b, "to_person_id": c, "relationship_type": "parent_of"},
        headers={"X-User-Id": owner_id},
    ).status_code == 200

    cycle = client.post(
        f"/circles/{circle_id}/relationships",
        json={"from_person_id": c, "to_person_id": a, "relationship_type": "parent_of"},
        headers={"X-User-Id": owner_id},
    )
    assert cycle.status_code == 400

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

    deleted = client.delete(
        f"/circles/{circle_id}/relationships/{rel_ab_id}",
        headers={"X-User-Id": editor_id},
    )
    assert deleted.status_code == 200

    first_duplicate_target = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Ravi Pai", "birth_date": "1970-01-01", "birth_place": "Mumbai"},
        headers={"X-User-Id": owner_id},
    )
    assert first_duplicate_target.status_code == 200
    hints = client.get(
        f"/circles/{circle_id}/persons/duplicate-hints",
        params={"full_name": "Ravi Pai", "birth_date": "1970-01-01", "birth_place": "Mumbai"},
        headers={"X-User-Id": owner_id},
    )
    assert hints.status_code == 200
    assert len(hints.json()) == 1
    blocked_duplicate = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Ravi Pai", "birth_date": "1970-01-01", "birth_place": "Mumbai"},
        headers={"X-User-Id": owner_id},
    )
    assert blocked_duplicate.status_code == 409


@postgres_only
def test_postgres_auth_media_and_person_revision(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = build_postgres_client(monkeypatch, tmp_path)
    owner_id = create_user(client, "Owner")
    editor_id = create_user(client, "Editor")
    viewer_id = create_user(client, "Viewer")

    owner_headers = auth_headers_for(client, owner_id)
    circle = client.post("/circles", json={"name": "Profile Media Family"}, headers=owner_headers)
    assert circle.status_code == 200
    circle_id = circle.json()["id"]

    assert client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": editor_id, "role": "editor"},
        headers=owner_headers,
    ).status_code == 200
    assert client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": viewer_id, "role": "viewer"},
        headers=owner_headers,
    ).status_code == 200

    person = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Meera", "birth_date": "1980-01-01"},
        headers=owner_headers,
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
    assert updated.json()["occupation"] == "Engineer"

    revisions = client.get(
        f"/circles/{circle_id}/persons/{person_id}/revisions",
        headers=owner_headers,
    )
    assert revisions.status_code == 200
    rev_rows = revisions.json()
    assert len(rev_rows) >= 2
    assert rev_rows[0]["reason"] == "profile_edit"

    upload = client.post(
        f"/circles/{circle_id}/persons/{person_id}/media",
        files={"file": ("note.txt", b"hello family media", "text/plain")},
        headers={"X-User-Id": editor_id},
    )
    assert upload.status_code == 200
    asset_id = upload.json()["id"]

    listed = client.get(
        f"/circles/{circle_id}/persons/{person_id}/media",
        headers=owner_headers,
    )
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == asset_id

    previews = client.get(f"/circles/{circle_id}/media-previews", headers=owner_headers)
    assert previews.status_code == 200
    assert previews.json()[0]["person_id"] == person_id
    assert previews.json()[0]["asset_id"] == asset_id

    downloaded = client.get(
        f"/circles/{circle_id}/media/{asset_id}/download",
        headers=owner_headers,
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"hello family media"


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
    assert asset["stored_filename"] == f"{asset_id}.txt"
    assert "/" not in asset["stored_filename"]

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
    assert 'filename="note.txt"' in downloaded.headers["content-disposition"]

    downloaded_via_query = client.get(
        f"/circles/{circle_id}/media/{asset_id}/download",
        params={"user_id": owner_id},
    )
    assert downloaded_via_query.status_code == 200
    assert downloaded_via_query.content == b"hello family media"


def test_media_upload_uses_server_owned_paths_and_rejects_spoofed_formats(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    owner_headers = auth_headers_for(client, owner_id)
    circle_id = client.post(
        "/circles",
        json={"name": "Safe Media Family"},
        headers=owner_headers,
    ).json()["id"]
    person_id = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Safe Media Person"},
        headers=owner_headers,
    ).json()["id"]

    uploaded = client.post(
        f"/circles/{circle_id}/persons/{person_id}/media",
        files={"file": ("..\\..\\family portrait.exe", JPEG_BYTES, "application/octet-stream")},
        headers=owner_headers,
    )
    assert uploaded.status_code == 200
    asset = uploaded.json()
    assert asset["original_filename"] == "family portrait.jpg"
    assert asset["stored_filename"] == f"{asset['id']}.jpg"
    assert asset["mime_type"] == "image/jpeg"
    stored_path = tmp_path / "media" / circle_id / person_id / asset["stored_filename"]
    assert stored_path.read_bytes() == JPEG_BYTES
    assert not (tmp_path / "media" / "family portrait.exe").exists()

    mismatched = client.post(
        f"/circles/{circle_id}/persons/{person_id}/media",
        files={"file": ("fake.jpg", b"%PDF-1.7 fake", "image/jpeg")},
        headers=owner_headers,
    )
    active_content = client.post(
        f"/circles/{circle_id}/persons/{person_id}/media",
        files={"file": ("page.svg", b"<svg><script>alert(1)</script></svg>", "image/svg+xml")},
        headers=owner_headers,
    )
    empty = client.post(
        f"/circles/{circle_id}/persons/{person_id}/media",
        files={"file": ("empty.txt", b"", "text/plain")},
        headers=owner_headers,
    )
    assert mismatched.status_code == 415
    assert active_content.status_code == 415
    assert empty.status_code == 400

    with main.get_conn() as conn:
        count = main.fetch_one(conn, "SELECT COUNT(*) AS count FROM media_assets WHERE person_id = ?", (person_id,))
    assert count["count"] == 1
    files = [path for path in (tmp_path / "media").rglob("*") if path.is_file()]
    assert files == [stored_path]
    assert not list((tmp_path / "media").rglob("*.uploading"))


def test_media_upload_limit_cleans_preflight_and_streaming_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    circle_id = client.post(
        "/circles",
        json={"name": "Bounded Media Family"},
        headers={"X-User-Id": owner_id},
    ).json()["id"]
    person_id = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Bounded Media Person"},
        headers={"X-User-Id": owner_id},
    ).json()["id"]
    monkeypatch.setattr(main, "MAX_MEDIA_UPLOAD_BYTES", 8)

    preflight = client.post(
        f"/circles/{circle_id}/persons/{person_id}/media",
        files={"file": ("large.txt", b"nine-byte", "text/plain")},
        headers={"X-User-Id": owner_id},
    )
    assert preflight.status_code == 413

    streaming_file = main.UploadFile(
        file=BytesIO(b"nine-byte"),
        size=None,
        filename="streamed.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    with pytest.raises(main.HTTPException) as streaming_error:
        asyncio.run(
            main.upload_person_media(
                circle_id,
                person_id,
                streaming_file,
                x_user_id=owner_id,
                authorization=None,
            )
        )
    assert streaming_error.value.status_code == 413
    assert streaming_file.file.closed

    with main.get_conn() as conn:
        count = main.fetch_one(conn, "SELECT COUNT(*) AS count FROM media_assets WHERE person_id = ?", (person_id,))
    assert count["count"] == 0
    assert not [path for path in (tmp_path / "media").rglob("*") if path.is_file()]


def test_media_stream_writes_run_off_the_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    circle_id = client.post(
        "/circles",
        json={"name": "Responsive Upload Family"},
        headers={"X-User-Id": owner_id},
    ).json()["id"]
    person_id = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Responsive Upload Person"},
        headers={"X-User-Id": owner_id},
    ).json()["id"]
    real_run_in_threadpool = main.run_in_threadpool
    write_sizes: list[int] = []

    async def record_threaded_write(function: object, *args: object, **kwargs: object) -> object:
        if args and isinstance(args[0], bytes):
            write_sizes.append(len(args[0]))
        return await real_run_in_threadpool(function, *args, **kwargs)

    monkeypatch.setattr(main, "run_in_threadpool", record_threaded_write)
    upload = main.UploadFile(
        file=BytesIO(b"responsive family note"),
        size=None,
        filename="note.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    result = asyncio.run(
        main.upload_person_media(
            circle_id,
            person_id,
            upload,
            x_user_id=owner_id,
            authorization=None,
        )
    )
    assert result.bytes == len(b"responsive family note")
    assert write_sizes == [len(b"responsive family note")]


def test_media_upload_removes_final_file_when_database_insert_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    circle_id = client.post(
        "/circles",
        json={"name": "Cleanup Media Family"},
        headers={"X-User-Id": owner_id},
    ).json()["id"]
    person_id = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Cleanup Media Person"},
        headers={"X-User-Id": owner_id},
    ).json()["id"]
    real_execute = main.execute

    def fail_media_insert(conn: object, sql: str, params: object = None) -> object:
        if "INSERT INTO media_assets" in sql:
            raise RuntimeError("simulated media metadata failure")
        return real_execute(conn, sql, params)

    monkeypatch.setattr(main, "execute", fail_media_insert)
    response = client.post(
        f"/circles/{circle_id}/persons/{person_id}/media",
        files={"file": ("portrait.jpg", JPEG_BYTES, "image/jpeg")},
        headers={"X-User-Id": owner_id, "Origin": "http://localhost:8000"},
    )
    assert response.status_code == 500
    assert response.json() == {
        "detail": "Unexpected server error",
        "request_id": response.headers["x-request-id"],
    }
    assert response.headers["access-control-allow-origin"] == "http://localhost:8000"
    assert "simulated media metadata failure" not in response.text
    assert not [path for path in (tmp_path / "media").rglob("*") if path.is_file()]


def test_media_download_rejects_legacy_rows_outside_person_directory(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    owner_headers = auth_headers_for(client, owner_id)
    circle_id = client.post(
        "/circles",
        json={"name": "Legacy Path Family"},
        headers=owner_headers,
    ).json()["id"]
    person_id = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Legacy Path Person"},
        headers=owner_headers,
    ).json()["id"]
    outside_file = tmp_path / "media" / "outside-secret.txt"
    outside_file.parent.mkdir(parents=True, exist_ok=True)
    outside_file.write_text("must stay private")
    asset_id = "legacy-traversal-asset"
    with main.get_conn() as conn:
        execute(
            conn,
            """
            INSERT INTO media_assets (
              id, circle_id, person_id, uploader_user_id, original_filename, stored_filename, mime_type, bytes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                circle_id,
                person_id,
                owner_id,
                "outside-secret.txt",
                "../../outside-secret.txt",
                "text/plain",
                outside_file.stat().st_size,
                main.utc_now(),
            ),
        )

    response = client.get(
        f"/circles/{circle_id}/media/{asset_id}/download",
        headers=owner_headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Media file path is invalid"


@pytest.mark.parametrize(
    ("sample", "claimed", "expected"),
    [
        (JPEG_BYTES, "image/jpeg", "image/jpeg"),
        (PNG_BYTES, "application/octet-stream", "image/png"),
        (b"GIF89a-data", "image/gif", "image/gif"),
        (b"RIFF1234WEBPdata", "image/webp", "image/webp"),
        (b"II*\x00tiff-data", "image/tiff", "image/tiff"),
        (b"\x00\x00\x00\x18ftypheicdata", "image/heif", "image/heic"),
        (b"%PDF-1.7 data", "application/pdf", "application/pdf"),
        (b"family note", "text/plain", "text/plain"),
        (b"ID3audio-data", "audio/mpeg", "audio/mpeg"),
        (b"RIFF1234WAVEdata", "audio/x-wav", "audio/wav"),
        (b"\x00\x00\x00\x18ftypisomdata", "video/mp4", "video/mp4"),
        (b"<html>unsafe</html>", "text/html", None),
        (b"%PDF-1.7 data", "image/jpeg", None),
    ],
)
def test_media_type_sniffing(sample: bytes, claimed: str, expected: Optional[str]) -> None:
    assert main._sniff_media_type(sample, claimed) == expected


def test_circle_media_previews_return_latest_asset_per_person_and_check_membership(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    outsider_id = create_user(client, "Outsider")
    owner_headers = auth_headers_for(client, owner_id)
    outsider_headers = auth_headers_for(client, outsider_id)

    circle = client.post("/circles", json={"name": "Preview Family"}, headers=owner_headers)
    assert circle.status_code == 200
    circle_id = circle.json()["id"]

    first_person = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "First Person"},
        headers=owner_headers,
    ).json()
    second_person = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Second Person"},
        headers=owner_headers,
    ).json()
    client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "No Media Person"},
        headers=owner_headers,
    ).raise_for_status()

    first_upload = client.post(
        f"/circles/{circle_id}/persons/{first_person['id']}/media",
        files={"file": ("first.jpg", JPEG_BYTES + b"-first", "image/jpeg")},
        headers=owner_headers,
    )
    latest_upload = client.post(
        f"/circles/{circle_id}/persons/{first_person['id']}/media",
        files={"file": ("latest.png", PNG_BYTES + b"-latest", "image/png")},
        headers=owner_headers,
    )
    newer_document = client.post(
        f"/circles/{circle_id}/persons/{first_person['id']}/media",
        files={"file": ("family-note.txt", b"newer document", "text/plain")},
        headers=owner_headers,
    )
    second_upload = client.post(
        f"/circles/{circle_id}/persons/{second_person['id']}/media",
        files={"file": ("portrait.jpg", JPEG_BYTES + b"-second", "image/jpeg")},
        headers=owner_headers,
    )
    assert first_upload.status_code == 200
    assert latest_upload.status_code == 200
    assert newer_document.status_code == 200
    assert second_upload.status_code == 200

    response = client.get(f"/circles/{circle_id}/media-previews", headers=owner_headers)
    assert response.status_code == 200
    preview_by_person = {row["person_id"]: row for row in response.json()}
    assert set(preview_by_person) == {first_person["id"], second_person["id"]}
    assert preview_by_person[first_person["id"]]["asset_id"] == latest_upload.json()["id"]
    assert preview_by_person[first_person["id"]]["mime_type"] == "image/png"
    assert preview_by_person[second_person["id"]]["asset_id"] == second_upload.json()["id"]
    assert preview_by_person[second_person["id"]]["mime_type"] == "image/jpeg"

    unauthorized = client.get(f"/circles/{circle_id}/media-previews")
    forbidden = client.get(f"/circles/{circle_id}/media-previews", headers=outsider_headers)
    assert unauthorized.status_code == 401
    assert forbidden.status_code == 403

    with sqlite3.connect(tmp_path / "test.db") as conn:
        indexes = {row[1] for row in conn.execute("PRAGMA index_list('media_assets')")}
    assert "idx_media_assets_circle_person_created" in indexes


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
        execute(
            conn,
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


def test_medical_notes_are_redacted_for_viewers_across_response_paths(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Privacy Owner")
    editor_id = create_user(client, "Privacy Editor")
    viewer_id = create_user(client, "Privacy Viewer")
    owner_headers = {"X-User-Id": owner_id}
    editor_headers = {"X-User-Id": editor_id}
    viewer_headers = {"X-User-Id": viewer_id}

    circle = client.post("/circles", json={"name": "Private Family"}, headers=owner_headers)
    assert circle.status_code == 200
    circle_id = circle.json()["id"]
    for user_id, role in ((editor_id, "editor"), (viewer_id, "viewer")):
        member = client.post(
            f"/circles/{circle_id}/members",
            json={"user_id": user_id, "role": role},
            headers=owner_headers,
        )
        assert member.status_code == 200

    original_note = "Private diagnosis shared with caregivers"
    created = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Asha", "medical_notes": original_note},
        headers=owner_headers,
    )
    assert created.status_code == 200
    assert created.json()["medical_notes"] == original_note
    person_id = created.json()["id"]

    owner_person = client.get(f"/circles/{circle_id}/persons", headers=owner_headers)
    editor_person = client.get(f"/circles/{circle_id}/persons", headers=editor_headers)
    viewer_person = client.get(f"/circles/{circle_id}/persons", headers=viewer_headers)
    assert owner_person.json()[0]["medical_notes"] == original_note
    assert editor_person.json()[0]["medical_notes"] == original_note
    assert viewer_person.json()[0]["medical_notes"] is None

    viewer_graph = client.get(
        f"/circles/{circle_id}/graph/subgraph",
        params={"root_person_id": person_id, "direction": "ancestors", "depth": 1},
        headers=viewer_headers,
    )
    assert viewer_graph.status_code == 200
    assert viewer_graph.json()["persons"][0]["medical_notes"] is None

    event = client.post(
        f"/circles/{circle_id}/context-events",
        json={"date": "2000-01-01", "title": "Family milestone", "event_type": "family"},
        headers=owner_headers,
    )
    assert event.status_code == 200
    event_id = event.json()["id"]
    linked = client.post(
        f"/circles/{circle_id}/persons/{person_id}/context-links",
        json={"context_event_id": event_id},
        headers=owner_headers,
    )
    assert linked.status_code == 200
    viewer_event_people = client.get(
        f"/circles/{circle_id}/context-events/{event_id}/persons",
        headers=viewer_headers,
    )
    assert viewer_event_people.status_code == 200
    assert viewer_event_people.json()[0]["medical_notes"] is None

    viewer_revisions = client.get(
        f"/circles/{circle_id}/persons/{person_id}/revisions",
        headers=viewer_headers,
    )
    editor_revisions = client.get(
        f"/circles/{circle_id}/persons/{person_id}/revisions",
        headers=editor_headers,
    )
    assert json.loads(viewer_revisions.json()[0]["snapshot_json"])["medical_notes"] is None
    assert json.loads(editor_revisions.json()[0]["snapshot_json"])["medical_notes"] == original_note

    updated_note = "Updated private diagnosis"
    updated = client.patch(
        f"/circles/{circle_id}/persons/{person_id}",
        json={"medical_notes": updated_note, "revision_reason": "caregiver_update"},
        headers=editor_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["medical_notes"] == updated_note

    viewer_audit = client.get(f"/circles/{circle_id}/audit-logs", headers=viewer_headers)
    editor_audit = client.get(f"/circles/{circle_id}/audit-logs", headers=editor_headers)
    viewer_update = next(row for row in viewer_audit.json() if row["action"] == "person.updated")
    editor_update = next(row for row in editor_audit.json() if row["action"] == "person.updated")
    expected_audit_payload = {
        "changed_fields": ["medical_notes"],
        "sensitive_fields_changed": ["medical_notes"],
    }
    assert json.loads(viewer_update["payload_json"]) == expected_audit_payload
    assert json.loads(editor_update["payload_json"]) == expected_audit_payload
    assert updated_note not in json.dumps(editor_audit.json())

    proposed_note = "Viewer-proposed confidential correction"
    viewer_proposal = client.post(
        f"/circles/{circle_id}/change-requests",
        json={
            "entity_type": "person",
            "entity_id": person_id,
            "proposed_patch_json": {"medical_notes": proposed_note},
        },
        headers=viewer_headers,
    )
    assert viewer_proposal.status_code == 403

    owner_proposal = client.post(
        f"/circles/{circle_id}/change-requests",
        json={
            "entity_type": "person",
            "entity_id": person_id,
            "proposed_patch_json": {"medical_notes": proposed_note},
        },
        headers=owner_headers,
    )
    assert owner_proposal.status_code == 200
    assert json.loads(owner_proposal.json()["proposed_patch_json"])["medical_notes"] == proposed_note
    viewer_requests = client.get(f"/circles/{circle_id}/change-requests", headers=viewer_headers)
    assert json.loads(viewer_requests.json()[0]["proposed_patch_json"])["medical_notes"] is None
    editor_requests = client.get(f"/circles/{circle_id}/change-requests", headers=editor_headers)
    assert json.loads(editor_requests.json()[0]["proposed_patch_json"])["medical_notes"] == proposed_note

    with main.get_conn() as conn:
        stored = main.fetch_one(conn, "SELECT medical_notes FROM persons WHERE id = ?", (person_id,))
        stored_revision = main.fetch_one(
            conn,
            "SELECT snapshot_json FROM entity_revisions WHERE entity_id = ? ORDER BY revision_no DESC LIMIT 1",
            (person_id,),
        )
    assert stored["medical_notes"] == updated_note
    assert json.loads(stored_revision["snapshot_json"])["medical_notes"] == updated_note


def test_viewer_redaction_of_malformed_legacy_json_fails_closed() -> None:
    assert redact_sensitive_json("not-json", "viewer", fallback="{}") == "{}"
    assert redact_sensitive_json("not-json", "editor", fallback="{}") == "not-json"


def test_viewer_person_query_does_not_load_sensitive_column(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Projection Owner")
    viewer_id = create_user(client, "Projection Viewer")
    circle_id = client.post(
        "/circles",
        json={"name": "Projection Family"},
        headers={"X-User-Id": owner_id},
    ).json()["id"]
    assert client.post(
        f"/circles/{circle_id}/members",
        json={"user_id": viewer_id, "role": "viewer"},
        headers={"X-User-Id": owner_id},
    ).status_code == 200
    assert client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Projection Person", "medical_notes": "database-only secret"},
        headers={"X-User-Id": owner_id},
    ).status_code == 200

    original_fetch_all = main.fetch_all
    captured_person_queries: list[str] = []

    def capture_fetch_all(conn: object, sql: str, params: object = None) -> list[object]:
        if "FROM persons" in sql:
            captured_person_queries.append(sql)
        return original_fetch_all(conn, sql, params)

    monkeypatch.setattr(main, "fetch_all", capture_fetch_all)
    viewer_response = client.get(
        f"/circles/{circle_id}/persons",
        headers={"X-User-Id": viewer_id},
    )
    assert viewer_response.status_code == 200
    assert viewer_response.json()[0]["medical_notes"] is None
    assert len(captured_person_queries) == 1
    assert "NULL AS medical_notes" in captured_person_queries[0]
    assert "medical_notes AS medical_notes" not in captured_person_queries[0]

    assert "NULL AS medical_notes" not in person_response_select_clause("owner")
    assert "medical_notes AS medical_notes" in person_response_select_clause("owner")


def test_auth_login_and_bearer_access(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")

    login = client.post("/auth/login", json={"user_id": owner_id})
    assert login.status_code == 200
    token = login.json()["access_token"]
    with main.get_conn() as conn:
        stored_session = main.fetch_one(conn, "SELECT token FROM auth_sessions WHERE user_id = ?", (owner_id,))
    assert stored_session["token"] == main.digest_token(token)
    assert stored_session["token"] != token
    assert client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {stored_session['token']}"},
    ).status_code == 401

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


def test_startup_migrates_plaintext_sessions_without_signing_out_clients(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Legacy Session Owner")
    circle_id = client.post(
        "/circles",
        json={"name": "Legacy Session Family"},
        headers={"X-User-Id": owner_id},
    ).json()["id"]
    legacy_token = "legacy-plaintext-session-token"
    with main.get_conn() as conn:
        execute(
            conn,
            """
            INSERT INTO auth_sessions (token, user_id, created_at, expires_at, revoked_at)
            VALUES (?, ?, ?, ?, NULL)
            """,
            (legacy_token, owner_id, main.utc_now(), "2999-01-01T00:00:00+00:00"),
        )
        execute(
            conn,
            """
            INSERT INTO circle_access_tickets (
              ticket_hash, session_token, circle_id, scope, created_at, expires_at, consumed_at
            ) VALUES (?, ?, ?, 'media', ?, ?, NULL)
            """,
            (
                main.digest_token("legacy-circle-ticket"),
                legacy_token,
                circle_id,
                main.utc_now(),
                "2999-01-01T00:00:00+00:00",
            ),
        )

    main.init_db(main.MEDIA_DIR)
    legacy_headers = {"Authorization": f"Bearer {legacy_token}"}
    restored = client.get("/auth/me", headers=legacy_headers)
    assert restored.status_code == 200
    assert restored.json()["id"] == owner_id
    with main.get_conn() as conn:
        sessions = main.fetch_all(conn, "SELECT token FROM auth_sessions")
        ticket_count = main.fetch_one(conn, "SELECT COUNT(*) AS count FROM circle_access_tickets")
    assert [row["token"] for row in sessions] == [main.digest_token(legacy_token)]
    assert ticket_count["count"] == 0

    reissued = client.post(
        f"/circles/{circle_id}/access-tickets",
        json={"scope": "media"},
        headers=legacy_headers,
    )
    assert reissued.status_code == 200
    main.init_db(main.MEDIA_DIR)
    with main.get_conn() as conn:
        session_tokens = main.fetch_all(conn, "SELECT token FROM auth_sessions")
        ticket_rows = main.fetch_all(conn, "SELECT session_token FROM circle_access_tickets")
    assert [row["token"] for row in session_tokens] == [main.digest_token(legacy_token)]
    assert [row["session_token"] for row in ticket_rows] == [main.digest_token(legacy_token)]
    assert client.get("/auth/me", headers=legacy_headers).status_code == 200


def test_auth_me_rejects_unknown_expired_and_revoked_tokens(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")

    unknown = client.get("/auth/me", headers={"Authorization": "Bearer unknown-token"})
    assert unknown.status_code == 401

    expired_login = client.post("/auth/login", json={"user_id": owner_id}).json()
    with main.get_conn() as conn:
        execute(
            conn,
            "UPDATE auth_sessions SET expires_at = ? WHERE token = ?",
            ("2000-01-01T00:00:00+00:00", main.digest_token(expired_login["access_token"])),
        )
    expired = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {expired_login['access_token']}"},
    )
    assert expired.status_code == 401

    revoked_login = client.post("/auth/login", json={"user_id": owner_id}).json()
    with main.get_conn() as conn:
        execute(
            conn,
            "UPDATE auth_sessions SET revoked_at = ? WHERE token = ?",
            (main.utc_now(), main.digest_token(revoked_login["access_token"])),
        )
    revoked = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {revoked_login['access_token']}"},
    )
    assert revoked.status_code == 401


def test_logout_revokes_only_the_current_session_and_is_idempotent(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    first_token = client.post("/auth/login", json={"user_id": owner_id}).json()["access_token"]
    second_token = client.post("/auth/login", json={"user_id": owner_id}).json()["access_token"]

    logged_out = client.post("/auth/logout", headers={"Authorization": f"Bearer {first_token}"})
    assert logged_out.status_code == 204
    assert logged_out.content == b""

    first_session = client.get("/auth/me", headers={"Authorization": f"Bearer {first_token}"})
    second_session = client.get("/auth/me", headers={"Authorization": f"Bearer {second_token}"})
    assert first_session.status_code == 401
    assert second_session.status_code == 200

    repeated = client.post("/auth/logout", headers={"Authorization": f"Bearer {first_token}"})
    assert repeated.status_code == 204

    with main.get_conn() as conn:
        row = main.fetch_one(
            conn,
            "SELECT revoked_at FROM auth_sessions WHERE token = ?",
            (main.digest_token(first_token),),
        )
    assert row["revoked_at"] is not None

    missing = client.post("/auth/logout")
    malformed = client.post("/auth/logout", headers={"Authorization": "Token malformed"})
    unknown = client.post("/auth/logout", headers={"Authorization": "Bearer unknown-token"})
    assert missing.status_code == 401
    assert malformed.status_code == 401
    assert unknown.status_code == 401


def test_circle_access_tickets_are_bearer_only_scoped_and_hashed(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    outsider_id = create_user(client, "Outsider")
    owner_headers = auth_headers_for(client, owner_id)
    outsider_headers = auth_headers_for(client, outsider_id)
    circle_id = client.post(
        "/circles",
        json={"name": "Ticket Family"},
        headers=owner_headers,
    ).json()["id"]

    missing = client.post(f"/circles/{circle_id}/access-tickets", json={"scope": "media"})
    legacy_only = client.post(
        f"/circles/{circle_id}/access-tickets",
        json={"scope": "media"},
        headers={"X-User-Id": owner_id},
    )
    outsider = client.post(
        f"/circles/{circle_id}/access-tickets",
        json={"scope": "media"},
        headers=outsider_headers,
    )
    assert missing.status_code == 401
    assert legacy_only.status_code == 401
    assert outsider.status_code == 403

    media = client.post(
        f"/circles/{circle_id}/access-tickets",
        json={"scope": "media"},
        headers=owner_headers,
    )
    websocket = client.post(
        f"/circles/{circle_id}/access-tickets",
        json={"scope": "websocket"},
        headers=owner_headers,
    )
    assert media.status_code == 200
    assert websocket.status_code == 200
    assert media.headers["cache-control"] == "no-store"
    assert media.json()["scope"] == "media"
    assert websocket.json()["scope"] == "websocket"
    assert media.json()["ticket"] != websocket.json()["ticket"]

    with main.get_conn() as conn:
        rows = main.fetch_all(
            conn,
            "SELECT ticket_hash, session_token, scope FROM circle_access_tickets WHERE circle_id = ? ORDER BY scope",
            (circle_id,),
        )
        indexes = main.fetch_all(conn, "PRAGMA index_list('circle_access_tickets')")
    stored_hashes = {row["ticket_hash"] for row in rows}
    assert {row["scope"] for row in rows} == {"media", "websocket"}
    assert all(len(ticket_hash) == 64 for ticket_hash in stored_hashes)
    assert {row["session_token"] for row in rows} == {
        main.digest_token(owner_headers["Authorization"].split(" ", 1)[1])
    }
    assert media.json()["ticket"] not in stored_hashes
    assert websocket.json()["ticket"] not in stored_hashes
    assert "idx_circle_access_tickets_expires_at" in {row["name"] for row in indexes}


def test_media_ticket_enforces_scope_expiry_and_parent_session_revocation(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    owner_headers = auth_headers_for(client, owner_id)
    session_token = owner_headers["Authorization"].split(" ", 1)[1]
    circle_id = client.post(
        "/circles",
        json={"name": "Media Ticket Family"},
        headers=owner_headers,
    ).json()["id"]
    person_id = client.post(
        f"/circles/{circle_id}/persons",
        json={"full_name": "Portrait Person"},
        headers=owner_headers,
    ).json()["id"]
    asset_id = client.post(
        f"/circles/{circle_id}/persons/{person_id}/media",
        files={"file": ("portrait.jpg", JPEG_BYTES + b"-portrait", "image/jpeg")},
        headers=owner_headers,
    ).json()["id"]

    media_access = client.post(
        f"/circles/{circle_id}/access-tickets",
        json={"scope": "media"},
        headers=owner_headers,
    ).json()
    downloaded = client.get(
        f"/circles/{circle_id}/media/{asset_id}/download",
        params={"ticket": media_access["ticket"]},
    )
    assert downloaded.status_code == 200
    assert downloaded.content == JPEG_BYTES + b"-portrait"
    assert downloaded.headers["cache-control"] == "private, max-age=300"
    assert downloaded.headers["referrer-policy"] == "no-referrer"
    assert downloaded.headers["x-content-type-options"] == "nosniff"

    websocket_access = client.post(
        f"/circles/{circle_id}/access-tickets",
        json={"scope": "websocket"},
        headers=owner_headers,
    ).json()
    wrong_scope = client.get(
        f"/circles/{circle_id}/media/{asset_id}/download",
        params={"ticket": websocket_access["ticket"]},
    )
    wrong_circle = client.get(
        f"/circles/not-this-circle/media/{asset_id}/download",
        params={"ticket": media_access["ticket"]},
    )
    raw_session_query = client.get(
        f"/circles/{circle_id}/media/{asset_id}/download",
        params={"token": session_token},
    )
    assert wrong_scope.status_code == 401
    assert wrong_circle.status_code == 401
    assert raw_session_query.status_code == 401

    with main.get_conn() as conn:
        execute(
            conn,
            "UPDATE circle_access_tickets SET expires_at = ? WHERE ticket_hash = ?",
            ("2000-01-01T00:00:00+00:00", hashlib.sha256(media_access["ticket"].encode()).hexdigest()),
        )
    expired = client.get(
        f"/circles/{circle_id}/media/{asset_id}/download",
        params={"ticket": media_access["ticket"]},
    )
    assert expired.status_code == 401

    replacement = client.post(
        f"/circles/{circle_id}/access-tickets",
        json={"scope": "media"},
        headers=owner_headers,
    ).json()
    assert client.post("/auth/logout", headers=owner_headers).status_code == 204
    revoked_parent = client.get(
        f"/circles/{circle_id}/media/{asset_id}/download",
        params={"ticket": replacement["ticket"]},
    )
    assert revoked_parent.status_code == 401


def test_websocket_ticket_is_circle_scoped_one_time_and_session_bound(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    owner_headers = auth_headers_for(client, owner_id)
    session_token = owner_headers["Authorization"].split(" ", 1)[1]
    circle_id = client.post(
        "/circles",
        json={"name": "Realtime Ticket Family"},
        headers=owner_headers,
    ).json()["id"]

    websocket_ticket = client.post(
        f"/circles/{circle_id}/access-tickets",
        json={"scope": "websocket"},
        headers=owner_headers,
    ).json()["ticket"]
    subprotocols = ["family-tree.v1", f"family-tree-ticket.{websocket_ticket}"]
    with client.websocket_connect(f"/ws/circles/{circle_id}", subprotocols=subprotocols) as ws:
        assert ws.accepted_subprotocol == "family-tree.v1"
        joined = ws.receive_json()
        assert joined["type"] == "presence.updated"
        assert joined["state"] == "joined"
        assert joined["user_id"] == owner_id

    with pytest.raises((WebSocketDisconnect, WebSocketDenialResponse)):
        with client.websocket_connect(f"/ws/circles/{circle_id}", subprotocols=subprotocols) as replay:
            replay.receive_json()

    media_ticket = client.post(
        f"/circles/{circle_id}/access-tickets",
        json={"scope": "media"},
        headers=owner_headers,
    ).json()["ticket"]
    with pytest.raises((WebSocketDisconnect, WebSocketDenialResponse)):
        with client.websocket_connect(
            f"/ws/circles/{circle_id}",
            subprotocols=["family-tree.v1", f"family-tree-ticket.{media_ticket}"],
        ) as wrong_scope:
            wrong_scope.receive_json()

    with pytest.raises((WebSocketDisconnect, WebSocketDenialResponse)):
        with client.websocket_connect(f"/ws/circles/{circle_id}?token={session_token}") as raw_session:
            raw_session.receive_json()

    header_only_ticket = client.post(
        f"/circles/{circle_id}/access-tickets",
        json={"scope": "websocket"},
        headers=owner_headers,
    ).json()["ticket"]
    with pytest.raises((WebSocketDisconnect, WebSocketDenialResponse)):
        with client.websocket_connect(f"/ws/circles/{circle_id}?ticket={header_only_ticket}") as ticket_in_url:
            ticket_in_url.receive_json()
    with client.websocket_connect(
        f"/ws/circles/{circle_id}",
        subprotocols=["family-tree.v1", f"family-tree-ticket.{header_only_ticket}"],
    ) as header_ticket_ws:
        assert header_ticket_ws.receive_json()["state"] == "joined"

    revoked_ticket = client.post(
        f"/circles/{circle_id}/access-tickets",
        json={"scope": "websocket"},
        headers=owner_headers,
    ).json()["ticket"]
    assert client.post("/auth/logout", headers=owner_headers).status_code == 204
    with pytest.raises((WebSocketDisconnect, WebSocketDenialResponse)):
        with client.websocket_connect(
            f"/ws/circles/{circle_id}",
            subprotocols=["family-tree.v1", f"family-tree-ticket.{revoked_ticket}"],
        ) as revoked:
            revoked.receive_json()


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


def test_discussion_lookup_is_read_only_and_thread_targets_stay_inside_circle(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    owner_id = create_user(client, "Owner")
    outsider_id = create_user(client, "Outsider")
    owner_headers = auth_headers_for(client, owner_id)
    outsider_headers = auth_headers_for(client, outsider_id)

    first_circle = client.post("/circles", json={"name": "First Circle"}, headers=owner_headers).json()
    second_circle = client.post("/circles", json={"name": "Second Circle"}, headers=owner_headers).json()
    first_person = client.post(
        f"/circles/{first_circle['id']}/persons",
        json={"full_name": "First Person"},
        headers=owner_headers,
    ).json()
    second_person = client.post(
        f"/circles/{second_circle['id']}/persons",
        json={"full_name": "Second Person"},
        headers=owner_headers,
    ).json()

    lookup = client.get(
        f"/circles/{first_circle['id']}/threads",
        params={"entity_type": "person", "entity_id": first_person["id"]},
        headers=owner_headers,
    )
    assert lookup.status_code == 200
    assert lookup.json() is None
    with sqlite3.connect(tmp_path / "test.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM discussion_threads").fetchone()[0] == 0

    forbidden = client.get(
        f"/circles/{first_circle['id']}/threads",
        params={"entity_type": "person", "entity_id": first_person["id"]},
        headers=outsider_headers,
    )
    assert forbidden.status_code == 403

    cross_circle = client.post(
        f"/circles/{first_circle['id']}/threads",
        json={"entity_type": "person", "entity_id": second_person["id"]},
        headers=owner_headers,
    )
    missing_entity = client.post(
        f"/circles/{first_circle['id']}/threads",
        json={"entity_type": "person", "entity_id": "missing-person"},
        headers=owner_headers,
    )
    assert cross_circle.status_code == 404
    assert missing_entity.status_code == 404

    created = client.post(
        f"/circles/{first_circle['id']}/threads",
        json={"entity_type": "person", "entity_id": first_person["id"]},
        headers=owner_headers,
    )
    assert created.status_code == 200
    thread_id = created.json()["id"]

    found = client.get(
        f"/circles/{first_circle['id']}/threads",
        params={"entity_type": "person", "entity_id": first_person["id"]},
        headers=owner_headers,
    )
    repeated = client.post(
        f"/circles/{first_circle['id']}/threads",
        json={"entity_type": "person", "entity_id": first_person["id"]},
        headers=owner_headers,
    )
    assert found.status_code == 200
    assert found.json()["id"] == thread_id
    assert repeated.status_code == 200
    assert repeated.json()["id"] == thread_id
    with sqlite3.connect(tmp_path / "test.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM discussion_threads").fetchone()[0] == 1


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
