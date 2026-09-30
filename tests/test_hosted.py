"""Hosted boundaries tested without real provider credentials or network calls."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import hosted, main
from app.api.db_runtime import configure_database, execute, get_conn, fetch_one
from app.api.security import digest_token
from scripts.revoke_hosted_sessions import revoke_sessions


@pytest.fixture
def client(tmp_path, monkeypatch):
    configure_database(db_path=tmp_path / 'hosted.db')
    monkeypatch.setattr(main, 'MEDIA_DIR', tmp_path / 'media')
    main.init_db(main.MEDIA_DIR)
    monkeypatch.setattr(main, 'REVIEW_AUTH_ENABLED', False)
    monkeypatch.setattr(main, 'ALLOW_LEGACY_X_USER_ID', False)
    monkeypatch.setattr(hosted, 'ENABLED', True)
    monkeypatch.setattr(hosted, 'SUPABASE_URL', 'https://test.supabase.co')
    monkeypatch.setattr(hosted, 'PUBLIC_APP_URL', 'https://test.example')
    monkeypatch.setattr(hosted, 'APPROVED_TESTER_EMAILS', frozenset({'approved@example.test'}))
    return TestClient(main.app, base_url='https://test.example')


def session(user_id=None, source='supabase'):
    user_id = user_id or str(uuid4())
    token = str(uuid4())
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        execute(conn, 'INSERT INTO users VALUES (?, ?, ?) ON CONFLICT (id) DO NOTHING', (user_id, 'Tester', now.isoformat()))
        if source == 'supabase':
            execute(conn, '''INSERT INTO approved_accounts (user_id, verified_email, approved_at)
                VALUES (?, ?, ?) ON CONFLICT (user_id) DO NOTHING''',
                (user_id, 'approved@example.test', now.isoformat()))
        execute(conn, 'INSERT INTO auth_sessions (token, user_id, created_at, expires_at, auth_source) VALUES (?, ?, ?, ?, ?)',
                (digest_token(token), user_id, now.isoformat(), (now + timedelta(days=14)).isoformat(), source))
    return {'Authorization': f'Bearer {token}'}


def use_session_cookie(client: TestClient, authorization: dict[str, str]) -> str:
    """Model a browser with an existing hosted session, without a JS bearer."""
    token = authorization['Authorization'].split(' ', 1)[1]
    client.cookies.set(hosted.SESSION_COOKIE, token)
    return hosted.csrf_token(token)


def test_verified_accounts_isolate_circles_and_restore_sessions(client):
    owner, stranger = session(), session()
    assert client.get('/runtime-config').json()['auth_mode'] == 'supabase'
    assert client.get('/users').status_code == 503
    assert client.post('/auth/login', json={'display_name': 'Tester'}).status_code == 503
    circle = client.post('/circles', headers=owner, json={'name': 'Private'}).json()['id']
    person = client.post(f'/circles/{circle}/persons', headers=owner, json={'full_name': 'Sample Person'})
    assert person.status_code == 200
    assert client.get(f'/circles/{circle}/persons', headers=stranger).status_code == 403
    assert client.get('/circles', headers=stranger).json() == []
    # New HTTP client, same durable database and account session.
    returning = TestClient(main.app)
    assert returning.get(f'/circles/{circle}/persons', headers=owner).json()[0]['full_name'] == 'Sample Person'
    review = session(source='review')
    assert client.get('/auth/me', headers=review).status_code == 401
    assert client.post('/auth/logout', headers=owner).status_code == 204
    assert returning.get('/circles', headers=owner).status_code == 401


def test_account_can_revoke_all_hosted_sessions_without_affecting_other_accounts(client):
    user_id = str(uuid4())
    first = session(user_id)
    second = session(user_id)
    other = session()
    review = session(user_id, source='review')
    circle_id = client.post('/circles', headers=first, json={'name': 'Private'}).json()['id']
    ticket = client.post(f'/circles/{circle_id}/access-tickets', headers=second, json={'scope': 'media'}).json()['ticket']

    assert client.post('/auth/managed/revoke-all', headers=first).status_code == 204
    assert client.get('/auth/me', headers=first).status_code == 401
    assert client.get('/auth/me', headers=second).status_code == 401
    assert client.get('/auth/me', headers=other).status_code == 200
    assert client.get('/auth/me', headers=review).status_code == 401  # review identity stays disabled in hosted mode
    with get_conn() as conn:
        row = fetch_one(conn, 'SELECT revoked_at FROM auth_sessions WHERE token = ?',
                        (digest_token(review['Authorization'].split(' ', 1)[1]),))
        assert row['revoked_at'] is None
        assert main._principal_from_circle_access_ticket(conn, ticket, circle_id, 'media') is None

    assert client.post('/auth/managed/revoke-all', headers=second).status_code == 401
    assert client.post('/auth/managed/revoke-all').status_code == 401
    assert client.post('/auth/managed/revoke-all', headers={'Authorization': 'Bearer unknown'}).status_code == 401


def test_operator_revoke_is_dry_run_by_default_and_scoped_to_hosted_account(client):
    user_id = str(uuid4())
    hosted_session = session(user_id)
    other_session = session()
    review_session = session(user_id, source='review')
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        assert revoke_sessions(conn, user_id, now, apply=False) == 1
    assert client.get('/auth/me', headers=hosted_session).status_code == 200
    with get_conn() as conn:
        assert revoke_sessions(conn, user_id, now, apply=True) == 1
    assert client.get('/auth/me', headers=hosted_session).status_code == 401
    assert client.get('/auth/me', headers=other_session).status_code == 200
    with get_conn() as conn:
        review_digest = digest_token(review_session['Authorization'].split(' ', 1)[1])
        assert fetch_one(conn, 'SELECT revoked_at FROM auth_sessions WHERE token = ?', (review_digest,))['revoked_at'] is None


def test_oauth_pkce_callback_sets_http_only_session_cookie(client, monkeypatch):
    user_id = str(uuid4())
    calls = []
    def provider(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path.startswith('/auth/v1/token'):
            assert kwargs['json']['code_verifier']
            return httpx.Response(200, json={'access_token': 'verified-provider-token'})
        assert kwargs['headers']['Authorization'] == 'Bearer verified-provider-token'
        return httpx.Response(200, json={'id': user_id, 'email': 'approved@example.test',
                                         'email_confirmed_at': '2026-09-18',
                                         'user_metadata': {'full_name': 'Test Steward'}})
    monkeypatch.setattr(hosted, 'provider_request', provider)
    start = client.get('/auth/managed/start', follow_redirects=False)
    assert 'code_challenge_method=s256' in start.headers['location']
    assert 'HttpOnly' in start.headers['set-cookie'] and 'Secure' in start.headers['set-cookie']
    callback = client.get('/auth/managed/callback?code=provider-code', follow_redirects=False)
    assert callback.headers['location'] == '/'
    assert 'provider-token' not in callback.headers['location']
    cookie_header = callback.headers['set-cookie']
    assert hosted.SESSION_COOKIE + '=' in cookie_header
    assert 'httponly' in cookie_header.lower()
    assert 'secure' in cookie_header.lower()
    assert 'samesite=lax' in cookie_header.lower()
    assert 'path=/' in cookie_header.lower()
    assert 'domain=' not in cookie_header.lower()
    token = client.cookies.get(hosted.SESSION_COOKIE)
    assert token
    assert token not in callback.headers['location']
    status = client.get('/auth/managed/session')
    assert status.headers['cache-control'] == 'no-store'
    assert status.json() == {'signed_in': True, 'csrf_token': hosted.csrf_token(token)}
    assert token not in status.text
    assert client.get('/auth/managed/session').json() == status.json()
    assert client.get('/auth/me').json()['id'] == user_id
    with get_conn() as conn:
        assert fetch_one(conn, 'SELECT token FROM auth_sessions')['token'] == digest_token(token)
    assert len(calls) == 2


def test_unapproved_google_identity_never_receives_app_session(client, monkeypatch):
    user_id = str(uuid4())
    def provider(method, path, **kwargs):
        if path.startswith('/auth/v1/token'):
            return httpx.Response(200, json={'access_token': 'provider-token'})
        return httpx.Response(200, json={'id': user_id, 'email': 'not-approved@example.test',
                                         'email_confirmed_at': '2026-09-18'})
    monkeypatch.setattr(hosted, 'provider_request', provider)
    assert client.get('/auth/managed/start', follow_redirects=False).status_code == 303
    callback = client.get('/auth/managed/callback?code=provider-code', follow_redirects=False)
    assert callback.status_code == 303 and callback.headers['location'] == '/?signin=failed'
    assert hosted.SESSION_COOKIE not in client.cookies
    with get_conn() as conn:
        assert fetch_one(conn, 'SELECT id FROM users WHERE id = ?', (user_id,)) is None


def test_first_v3_login_keeps_preexisting_v2_bearer_revoked(client, monkeypatch):
    user_id = str(uuid4())
    old = session(user_id)
    old_digest = digest_token(old['Authorization'].split(' ', 1)[1])
    with get_conn() as conn:
        execute(conn, 'DELETE FROM approved_accounts WHERE user_id = ?', (user_id,))
    assert client.get('/auth/me', headers=old).status_code == 401

    def provider(method, path, **kwargs):
        if path.startswith('/auth/v1/token'):
            return httpx.Response(200, json={'access_token': 'provider-token'})
        return httpx.Response(200, json={'id': user_id, 'email': 'approved@example.test',
                                         'email_confirmed_at': '2026-09-18'})
    monkeypatch.setattr(hosted, 'provider_request', provider)
    assert client.get('/auth/managed/start', follow_redirects=False).status_code == 303
    assert client.get('/auth/managed/callback?code=provider-code', follow_redirects=False).headers['location'] == '/'
    assert client.get('/auth/me').status_code == 200
    assert client.get('/auth/me', headers=old).status_code == 401
    with get_conn() as conn:
        assert fetch_one(conn, 'SELECT revoked_at FROM auth_sessions WHERE token = ?', (old_digest,))['revoked_at']


def test_later_approved_login_preserves_first_device_session(client, monkeypatch):
    user_id = str(uuid4())
    def provider(method, path, **kwargs):
        if path.startswith('/auth/v1/token'):
            return httpx.Response(200, json={'access_token': 'provider-token'})
        return httpx.Response(200, json={'id': user_id, 'email': 'approved@example.test',
                                         'email_confirmed_at': '2026-09-18'})
    monkeypatch.setattr(hosted, 'provider_request', provider)
    second_device = TestClient(main.app, base_url='https://test.example')
    for device in (client, second_device):
        assert device.get('/auth/managed/start', follow_redirects=False).status_code == 303
        assert device.get('/auth/managed/callback?code=provider-code', follow_redirects=False).headers['location'] == '/'
    assert client.cookies.get(hosted.SESSION_COOKIE) != second_device.cookies.get(hosted.SESSION_COOKIE)
    assert client.get('/auth/me').json()['id'] == user_id
    assert second_device.get('/auth/me').json()['id'] == user_id


def test_removing_tester_approval_revokes_existing_session_and_ticket(client, monkeypatch):
    account = session()
    circle = client.post('/circles', headers=account, json={'name': 'Private'}).json()['id']
    ticket = client.post(f'/circles/{circle}/access-tickets', headers=account,
                         json={'scope': 'media'}).json()['ticket']
    monkeypatch.setattr(hosted, 'APPROVED_TESTER_EMAILS', frozenset())
    assert client.get('/auth/me', headers=account).status_code == 401
    assert client.get('/auth/managed/session').json()['signed_in'] is False
    with get_conn() as conn:
        assert main._principal_from_circle_access_ticket(conn, ticket, circle, 'media') is None


def test_cookie_reads_work_but_writes_require_matching_csrf_header(client):
    owner = session()
    csrf = use_session_cookie(client, owner)
    assert client.get('/auth/me').status_code == 200
    assert client.post('/circles', json={'name': 'Blocked'}).status_code == 403
    assert client.post('/circles', headers={'X-FT-CSRF': 'wrong'}, json={'name': 'Blocked'}).status_code == 403
    created = client.post('/circles', headers={'X-FT-CSRF': csrf}, json={'name': 'Allowed'})
    assert created.status_code == 200
    assert [circle['name'] for circle in client.get('/circles').json()] == ['Allowed']
    assert client.get('/auth/me', headers={'Authorization': 'Bearer unknown'}).status_code == 401


def test_legacy_browser_migration_rotates_bearer_into_cookie(client):
    legacy = session()
    old_token = legacy['Authorization'].split(' ', 1)[1]
    circle = client.post('/circles', headers=legacy, json={'name': 'Private'}).json()['id']
    old_ticket = client.post(f'/circles/{circle}/access-tickets', headers=legacy,
                             json={'scope': 'media'}).json()['ticket']
    response = client.post('/auth/managed/migrate', headers=legacy)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    cookie_header = response.headers['set-cookie'].lower()
    assert 'httponly' in cookie_header and 'secure' in cookie_header and 'samesite=lax' in cookie_header
    new_token = client.cookies.get(hosted.SESSION_COOKIE)
    assert new_token and new_token != old_token
    assert old_token not in response.text and new_token not in response.text
    assert response.json() == {'signed_in': True, 'csrf_token': hosted.csrf_token(new_token)}
    assert client.get('/auth/me', headers=legacy).status_code == 401
    assert client.get('/auth/me').status_code == 200
    assert client.get(f'/circles/{circle}/persons').status_code == 200
    assert client.post('/auth/managed/migrate', headers=legacy).status_code == 401
    with get_conn() as conn:
        old = fetch_one(conn, 'SELECT revoked_at FROM auth_sessions WHERE token = ?', (digest_token(old_token),))
        new = fetch_one(conn, 'SELECT revoked_at FROM auth_sessions WHERE token = ?', (digest_token(new_token),))
        assert old['revoked_at'] is not None and new['revoked_at'] is None
        assert main._principal_from_circle_access_ticket(conn, old_ticket, circle, 'media') is None


def test_cookie_logout_revokes_session_and_media_tickets(client):
    owner = session()
    csrf = use_session_cookie(client, owner)
    circle = client.post('/circles', headers={'X-FT-CSRF': csrf}, json={'name': 'Private'}).json()['id']
    ticket = client.post(f'/circles/{circle}/access-tickets', headers={'X-FT-CSRF': csrf},
                         json={'scope': 'media'}).json()['ticket']
    assert client.post('/auth/managed/logout').status_code == 403
    assert client.get('/auth/me').status_code == 200
    assert client.post('/auth/managed/logout', headers={'X-FT-CSRF': csrf}).status_code == 204
    assert client.get('/auth/managed/session').json() == {'signed_in': False, 'csrf_token': None}
    assert client.get('/auth/me').status_code == 401
    with get_conn() as conn:
        assert main._principal_from_circle_access_ticket(conn, ticket, circle, 'media') is None


def test_cookie_revoke_all_invalidates_other_devices_and_tickets(client):
    user_id = str(uuid4())
    first = session(user_id)
    other_device = session(user_id)
    different_account = session()
    csrf = use_session_cookie(client, first)
    circle = client.post('/circles', headers={'X-FT-CSRF': csrf}, json={'name': 'Private'}).json()['id']
    ticket = client.post(f'/circles/{circle}/access-tickets', headers=other_device,
                         json={'scope': 'media'}).json()['ticket']
    assert client.post('/auth/managed/revoke-all').status_code == 403
    assert client.post('/auth/managed/revoke-all', headers={'X-FT-CSRF': csrf}).status_code == 204
    assert client.get('/auth/me').status_code == 401
    assert client.get('/auth/me', headers=other_device).status_code == 401
    assert client.get('/auth/me', headers=different_account).status_code == 200
    with get_conn() as conn:
        assert main._principal_from_circle_access_ticket(conn, ticket, circle, 'media') is None


def test_review_mode_still_accepts_explicit_bearer_without_hosted_cookie(client, monkeypatch):
    monkeypatch.setattr(hosted, 'ENABLED', False)
    monkeypatch.setattr(main, 'REVIEW_AUTH_ENABLED', True)
    review = session(source='review')
    assert client.get('/auth/me', headers=review).status_code == 200
    assert client.post('/circles', headers=review, json={'name': 'Review'}).status_code == 200


def test_callback_without_pkce_and_provider_failure_do_not_create_sessions(client, monkeypatch):
    assert client.get('/auth/managed/callback?code=bad', follow_redirects=False).headers['location'] == '/?signin=failed'
    def failed(*args, **kwargs):
        raise main.HTTPException(503, 'Unavailable')
    monkeypatch.setattr(hosted, 'provider_request', failed)
    client.get('/auth/managed/start', follow_redirects=False)
    assert client.get('/auth/managed/callback?code=bad', follow_redirects=False).headers['location'] == '/?signin=failed'
    with get_conn() as conn:
        assert fetch_one(conn, 'SELECT COUNT(*) AS n FROM auth_sessions')['n'] == 0


def test_private_media_survives_local_file_loss_and_tickets_respect_logout(client, monkeypatch):
    objects = {}
    monkeypatch.setattr(hosted, 'upload_object', lambda key, path, mime: objects.update({key: path.read_bytes()}))
    monkeypatch.setattr(hosted, 'read_object', lambda key: objects[key])
    owner = session()
    circle = client.post('/circles', headers=owner, json={'name': 'Archive'}).json()['id']
    person = client.post(f'/circles/{circle}/persons', headers=owner, json={'full_name': 'Asha'}).json()['id']
    rejected = client.post(f'/circles/{circle}/persons/{person}/media', headers=owner,
                           files={'file': ('note.txt', b'Family story', 'text/plain')})
    assert rejected.status_code == 415
    upload = client.post(f'/circles/{circle}/persons/{person}/media', headers=owner,
                         files={'file': ('portrait.jpg', b'\xff\xd8\xffFamily portrait', 'image/jpeg')})
    assert upload.status_code == 200
    assert not list(main.MEDIA_DIR.rglob('*.jpg'))
    url = f'/circles/{circle}/media/{upload.json()["id"]}/download'
    assert client.get(url, headers=session()).status_code == 403
    ticket = client.post(f'/circles/{circle}/access-tickets', headers=owner, json={'scope': 'media'}).json()['ticket']
    preview = client.get(url, params={'ticket': ticket})
    assert preview.content == b'\xff\xd8\xffFamily portrait'
    assert preview.headers['content-type'] == 'image/jpeg'
    assert preview.headers['content-disposition'].startswith('inline;')
    assert preview.headers['referrer-policy'] == 'no-referrer'
    assert client.post('/auth/logout', headers=owner).status_code == 204
    assert client.get(url, params={'ticket': ticket}).status_code == 401


def test_hosted_config_fails_closed(monkeypatch):
    monkeypatch.setattr(hosted, 'ENABLED', True)
    with pytest.raises(RuntimeError, match='ENABLE_REVIEW_AUTH'):
        hosted.validate_configuration(True)
    monkeypatch.setattr(hosted, 'SUPABASE_KEY', '')
    with pytest.raises(RuntimeError, match='keys'):
        hosted.validate_configuration(False)
    monkeypatch.setattr(hosted, 'SUPABASE_KEY', 'sb_publishable_test')
    monkeypatch.setattr(hosted, 'SERVICE_KEY', 'legacy-service-role-jwt')
    with pytest.raises(RuntimeError, match='keys'):
        hosted.validate_configuration(False)
    monkeypatch.setattr(hosted, 'SERVICE_KEY', 'sb_secret_test')
    monkeypatch.setattr(hosted, 'PUBLIC_APP_URL', 'https://test.example')
    monkeypatch.setattr(hosted, 'SUPABASE_URL', 'https://test.supabase.co')
    monkeypatch.setenv('DATABASE_URL', 'postgresql://localhost/test')
    monkeypatch.setattr(hosted, 'APPROVED_TESTER_EMAILS', frozenset())
    with pytest.raises(RuntimeError, match='APPROVED_TESTER_EMAILS'):
        hosted.validate_configuration(False)


def test_storage_uses_rotatable_secret_without_jwt_header(monkeypatch):
    monkeypatch.setattr(hosted, 'SUPABASE_URL', 'https://test.supabase.co')
    monkeypatch.setattr(hosted, 'SERVICE_KEY', 'sb_secret_test')
    seen = []
    def request(method, url, **kwargs):
        seen.append(kwargs['headers'])
        return httpx.Response(200, content=b'private image')
    monkeypatch.setattr(hosted.httpx, 'request', request)
    assert hosted.read_object('circle/person/image.jpg') == b'private image'
    assert seen[0]['apikey'] == 'sb_secret_test'
    assert 'Authorization' not in seen[0]


def test_provider_errors_are_redacted(monkeypatch):
    monkeypatch.setattr(hosted.httpx, 'request', lambda *a, **kw: httpx.Response(500, text='SECRET'))
    with pytest.raises(main.HTTPException) as error:
        hosted.provider_request('GET', '/auth/v1/user')
    assert error.value.status_code == 503
    assert 'SECRET' not in error.value.detail


def test_sample_is_private_idempotent_and_editable_on_second_device(client):
    user_id = str(uuid4())
    owner = session(user_id)
    other_device = session(user_id)
    stranger = session()
    sample = client.post('/demo/sample-circle', headers=owner)
    assert sample.status_code == 200
    circle = sample.json()['id']
    assert client.post('/demo/sample-circle', headers=other_device).json()['id'] == circle
    assert client.post('/demo/sample-circle', headers=stranger).json()['id'] != circle
    people = client.get(f'/circles/{circle}/persons', headers=other_device).json()
    assert len(people) == 5
    person = people[0]['id']
    update = client.patch(f'/circles/{circle}/persons/{person}', headers=other_device, json={'occupation': 'Updated on another device'})
    assert update.status_code == 200
    assert any(p['occupation'] == 'Updated on another device' for p in client.get(f'/circles/{circle}/persons', headers=owner).json())
    graph = client.get(f'/circles/{circle}/graph/subgraph', headers=owner, params={'root_person_id': person, 'direction': 'descendants', 'depth': 3})
    assert graph.status_code == 200
    revisions = client.get(f'/circles/{circle}/persons/{person}/revisions', headers=owner).json()
    assert len(revisions) == 2
    assert client.post('/demo/sample-circle').status_code == 401
