from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth ---

class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    name: str = ""


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    name: str
    created_at: datetime


class TokenOut(BaseModel):
    token: str
    user: UserOut


# --- projects ---

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    root_path: str


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ProjectOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    root_path: str
    status: str
    meta: dict
    created_at: datetime
    updated_at: datetime


class ProjectDetailOut(ProjectOut):
    stats: dict[str, Any] = {}


class IndexRequest(BaseModel):
    mode: str = "update"  # initial | update | reverify
    ai_limit: int | None = None  # переопределить бюджет ИИ-анализа
    auto_continue: bool = False  # продолжать бэклог анализа до конца автоматически
    retry_errors: bool = False  # повторить упавшие файлы в этом прогоне


# --- files ---

class ProjectFileOut(ORMModel):
    id: uuid.UUID
    rel_path: str
    sha256: str
    size: int
    kind: str
    analysis_status: str
    summary: str | None
    updated_at: datetime


class ChangeReportOut(ORMModel):
    id: uuid.UUID
    mode: str
    added: list
    modified: list
    deleted: list
    stats: dict
    created_at: datetime


# --- jobs ---

class JobOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    type: str
    status: str
    progress: float
    detail: str
    stats: dict
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


# --- chat ---

class ChatCreate(BaseModel):
    title: str = "Новый чат"
    model: str | None = None
    reasoning: str | None = None


class ChatUpdate(BaseModel):
    title: str | None = None
    model: str | None = None
    reasoning: str | None = None


class ChatOut(ORMModel):
    id: uuid.UUID
    title: str
    model: str
    reasoning: str
    created_at: datetime


class MessageIn(BaseModel):
    content: str = Field(min_length=1)


class MessageOut(ORMModel):
    id: uuid.UUID
    role: str
    content: str
    meta: dict
    created_at: datetime


# --- tasks ---

class PlanStep(BaseModel):
    text: str
    done: bool = False


def normalize_plan(plan: list | None) -> list[dict]:
    """Строки и объекты → [{"text", "done"}] (обратная совместимость)."""
    out: list[dict] = []
    for item in (plan or [])[:40]:
        if isinstance(item, dict) and item.get("text"):
            out.append({"text": str(item["text"])[:500], "done": bool(item.get("done"))})
        elif isinstance(item, str) and item.strip():
            out.append({"text": item.strip()[:500], "done": False})
    return out


class TaskCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    source: str = "manual"
    plan: list = []
    enrich: bool = False  # сразу отправить на RLM-проработку


class TaskUpdateIn(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    plan: list | None = None


class TaskDoneIn(BaseModel):
    report: str = Field(min_length=1)
    files: list[str] = []


class TasksEnrichIn(BaseModel):
    task_ids: list[uuid.UUID] | None = None  # None = все planned без проработки


class TaskOut(ORMModel):
    id: uuid.UUID
    title: str
    description: str
    status: str
    source: str
    plan: list[PlanStep]
    extra: dict
    report: str | None
    created_at: datetime
    updated_at: datetime
    done_at: datetime | None

    @field_validator("plan", mode="before")
    @classmethod
    def _norm_plan(cls, v: list | None) -> list[dict]:
        return normalize_plan(v)


# --- worklog ---

class WorkLogIn(BaseModel):
    description: str = Field(min_length=1)
    files: list[str] = []
    task_id: uuid.UUID | None = None


class WorkLogOut(ORMModel):
    id: uuid.UUID
    task_id: uuid.UUID | None
    description: str
    files: list
    synced: bool
    created_at: datetime


# --- decisions ---

class DecisionIn(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)


class DecisionUpdateIn(BaseModel):
    topic: str | None = None
    text: str | None = None


class DecisionOut(ORMModel):
    id: uuid.UUID
    topic: str
    text: str
    source: str
    created_at: datetime
    updated_at: datetime


# --- materials ---

class MaterialOut(ORMModel):
    id: uuid.UUID
    filename: str
    media_type: str
    size: int
    status: str
    summary: str | None
    error: str | None
    created_at: datetime
    processed_at: datetime | None


# --- rlm ---

class AskIn(BaseModel):
    question: str = Field(min_length=1)
    paths: list[str] | None = None


class AskOut(BaseModel):
    answer: str
    sub_queries: list[dict] = []
