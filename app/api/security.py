from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Mapping, Optional
from urllib.parse import urlsplit


TOKEN_DIGEST_HEX_LENGTH = 64
ALLOWED_APP_ENVIRONMENTS = frozenset({"development", "test", "staging", "production"})
LOCAL_APP_ENVIRONMENTS = frozenset({"development", "test"})
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})
DEFAULT_LOCAL_CORS_ORIGINS = (
    "http://127.0.0.1:8000",
    "http://localhost:8000",
)


@dataclass(frozen=True)
class RuntimeSecurityConfig:
    environment: str
    review_auth_enabled: bool
    legacy_user_header_enabled: bool
    cors_allowed_origins: tuple[str, ...]
    metrics_enabled: bool
    metrics_bearer_token_digest: Optional[str]

    @property
    def auth_mode(self) -> str:
        return "review_unverified" if self.review_auth_enabled else "disabled"


def _parse_bool(name: str, value: Optional[str], *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise RuntimeError(f"{name} must be one of: true, false, 1, 0, yes, no, on, off")


def _parse_cors_origins(value: Optional[str], *, local_environment: bool) -> tuple[str, ...]:
    if value is None:
        return DEFAULT_LOCAL_CORS_ORIGINS if local_environment else ()

    origins: list[str] = []
    for raw_origin in value.split(","):
        raw_origin = raw_origin.strip()
        if not raw_origin:
            continue
        if raw_origin == "*":
            raise RuntimeError("CORS_ALLOWED_ORIGINS cannot contain wildcard origins")
        parsed = urlsplit(raw_origin)
        try:
            parsed_port = parsed.port
        except ValueError as exc:
            raise RuntimeError(f"Invalid CORS origin: {raw_origin}") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError(f"Invalid CORS origin: {raw_origin}")
        host = f"[{parsed.hostname.lower()}]" if ":" in parsed.hostname else parsed.hostname.lower()
        normalized = f"{parsed.scheme.lower()}://{host}"
        if parsed_port is not None:
            normalized += f":{parsed_port}"
        if normalized not in origins:
            origins.append(normalized)
    return tuple(origins)


def load_runtime_security_config(env: Optional[Mapping[str, str]] = None) -> RuntimeSecurityConfig:
    """Load explicit auth policy, defaulting review access on only for local/test use."""
    source = env if env is not None else os.environ
    environment = source.get("APP_ENV", "development").strip().lower() or "development"
    if environment not in ALLOWED_APP_ENVIRONMENTS:
        allowed = ", ".join(sorted(ALLOWED_APP_ENVIRONMENTS))
        raise RuntimeError(f"APP_ENV must be one of: {allowed}")

    local_environment = environment in LOCAL_APP_ENVIRONMENTS
    review_auth_enabled = _parse_bool(
        "ENABLE_REVIEW_AUTH",
        source.get("ENABLE_REVIEW_AUTH"),
        default=local_environment,
    )
    legacy_user_header_enabled = _parse_bool(
        "ALLOW_LEGACY_X_USER_ID",
        source.get("ALLOW_LEGACY_X_USER_ID"),
        default=False,
    )
    cors_allowed_origins = _parse_cors_origins(
        source.get("CORS_ALLOWED_ORIGINS"),
        local_environment=local_environment,
    )
    metrics_enabled = _parse_bool(
        "ENABLE_METRICS_ENDPOINT",
        source.get("ENABLE_METRICS_ENDPOINT"),
        default=local_environment,
    )
    metrics_bearer_token = source.get("METRICS_BEARER_TOKEN", "").strip()
    if metrics_bearer_token and len(metrics_bearer_token) < 32:
        raise RuntimeError("METRICS_BEARER_TOKEN must contain at least 32 characters")
    if metrics_enabled and not local_environment and not metrics_bearer_token:
        raise RuntimeError(
            "METRICS_BEARER_TOKEN with at least 32 characters is required when metrics are enabled outside development or test"
        )
    if legacy_user_header_enabled and not local_environment:
        raise RuntimeError("ALLOW_LEGACY_X_USER_ID may only be enabled in development or test")
    if legacy_user_header_enabled and not review_auth_enabled:
        raise RuntimeError("ALLOW_LEGACY_X_USER_ID requires ENABLE_REVIEW_AUTH=true")

    return RuntimeSecurityConfig(
        environment=environment,
        review_auth_enabled=review_auth_enabled,
        legacy_user_header_enabled=legacy_user_header_enabled,
        cors_allowed_origins=cors_allowed_origins,
        metrics_enabled=metrics_enabled,
        metrics_bearer_token_digest=(
            hashlib.sha256(metrics_bearer_token.encode("utf-8")).hexdigest()
            if metrics_bearer_token
            else None
        ),
    )


def digest_token(token: str) -> str:
    """Return the irreversible lookup key stored for a high-entropy bearer token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_token_digest(value: str) -> bool:
    if len(value) != TOKEN_DIGEST_HEX_LENGTH:
        return False
    return all(character in "0123456789abcdef" for character in value)
