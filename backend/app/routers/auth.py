from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models import User
from ..schemas import LoginIn, RegisterIn, TokenOut, UserOut
from ..security import create_user_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut)
async def register(data: RegisterIn, session: AsyncSession = Depends(get_session)) -> TokenOut:
    email = data.email.lower()
    exists = await session.execute(select(User).where(func.lower(User.email) == email))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Пользователь с таким email уже есть")
    user = User(email=email, password_hash=hash_password(data.password), name=data.name.strip())
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return TokenOut(token=create_user_token(user.id), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
async def login(data: LoginIn, session: AsyncSession = Depends(get_session)) -> TokenOut:
    email = data.email.lower()
    res = await session.execute(select(User).where(func.lower(User.email) == email))
    user = res.scalar_one_or_none()
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    return TokenOut(token=create_user_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
