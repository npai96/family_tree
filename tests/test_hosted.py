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
    return TestClient(main.app, base_url='https://test.example')


def session(user_id=None, source='supabase'):
    user_id = user_id or str(uuid4())
    token = str(uuid4())
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        execute(conn, 'INSERT INTO users VALUES (?, ?, ?) ON CONFLICT (id) DO NOTHING', (user_id, 'Tester', now.isoformat()))
        execute(conn, 'INSERT INTO auth_sessions (token, user_id, created_at, expires_at, auth_source) VALUES (?, ?, ?, ?, ?)',
                (digest_token(token), user_id, now.isoformat(), (now + timedelta(days=14)).isoformat(), source))
    return {'Authorization': f'Bearer {token}'}


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


def test_oauth_pkce_callback_and_handoff(client, monkeypatch):
    user_id = str(uuid4())
    calls = []
    def provider(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path.startswith('/auth/v1/token'):
            assert kwargs['json']['code_verifier']
            return httpx.Response(200, json={'access_token': 'verified-provider-token'})
        assert kwargs['headers']['Authorization'] == 'Bearer verified-provider-token'
        return httpx.Response(200, json={'id': user_id, 'email_confirmed_at': '2026-09-18', 'user_metadata': {'full_name': 'Test Steward'}})
    monkeypatch.setattr(hosted, 'provider_request', provider)
    start = client.get('/auth/managed/start', follow_redirects=False)
    assert 'code_challenge_method=s256' in start.headers['location']
    assert 'HttpOnly' in start.headers['set-cookie'] and 'Secure' in start.headers['set-cookie']
    callback = client.get('/auth/managed/callback?code=provider-code', follow_redirects=False)
    assert callback.headers['location'] == '/'
    assert 'provider-token' not in callback.headers['location']
    handoff = client.get('/auth/managed/session')
    assert handoff.headers['cache-control'] == 'no-store'
    token = handoff.json()['access_token']
    assert client.get('/auth/managed/session').json()['access_token'] is None
    assert client.get('/auth/me', headers={'Authorization': f'Bearer {token}'}).json()['id'] == user_id
    with get_conn() as conn:
        assert fetch_one(conn, 'SELECT token FROM auth_sessions')['token'] == digest_token(token)
    assert len(calls) == 2


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
    upload = client.post(f'/circles/{circle}/persons/{person}/media', headers=owner,
                         files={'file': ('note.txt', b'Family story', 'text/plain')})
    assert upload.status_code == 200
    assert not list(main.MEDIA_DIR.rglob('*.txt'))
    url = f'/circles/{circle}/media/{upload.json()["id"]}/download'
    assert client.get(url, headers=session()).status_code == 403
    ticket = client.post(f'/circles/{circle}/access-tickets', headers=owner, json={'scope': 'media'}).json()['ticket']
    assert client.get(url, params={'ticket': ticket}).content == b'Family story'
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
