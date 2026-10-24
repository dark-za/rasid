"""اختبارات مصادقة X-API-Key.

معظم الاختبارات يبني تطبيقاً صغيراً معتمداً على require_api_key نفسه
حتى لا تعتمد على قاعدة بيانات حقيقية.
اختبارات الأحرف غير ASCII تُستدعى على مستوى ASGI ببايتات خام (سلوك uvicorn
الفعلي) لأن طبقة httpx في TestClient ترفض رؤوساً غير ASCII.
"""
import asyncio
import json

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

import config
import main

test_app = FastAPI()


@test_app.get("/protected")
def protected(_: None = Depends(main.require_api_key)):
    return {"ok": True}


@pytest.fixture(autouse=True)
def _clean_settings_cache():
    yield
    config.settings.cache_clear()


def _client() -> TestClient:
    return TestClient(test_app)


def _raw_get(path: str, headers: list[tuple[bytes, bytes]]) -> tuple[int, dict | None]:
    """استدعاء ASGI ببايتات خام — نفس مسار uvicorn الحقيقي للرؤوس."""
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

    asyncio.run(test_app(scope, receive, send))
    status = sent[0]["status"]
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, (json.loads(body) if body else None)


def _set_key(monkeypatch, value=None):
    if value is None:
        monkeypatch.delenv("RASID_API_KEY", raising=False)
    else:
        monkeypatch.setenv("RASID_API_KEY", value)
    config.settings.cache_clear()


def test_missing_key_returns_401(monkeypatch):
    _set_key(monkeypatch, "rasid-secret-123")
    response = _client().get("/protected")
    assert response.status_code == 401


def test_wrong_ascii_key_returns_401(monkeypatch):
    _set_key(monkeypatch, "rasid-secret-123")
    response = _client().get("/protected", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401


def test_non_ascii_wrong_key_returns_401_not_500(monkeypatch):
    """انكسار سابق: hmac.compare_digest مع نص غير ASCII كان يرمي TypeError -> 500."""
    _set_key(monkeypatch, "rasid-secret-123")
    status, _ = _raw_get("/protected", [(b"x-api-key", "مفتاح_خاطئ".encode("utf-8"))])
    assert status == 401


def test_correct_ascii_key_returns_200(monkeypatch):
    _set_key(monkeypatch, "rasid-secret-123")
    response = _client().get("/protected", headers={"X-API-Key": "rasid-secret-123"})
    assert response.status_code == 200


def test_correct_non_ascii_key_returns_200(monkeypatch):
    """مفتاح مُهيّأ بأحرف عربية والمُرسل يرسل بايتات UTF-8 نفسها — يجب المصادقة."""
    _set_key(monkeypatch, "سر-راصد-2026")
    status, body = _raw_get("/protected", [(b"x-api-key", "سر-راصد-2026".encode("utf-8"))])
    assert status == 200
    assert body == {"ok": True}


def test_non_ascii_key_mismatch_returns_401(monkeypatch):
    """مفتاحان غير ASCII مختلفان: 401 بلا استثناءات."""
    _set_key(monkeypatch, "سر-راصد-2026")
    status, _ = _raw_get("/protected", [(b"x-api-key", "مفتاح-آخر".encode("utf-8"))])
    assert status == 401


def test_unconfigured_api_returns_503(monkeypatch):
    _set_key(monkeypatch, None)
    response = _client().get("/protected", headers={"X-API-Key": "anything"})
    assert response.status_code == 503
