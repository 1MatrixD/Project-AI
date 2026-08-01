from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session, get_sessionmaker
from ..deps import get_project
from ..models import Chat, Message, Project
from ..schemas import ChatCreate, ChatOut, ChatUpdate, MessageIn, MessageOut
from ..services import claude_cli, graphdb, plugin_gen
from ..services.prompts import build_chat_system_prompt

log = logging.getLogger("projectai.chat")

router = APIRouter(prefix="/projects/{project_id}/chats", tags=["chat"])

ALLOWED_MODELS = {"opus", "sonnet", "haiku"}
ALLOWED_REASONING = {"none", "low", "medium", "high"}

CHAT_TOOLS = [
    "Read", "Grep", "Glob", "LS",
    "mcp__projectai",  # все инструменты MCP-сервера проекта
    "mcp__projectai__*",
]


async def _get_chat(session: AsyncSession, project: Project, chat_id: uuid.UUID) -> Chat:
    chat = await session.get(Chat, chat_id)
    if chat is None or chat.project_id != project.id:
        raise HTTPException(status_code=404, detail="Чат не найден")
    return chat


@router.get("", response_model=list[ChatOut])
async def list_chats(
    project: Project = Depends(get_project), session: AsyncSession = Depends(get_session)
) -> list[ChatOut]:
    res = await session.execute(
        select(Chat).where(Chat.project_id == project.id).order_by(desc(Chat.created_at))
    )
    return [ChatOut.model_validate(c) for c in res.scalars()]


@router.post("", response_model=ChatOut, status_code=201)
async def create_chat(
    data: ChatCreate,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> ChatOut:
    s = get_settings()
    model = data.model if data.model in ALLOWED_MODELS else s.chat_default_model
    reasoning = data.reasoning if data.reasoning in ALLOWED_REASONING else s.chat_default_reasoning
    chat = Chat(project_id=project.id, title=data.title[:200], model=model, reasoning=reasoning)
    session.add(chat)
    await session.commit()
    await session.refresh(chat)
    return ChatOut.model_validate(chat)


@router.patch("/{chat_id}", response_model=ChatOut)
async def update_chat(
    chat_id: uuid.UUID,
    data: ChatUpdate,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> ChatOut:
    chat = await _get_chat(session, project, chat_id)
    if data.title is not None:
        chat.title = data.title[:200]
    if data.model is not None:
        if data.model not in ALLOWED_MODELS:
            raise HTTPException(status_code=400, detail=f"Модель: {', '.join(sorted(ALLOWED_MODELS))}")
        chat.model = data.model
    if data.reasoning is not None:
        if data.reasoning not in ALLOWED_REASONING:
            raise HTTPException(status_code=400, detail=f"Reasoning: {', '.join(sorted(ALLOWED_REASONING))}")
        chat.reasoning = data.reasoning
    await session.commit()
    await session.refresh(chat)
    return ChatOut.model_validate(chat)


@router.delete("/{chat_id}", status_code=204)
async def delete_chat(
    chat_id: uuid.UUID,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> None:
    chat = await _get_chat(session, project, chat_id)
    await session.delete(chat)
    await session.commit()


@router.get("/{chat_id}/messages", response_model=list[MessageOut])
async def list_messages(
    chat_id: uuid.UUID,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> list[MessageOut]:
    await _get_chat(session, project, chat_id)
    res = await session.execute(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
    )
    return [MessageOut.model_validate(m) for m in res.scalars()]


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _tool_preview(tool_input: object) -> str:
    try:
        text = json.dumps(tool_input, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(tool_input)
    return text[:200]


@router.post("/{chat_id}/messages")
async def send_message(
    chat_id: uuid.UUID,
    data: MessageIn,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    chat = await _get_chat(session, project, chat_id)

    user_msg = Message(chat_id=chat.id, role="user", content=data.content)
    session.add(user_msg)
    if chat.title == "Новый чат":
        chat.title = data.content.strip().replace("\n", " ")[:80]
    await session.commit()

    chat_id_val = chat.id
    session_id = chat.claude_session_id
    model, reasoning = chat.model, chat.reasoning
    project_name, root_path = project.name, project.root_path
    pid = project.id

    async def event_stream():
        maker = get_sessionmaker()
        text_parts: list[str] = []
        meta: dict = {"model": model, "reasoning": reasoning}
        new_session_id: str | None = None
        error: str | None = None

        try:
            try:
                graph_context = await graphdb.get_project_summary_context(str(pid), 5000)
            except Exception:
                graph_context = "(карта знаний недоступна)"
            try:
                mcp_config = await plugin_gen.get_chat_mcp_config(pid)
            except Exception as e:
                log.warning("MCP-конфиг не собрался: %s", e)
                mcp_config = None

            system = build_chat_system_prompt(project_name, root_path, graph_context)
            yield _sse({"type": "start"})

            async for event in claude_cli.stream_prompt(
                data.content,
                cwd=root_path,
                system=system,
                tools=CHAT_TOOLS,
                model=model,
                reasoning=reasoning,
                session_id=session_id,
                mcp_config=mcp_config,
                timeout=900,
            ):
                etype = event.get("type")
                if etype == "system" and event.get("subtype") == "init":
                    new_session_id = event.get("session_id") or new_session_id
                elif etype == "assistant":
                    for block in (event.get("message") or {}).get("content", []):
                        btype = block.get("type")
                        if btype == "text" and block.get("text"):
                            text_parts.append(block["text"])
                            yield _sse({"type": "delta", "text": block["text"]})
                        elif btype == "tool_use":
                            yield _sse(
                                {
                                    "type": "tool",
                                    "name": block.get("name", ""),
                                    "input": _tool_preview(block.get("input")),
                                }
                            )
                elif etype == "result":
                    meta.update(
                        {
                            "cost_usd": event.get("total_cost_usd"),
                            "duration_ms": event.get("duration_ms"),
                            "num_turns": event.get("num_turns"),
                        }
                    )
                    new_session_id = event.get("session_id") or new_session_id
                    if event.get("is_error"):
                        error = str(event.get("result", "Ошибка ИИ"))[:2000]
                elif etype == "process_error":
                    error = f"Процесс claude: код {event.get('code')}. {event.get('stderr', '')}"[:2000]
        except Exception as e:
            log.exception("Стрим чата упал")
            error = str(e)[:2000]
        finally:
            content = "\n\n".join(t for t in text_parts if t.strip()).strip()
            if error and not content:
                content = f"⚠️ {error}"
            if error:
                meta["error"] = error
            if content:
                try:
                    async with maker() as s2:
                        msg = Message(chat_id=chat_id_val, role="assistant", content=content, meta=meta)
                        s2.add(msg)
                        if new_session_id:
                            await s2.execute(
                                update(Chat)
                                .where(Chat.id == chat_id_val)
                                .values(claude_session_id=new_session_id)
                            )
                        await s2.commit()
                except Exception:
                    log.exception("Не сохранилось сообщение ассистента")
        if error:
            yield _sse({"type": "error", "detail": error})
        yield _sse({"type": "done", "meta": meta})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
