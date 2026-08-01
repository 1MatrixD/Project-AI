from __future__ import annotations

import uuid

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import Project, User
from .security import decode_token


def _extract_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    # SSE через EventSource не умеет заголовки — разрешаем token в query
    token = request.query_params.get("token")
    if token:
        return token
    raise HTTPException(status_code=401, detail="Не авторизован")


async def get_auth_payload(request: Request) -> dict:
    token = _extract_token(request)
    try:
        return decode_token(token)
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Недействительный токен")


async def get_current_user(
    payload: dict = Depends(get_auth_payload),
    session: AsyncSession = Depends(get_session),
) -> User:
    user = await session.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user


async def get_project(
    project_id: uuid.UUID,
    payload: dict = Depends(get_auth_payload),
    session: AsyncSession = Depends(get_session),
) -> Project:
    """Доступ к проекту: владелец (scope=user) или сервисный токен этого проекта (scope=service)."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    scope = payload.get("scope", "user")
    if scope == "service":
        if payload.get("project_id") != str(project_id):
            raise HTTPException(status_code=403, detail="Токен не для этого проекта")
        return project
    if str(project.owner_id) != payload["sub"]:
        raise HTTPException(status_code=403, detail="Нет доступа к проекту")
    return project


async def find_owned_project(
    session: AsyncSession, owner_id: uuid.UUID, project_id: uuid.UUID
) -> Project | None:
    res = await session.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
    )
    return res.scalar_one_or_none()
