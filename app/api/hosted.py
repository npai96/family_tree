"""Optional Supabase boundary: verified identity and private, durable media."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.db_runtime import execute, fetch_one, get_conn
from app.api.security import digest_token
from app.api.security_abuse import enforce_rate_limit

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
SERVICE_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
PUBLIC_APP_URL = os.getenv("PUBLIC_APP_URL", "").rstrip("/")
STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "family-media")
APPROVED_TESTER_EMAILS = frozenset(
    email.strip().casefold() for email in os.getenv("APPROVED_TESTER_EMAILS", "").split(",")
    if email.strip()
)
SESSION_COOKIE = "__Host-ft_session"
ENABLED = bool(SUPABASE_URL)
router = APIRouter()


def csrf_token(session_token: str) -> str:
    """Derive a browser-visible CSRF proof from the HTTP-only session secret."""
    return hmac.new(session_token.encode("utf-8"), b"viraasat-csrf-v1", hashlib.sha256).hexdigest()


def account_is_approved(conn, user_id: str) -> bool:
    """Keep approval active only while the verified email remains configured."""
    if not APPROVED_TESTER_EMAILS:
        return False
    row = fetch_one(conn, "SELECT verified_email FROM approved_accounts WHERE user_id = ?", (user_id,))
    return bool(row and row["verified_email"].casefold() in APPROVED_TESTER_EMAILS)


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
    if not APPROVED_TESTER_EMAILS or any("@" not in email or any(c.isspace() for c in email) for email in APPROVED_TESTER_EMAILS):
        raise RuntimeError("Hosted mode requires APPROVED_TESTER_EMAILS with verified tester email addresses")


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


def _request_peer(request: Request) -> str:
    # Do not trust a client-supplied forwarding header for pre-login limits.
    return request.client.host if request.client else "unknown-peer"


@router.get("/auth/managed/start")
def start_login(request: Request):
    if not ENABLED:
        raise HTTPException(404, "Not found")
    enforce_rate_limit("auth.start", _request_peer(request))
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = urlencode({"provider": "google", "redirect_to": PUBLIC_APP_URL + "/auth/managed/callback",
                       "code_challenge": challenge, "code_challenge_method": "s256",
                       "prompt": "select_account"})
    response = RedirectResponse(SUPABASE_URL + "/auth/v1/authorize?" + query, status_code=303)
    response.set_cookie("ft_oauth_verifier", verifier, max_age=600, secure=True, httponly=True,
                        samesite="lax", path="/auth/managed")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/auth/managed/callback")
def finish_login(request: Request):
    if not ENABLED:
        raise HTTPException(404, "Not found")
    enforce_rate_limit("auth.callback", _request_peer(request))
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
            verified_email = str(identity.get("email") or "").strip().casefold()
            if verified_email not in APPROVED_TESTER_EMAILS:
                raise ValueError("Account is not approved for this demo")
            display_name = str((identity.get("user_metadata") or {}).get("full_name") or "Family steward")[:200]
            token = secrets.token_urlsafe(32)
            now = datetime.now(timezone.utc)
            expires = (now + timedelta(days=14)).isoformat()
            with get_conn() as conn:
                execute(conn, "INSERT INTO users (id, display_name, created_at) VALUES (?, ?, ?) ON CONFLICT (id) DO NOTHING",
                        (user_id, display_name, now.isoformat()))
                # Serialize first-login migration for the same account across devices.
                # Otherwise two callbacks can both see no approval and revoke each other's new session.
                execute(conn, "UPDATE users SET display_name = display_name WHERE id = ?", (user_id,))
                prior_approval = fetch_one(conn, "SELECT verified_email FROM approved_accounts WHERE user_id = ?", (user_id,))
                if not prior_approval or prior_approval["verified_email"] != verified_email:
                    # First V3 login (or a changed provider email) must not revive a V2 bearer.
                    execute(conn, """UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ?
                        AND auth_source = 'supabase' AND revoked_at IS NULL""", (now.isoformat(), user_id))
                execute(conn, """INSERT INTO approved_accounts (user_id, verified_email, approved_at)
                    VALUES (?, ?, ?) ON CONFLICT (user_id) DO UPDATE SET
                    verified_email = excluded.verified_email, approved_at = excluded.approved_at""",
                        (user_id, verified_email, now.isoformat()))
                execute(conn, "INSERT INTO auth_sessions (token, user_id, created_at, expires_at, auth_source) VALUES (?, ?, ?, ?, 'supabase')",
                        (digest_token(token), user_id, now.isoformat(), expires))
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(SESSION_COOKIE, token, max_age=14 * 86400, secure=True,
                                httponly=True, samesite="lax", path="/")
        except (HTTPException, ValueError, KeyError, TypeError):
            response = RedirectResponse("/?signin=failed", status_code=303)
    response.delete_cookie("ft_oauth_verifier", path="/auth/managed", secure=True, httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/auth/managed/session")
def take_session(request: Request):
    if not ENABLED:
        raise HTTPException(404, "Not found")
    token = request.cookies.get(SESSION_COOKIE, "")
    with get_conn() as conn:
        row = fetch_one(conn, "SELECT user_id FROM auth_sessions WHERE token = ? AND auth_source = 'supabase' AND revoked_at IS NULL AND expires_at > ?",
                        (digest_token(token), datetime.now(timezone.utc).isoformat()))
        approved = bool(row and account_is_approved(conn, row["user_id"]))
    response = JSONResponse({"signed_in": approved, "csrf_token": csrf_token(token) if approved else None},
                            headers={"Cache-Control": "no-store"})
    if not approved and token:
        response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


@router.post("/auth/managed/migrate")
def migrate_legacy_browser_session(authorization: Optional[str] = Header(default=None)) -> JSONResponse:
    """Exchange and revoke a V2 browser bearer for a fresh HTTP-only cookie."""
    if not ENABLED:
        raise HTTPException(404, "Not found")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "Missing or invalid auth token")
    old_digest = digest_token(token.strip())
    new_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(days=14)).isoformat()
    with get_conn() as conn:
        row = fetch_one(conn, """SELECT user_id FROM auth_sessions WHERE token = ?
            AND auth_source = 'supabase' AND revoked_at IS NULL AND expires_at > ?""",
            (old_digest, now.isoformat()))
        if not row:
            raise HTTPException(401, "Missing or invalid auth token")
        if not account_is_approved(conn, row["user_id"]):
            raise HTTPException(403, "Account is not approved for this demo")
        revoked = execute(conn, """UPDATE auth_sessions SET revoked_at = ?
            WHERE token = ? AND auth_source = 'supabase' AND revoked_at IS NULL""",
            (now.isoformat(), old_digest))
        if revoked.rowcount != 1:
            raise HTTPException(401, "Missing or invalid auth token")
        execute(conn, """INSERT INTO auth_sessions (token, user_id, created_at, expires_at, auth_source)
            VALUES (?, ?, ?, ?, 'supabase')""",
            (digest_token(new_token), row["user_id"], now.isoformat(), expires))
    response = JSONResponse({"signed_in": True, "csrf_token": csrf_token(new_token)},
                            headers={"Cache-Control": "no-store"})
    response.set_cookie(SESSION_COOKIE, new_token, max_age=14 * 86400, secure=True,
                        httponly=True, samesite="lax", path="/")
    return response


@router.post("/auth/managed/logout", status_code=204)
def logout_managed_session(request: Request) -> Response:
    if not ENABLED:
        raise HTTPException(404, "Not found")
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        with get_conn() as conn:
            execute(conn, "UPDATE auth_sessions SET revoked_at = COALESCE(revoked_at, ?) WHERE token = ? AND auth_source = 'supabase'",
                    (datetime.now(timezone.utc).isoformat(), digest_token(token)))
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


@router.post("/auth/managed/revoke-all", status_code=204)
def revoke_all_sessions(request: Request, authorization: Optional[str] = Header(default=None)) -> Response:
    """Let a verified account invalidate every app session and its dependent media tickets."""
    if not ENABLED:
        raise HTTPException(404, "Not found")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "Missing or invalid auth token")
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        row = fetch_one(
            conn,
            """SELECT user_id FROM auth_sessions
               WHERE token = ? AND auth_source = 'supabase'
                 AND revoked_at IS NULL AND expires_at > ?""",
            (digest_token(token.strip()), now),
        )
        if not row:
            raise HTTPException(401, "Missing or invalid auth token")
        execute(
            conn,
            """UPDATE auth_sessions SET revoked_at = ?
               WHERE user_id = ? AND auth_source = 'supabase' AND revoked_at IS NULL""",
            (now, row["user_id"]),
        )
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


def upload_object(key: str, path, media_type: str) -> None:
    with path.open("rb") as content:
        provider_request("POST", f"/storage/v1/object/{STORAGE_BUCKET}/{key}", storage=True,
                         content=content, headers={"Content-Type": media_type})


def read_object(key: str) -> bytes:
    return provider_request("GET", f"/storage/v1/object/{STORAGE_BUCKET}/{key}", storage=True).content


def delete_object(key: str) -> None:
    provider_request("DELETE", f"/storage/v1/object/{STORAGE_BUCKET}", storage=True, json={"prefixes": [key]})
