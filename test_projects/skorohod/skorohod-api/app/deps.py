"""Зависимости FastAPI: авторизация и роли.

Токен — обычный JWT в заголовке `Authorization: Bearer ...`, выдаётся
сервисом авторизации по СМС-коду. Полезная нагрузка: `sub` (id пользователя),
`exp`, опционально `courier_id`.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import Courier, User

logger = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[Session, Depends(get_session)]
CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def decode_token(token: str) -> dict:
    """Разобрать и проверить JWT."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as error:
        logger.info("auth.bad_token", extra={"error": str(error)})
        raise _unauthorized("токен невалиден или истёк") from error


def get_current_user(session: SessionDep, credentials: CredentialsDep) -> User:
    """Текущий пользователь по токену."""
    if credentials is None or not credentials.credentials:
        raise _unauthorized("нужен токен")

    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if user_id is None:
        raise _unauthorized("в токене нет sub")

    user = session.get(User, int(user_id))
    if user is None:
        raise _unauthorized("пользователь не найден")
    if user.is_blocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "пользователь заблокирован")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    """Доступ только для сотрудников с флагом `is_admin`."""
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "нужны права администратора")
    return user


def require_courier(session: SessionDep, user: CurrentUser) -> Courier:
    """Профиль курьера текущего пользователя."""
    courier = session.scalar(select(Courier).where(Courier.user_id == user.id))
    if courier is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "пользователь не курьер")
    if not courier.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "курьер деактивирован")
    return courier


AdminUser = Annotated[User, Depends(require_admin)]
CurrentCourier = Annotated[Courier, Depends(require_courier)]
