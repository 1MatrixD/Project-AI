from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import get_settings

ALGO = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def create_user_token(user_id: uuid.UUID) -> str:
    s = get_settings()
    payload = {
        "sub": str(user_id),
        "scope": "user",
        "exp": datetime.now(timezone.utc) + timedelta(hours=s.jwt_ttl_hours),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=ALGO)


def create_service_token(user_id: uuid.UUID, project_id: uuid.UUID, days: int = 365) -> str:
    """Токен для MCP-сервера/плагина: доступ только к одному проекту."""
    s = get_settings()
    payload = {
        "sub": str(user_id),
        "scope": "service",
        "project_id": str(project_id),
        "exp": datetime.now(timezone.utc) + timedelta(days=days),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=ALGO)


def decode_token(token: str) -> dict:
    return jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGO])
