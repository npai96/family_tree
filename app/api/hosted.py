"""Optional Supabase boundary: verified identity and private, durable media."""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.db_runtime import execute, fetch_one, get_conn
from app.api.security import digest_token

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
SERVICE_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
PUBLIC_APP_URL = os.getenv("PUBLIC_APP_URL", "").rstrip("/")
STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "family-media")
ENABLED = bool(SUPABASE_URL)
router = APIRouter()


def validate_configuration(review_enabled: bool) -> None:
    if not ENABLED:
        return
    if review_enabled:
        raise RuntimeError("Supabase authentication requires ENABLE_REVIEW_AUTH=false")
    if not SUPABASE_KEY or not SERVICE_KEY.startswith("sb_secret_") or not PUBLIC_APP_URL.startswith("https://"):
        raise RuntimeError("Hosted mode requires Supabase keys and an HTTPS PUBLIC_APP_URL")
    if not SUPABASE_URL.startswith("https://"):
        raise RuntimeError("SUPABASE_URL must use HTTPS")
    if not os.getenv("DATABASE_URL", "").startswith(("postgres://", "postgresql://")):
        raise RuntimeError("Hosted mode requires durable Postgres DATABASE_URL")


def provider_request(method: str, path: str, *, storage: bool = False, **kwargs) -> httpx.Response:
    key = SERVICE_KEY if storage else SUPABASE_KEY
    headers = {"apikey": key}
    # New Supabase secret keys belong in apikey only; they are not JWTs.
    headers.update(kwargs.pop("headers", {}))
    try:
        response = httpx.request(method, SUPABASE_URL + path, headers=headers, timeout=30, **kwargs)
    except httpx.HTTPError:
        raise HTTPException(503, "Hosted service is temporarily unavailable. Please retry.") from None
    if response.status_code >= 400:
        # Never relay provider bodies: they may contain credentials or internal details.
        raise HTTPException(503 if storage or response.status_code >= 500 else 401,
                            "Hosted service could not complete this request. Please retry.")
    return response


@router.get("/auth/managed/start")
def start_login():
    if not ENABLED:
        raise HTTPException(404, "Not found")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = urlencode({"provider": "google", "redirect_to": PUBLIC_APP_URL + "/auth/managed/callback",
                       "code_challenge": challenge, "code_challenge_method": "s256"})
    response = RedirectResponse(SUPABASE_URL + "/auth/v1/authorize?" + query, status_code=303)
    response.set_cookie("ft_oauth_verifier", verifier, max_age=600, secure=True, httponly=True,
                        samesite="lax", path="/auth/managed")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/auth/managed/callback")
def finish_login(request: Request):
    if not ENABLED:
        raise HTTPException(404, "Not found")
    verifier = request.cookies.get("ft_oauth_verifier")
    code = request.query_params.get("code")
    if not verifier or not code:
        response = RedirectResponse("/?signin=failed", status_code=303)
    else:
        try:
            data = provider_request("POST", "/auth/v1/token?grant_type=pkce",
                                    json={"auth_code": code, "code_verifier": verifier}).json()
            # Verify identity with Auth; never trust an ID supplied by the browser.
            identity = provider_request("GET", "/auth/v1/user", headers={
                "Authorization": "Bearer " + data["access_token"]}).json()
            user_id = str(UUID(identity["id"]))
            if not identity.get("email_confirmed_at"):
                raise ValueError("Unverified identity")
            display_name = str((identity.get("user_metadata") or {}).get("full_name") or "Family steward")[:200]
            token = secrets.token_urlsafe(32)
            now = datetime.now(timezone.utc)
            expires = (now + timedelta(days=14)).isoformat()
            with get_conn() as conn:
                execute(conn, "INSERT INTO users (id, display_name, created_at) VALUES (?, ?, ?) ON CONFLICT (id) DO NOTHING",
                        (user_id, display_name, now.isoformat()))
                execute(conn, "INSERT INTO auth_sessions (token, user_id, created_at, expires_at, auth_source) VALUES (?, ?, ?, ?, 'supabase')",
                        (digest_token(token), user_id, now.isoformat(), expires))
            response = RedirectResponse("/", status_code=303)
            # One-use handoff; the UI continues using its existing bearer-session contract.
            response.set_cookie("ft_login", token, max_age=120, secure=True, httponly=True,
                                samesite="strict", path="/auth/managed/session")
        except (HTTPException, ValueError, KeyError, TypeError):
            response = RedirectResponse("/?signin=failed", status_code=303)
    response.delete_cookie("ft_oauth_verifier", path="/auth/managed", secure=True, httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/auth/managed/session")
def take_session(request: Request):
    if not ENABLED:
        raise HTTPException(404, "Not found")
    token = request.cookies.get("ft_login", "")
    with get_conn() as conn:
        row = fetch_one(conn, "SELECT user_id FROM auth_sessions WHERE token = ? AND auth_source = 'supabase' AND revoked_at IS NULL AND expires_at > ?",
                        (digest_token(token), datetime.now(timezone.utc).isoformat()))
    response = JSONResponse({"access_token": token if row else None}, headers={"Cache-Control": "no-store"})
    response.delete_cookie("ft_login", path="/auth/managed/session", secure=True, httponly=True, samesite="strict")
    return response


def upload_object(key: str, path, media_type: str) -> None:
    with path.open("rb") as content:
        provider_request("POST", f"/storage/v1/object/{STORAGE_BUCKET}/{key}", storage=True,
                         content=content, headers={"Content-Type": media_type})


def read_object(key: str) -> bytes:
    return provider_request("GET", f"/storage/v1/object/{STORAGE_BUCKET}/{key}", storage=True).content


def delete_object(key: str) -> None:
    provider_request("DELETE", f"/storage/v1/object/{STORAGE_BUCKET}", storage=True, json={"prefixes": [key]})
