from __future__ import annotations

import json
from typing import Any, Optional

from app.api.authorization import role_allows


SENSITIVE_PERSON_FIELDS = frozenset({"medical_notes"})
PERSON_RESPONSE_FIELDS = (
    "id",
    "circle_id",
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
    "created_at",
    "updated_at",
)


def can_read_sensitive_person_fields(role: str) -> bool:
    return role_allows(role, "view_medical_notes")


def contains_sensitive_person_fields(value: Any) -> bool:
    """Check nested proposals too, so a viewer cannot hide a protected field."""
    if isinstance(value, dict):
        return bool(SENSITIVE_PERSON_FIELDS.intersection(value)) or any(
            contains_sensitive_person_fields(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(contains_sensitive_person_fields(item) for item in value)
    return False


def person_response_select_clause(role: str, table_alias: Optional[str] = None) -> str:
    """Build a constant-shape person projection without loading forbidden fields."""
    if table_alias not in {None, "p"}:
        raise ValueError("Unsupported person table alias")
    prefix = f"{table_alias}." if table_alias else ""
    columns = []
    for field in PERSON_RESPONSE_FIELDS:
        if field in SENSITIVE_PERSON_FIELDS and not can_read_sensitive_person_fields(role):
            columns.append(f"NULL AS {field}")
        else:
            columns.append(f"{prefix}{field} AS {field}")
    return ", ".join(columns)


def redact_sensitive_value(value: Any) -> Any:
    """Return a JSON-compatible copy with sensitive person fields replaced by null."""
    if isinstance(value, dict):
        return {
            key: None if key in SENSITIVE_PERSON_FIELDS else redact_sensitive_value(nested_value)
            for key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_value(item) for item in value]
    return value


def redact_sensitive_json(raw_json: Optional[str], role: str, *, fallback: Optional[str]) -> Optional[str]:
    """Sanitize stored JSON for a role, failing closed on malformed viewer data."""
    if raw_json is None or can_read_sensitive_person_fields(role):
        return raw_json
    try:
        value = json.loads(raw_json)
    except (TypeError, ValueError):
        return fallback
    return json.dumps(redact_sensitive_value(value))
