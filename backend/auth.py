"""Short-lived bearer tokens for the single configured Rasid administrator."""
import base64
import hashlib
import hmac
import json
import time

from fastapi import Header, HTTPException

import config

TOKEN_TTL_SECONDS = 8 * 60 * 60


class AuthConfigurationError(RuntimeError):
    pass


def _credentials() -> tuple[str, str, bytes]:
    settings = config.settings()
    username = settings["login_username"]
    password = settings["login_password"]
    secret = settings["session_secret"].encode("utf-8")
    if not username or not password or len(secret) < 32:
        raise AuthConfigurationError(
            "اضبط كلمة مرور المشرف وسراً عشوائياً لا يقل عن 32 محرفاً"
        )
    return username, password, secret


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_access_token(username: str, password: str) -> str:
    expected_username, expected_password, secret = _credentials()
    if not (
        hmac.compare_digest(username.encode("utf-8"), expected_username.encode("utf-8"))
        and hmac.compare_digest(password.encode("utf-8"), expected_password.encode("utf-8"))
    ):
        raise PermissionError("بيانات تسجيل الدخول غير صحيحة")

    payload = _encode(
        json.dumps(
            {"sub": expected_username, "exp": int(time.time()) + TOKEN_TTL_SECONDS},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signature = _encode(hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify_access_token(token: str) -> str | None:
    try:
        username, _password, secret = _credentials()
        if len(token) > 4096:
            return None
        payload_part, signature_part = token.split(".", 1)
        expected_signature = _encode(
            hmac.new(secret, payload_part.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature_part, expected_signature):
            return None
        payload = json.loads(_decode(payload_part))
        if (
            payload.get("sub") != username
            or not isinstance(payload.get("exp"), int)
            or payload["exp"] <= int(time.time())
        ):
            return None
        return username
    except (ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError):
        return None


def require_authenticated_user(authorization: str = Header(default="")) -> str:
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=401,
            detail="سجّل الدخول للمتابعة",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        username = verify_access_token(token)
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if username is None:
        raise HTTPException(
            status_code=401,
            detail="انتهت الجلسة أو بيانات الدخول غير صالحة",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username
