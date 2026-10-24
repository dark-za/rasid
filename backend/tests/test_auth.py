"""Tests for configured administrator credentials and short-lived bearer tokens."""
import asyncio
import json
import time

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
import pytest
from fastapi import HTTPException

import auth
import config
import main
import schemas

_test_app = FastAPI()


@_test_app.get("/protected")
def protected(_: str = Depends(auth.require_authenticated_user)):
    return {"ok": True}


@pytest.fixture(autouse=True)
def _clean_settings_cache():
    yield
    config.settings.cache_clear()


def _set_credentials(monkeypatch, *, username="admin", password="strong-password"):
    monkeypatch.setenv("RASID_LOGIN_USERNAME", username)
    monkeypatch.setenv("RASID_LOGIN_PASSWORD", password)
    monkeypatch.setenv("RASID_SESSION_SECRET", "s" * 40)
    config.settings.cache_clear()


def _raw_get(path: str, headers: list[tuple[bytes, bytes]]) -> tuple[int, dict | None]:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(_test_app(scope, receive, send))
    status = sent[0]["status"]
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, (json.loads(body) if body else None)


def test_login_issues_token_for_configured_credentials(monkeypatch):
    _set_credentials(monkeypatch)

    response = main.login(schemas.LoginIn(username="admin", password="strong-password"))

    assert response["token_type"] == "bearer"
    assert response["expires_in"] == auth.TOKEN_TTL_SECONDS
    assert auth.verify_access_token(response["access_token"]) == "admin"


def test_wrong_login_credentials_are_rejected(monkeypatch):
    _set_credentials(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        main.login(schemas.LoginIn(username="admin", password="wrong-password"))

    assert exc.value.status_code == 401


def test_protected_endpoint_requires_bearer_token(monkeypatch):
    _set_credentials(monkeypatch)
    token = auth.issue_access_token("admin", "strong-password")

    status, body = _raw_get(
        "/protected", [(b"authorization", f"Bearer {token}".encode("ascii"))]
    )

    assert status == 200
    assert body == {"ok": True}


def test_missing_and_tampered_tokens_are_rejected(monkeypatch):
    _set_credentials(monkeypatch)
    token = auth.issue_access_token("admin", "strong-password")

    missing_status, _ = _raw_get("/protected", [])
    tampered_status, _ = _raw_get(
        "/protected", [(b"authorization", f"Bearer {token}x".encode("ascii"))]
    )

    assert missing_status == 401
    assert tampered_status == 401


def test_expired_token_is_rejected(monkeypatch):
    _set_credentials(monkeypatch)
    token = auth.issue_access_token("admin", "strong-password")
    current_time = time.time()
    monkeypatch.setattr(auth.time, "time", lambda: current_time + auth.TOKEN_TTL_SECONDS + 1)

    assert auth.verify_access_token(token) is None


def test_authentication_requires_configured_credentials_and_secret(monkeypatch):
    monkeypatch.delenv("RASID_LOGIN_USERNAME", raising=False)
    monkeypatch.delenv("RASID_LOGIN_PASSWORD", raising=False)
    monkeypatch.delenv("RASID_SESSION_SECRET", raising=False)
    config.settings.cache_clear()

    with pytest.raises(HTTPException) as exc:
        main.login(schemas.LoginIn(username="admin", password="password"))

    assert exc.value.status_code == 503


def test_public_reads_and_admin_only_writes():
    routes = {
        (route.path, method): route
        for route in main.app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    public_reads = [
        ("/api/attendance/today", "GET"),
        ("/api/attendance", "GET"),
        ("/api/reports/late", "GET"),
        ("/api/shifts", "GET"),
        ("/api/employees", "GET"),
        ("/api/employee-shifts", "GET"),
        ("/api/employee-branches", "GET"),
    ]
    admin_writes = [
        ("/api/admin/database", "PUT"),
        ("/api/admin/database/test", "POST"),
        ("/api/shifts", "POST"),
        ("/api/shifts/{shift_id}", "PUT"),
        ("/api/shifts/{shift_id}", "DELETE"),
        ("/api/employees", "POST"),
        ("/api/employees/sync", "POST"),
        ("/api/employees/{employee_id}", "PUT"),
        ("/api/employees/{employee_id}", "DELETE"),
        ("/api/employees/{employee_id}/deactivate", "POST"),
        ("/api/employees/{employee_id}/activate", "POST"),
        ("/api/employee-shifts", "POST"),
        ("/api/employee-shifts/{assignment_id}", "DELETE"),
        ("/api/employee-branches", "POST"),
        ("/api/employee-branches/{history_id}", "DELETE"),
    ]

    for route_key in public_reads:
        route = routes[route_key]
        assert all(
            dependency.call is not main.require_authenticated_user
            for dependency in route.dependant.dependencies
        )

    admin_reads = [("/api/admin/database", "GET")]
    for route_key in admin_reads:
        route = routes[route_key]
        assert any(
            dependency.call is main.require_authenticated_user
            for dependency in route.dependant.dependencies
        )

    for route_key in admin_writes:
        route = routes[route_key]
        assert any(
            dependency.call is main.require_authenticated_user
            for dependency in route.dependant.dependencies
        )
