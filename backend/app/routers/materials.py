from __future__ import annotations

import uuid

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..deps import get_project
from ..jobs_runner import runner
from ..models import Material, Project
from ..schemas import MaterialOut

router = APIRouter(prefix="/projects/{project_id}/materials", tags=["materials"])

MAX_UPLOAD = 2 * 1024 * 1024 * 1024  # 2 ГБ (видео созвонов)

_INVALID_FS_CHARS = '<>:"/\\|?*'


def sanitize_filename(raw: str | None) -> str:
    name = (raw or "file").replace("\\", "/").split("/")[-1]
    if name.startswith("=?") and name.endswith("?="):
        # RFC 2047 (так кодируют не-ASCII имена некоторые клиенты)
        try:
            from email.header import decode_header

            decoded, charset = decode_header(name)[0]
            if isinstance(decoded, bytes):
                name = decoded.decode(charset or "utf-8", errors="replace")
        except Exception:
            pass
    name = "".join("_" if c in _INVALID_FS_CHARS or ord(c) < 32 else c for c in name)
    return (name.strip() or "file")[:400]


@router.get("", response_model=list[MaterialOut])
async def list_materials(
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> list[MaterialOut]:
    res = await session.execute(
        select(Material)
        .where(Material.project_id == project.id)
        .order_by(desc(Material.created_at))
    )
    return [MaterialOut.model_validate(m) for m in res.scalars()]


@router.post("", response_model=MaterialOut, status_code=201)
async def upload_material(
    file: UploadFile,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
    extract_tasks: bool = True,
) -> MaterialOut:
    s = get_settings()
    filename = sanitize_filename(file.filename)
    material = Material(
        project_id=project.id,
        filename=filename,
        stored_path="",
        media_type=file.content_type or "application/octet-stream",
    )
    session.add(material)
    await session.flush()

    d = s.data_path / "materials" / str(project.id)
    d.mkdir(parents=True, exist_ok=True)
    stored = d / f"{material.id}_{filename}"

    size = 0
    async with aiofiles.open(stored, "wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD:
                await out.close()
                stored.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Файл больше 2 ГБ")
            await out.write(chunk)

    material.stored_path = str(stored)
    material.size = size
    await session.commit()
    await session.refresh(material)

    await runner.submit(
        project.id,
        "process_material",
        {"material_id": str(material.id), "extract_tasks": extract_tasks},
    )
    return MaterialOut.model_validate(material)


@router.get("/{material_id}/text")
async def material_text(
    material_id: uuid.UUID,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
    offset: int = 0,
    limit_chars: int = 20000,
) -> dict:
    material = await session.get(Material, material_id)
    if material is None or material.project_id != project.id:
        raise HTTPException(status_code=404, detail="Материал не найден")
    if not material.text_path:
        raise HTTPException(status_code=409, detail=f"Текст ещё не готов (статус: {material.status})")
    try:
        async with aiofiles.open(material.text_path, "r", encoding="utf-8") as f:
            text = await f.read()
    except OSError:
        raise HTTPException(status_code=500, detail="Файл текста недоступен")
    chunk = text[offset : offset + min(limit_chars, 100_000)]
    return {
        "text": chunk,
        "offset": offset,
        "total_chars": len(text),
        "summary": material.summary,
    }


@router.post("/{material_id}/reprocess", response_model=MaterialOut)
async def reprocess_material(
    material_id: uuid.UUID,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
    extract_tasks: bool = True,
) -> MaterialOut:
    material = await session.get(Material, material_id)
    if material is None or material.project_id != project.id:
        raise HTTPException(status_code=404, detail="Материал не найден")
    await runner.submit(
        project.id,
        "process_material",
        {"material_id": str(material.id), "extract_tasks": extract_tasks},
    )
    material.status = "processing"
    await session.commit()
    await session.refresh(material)
    return MaterialOut.model_validate(material)


@router.delete("/{material_id}", status_code=204)
async def delete_material(
    material_id: uuid.UUID,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_session),
) -> None:
    material = await session.get(Material, material_id)
    if material is None or material.project_id != project.id:
        raise HTTPException(status_code=404, detail="Материал не найден")
    from pathlib import Path

    for p in (material.stored_path, material.text_path):
        if p:
            Path(p).unlink(missing_ok=True)
    await session.delete(material)
    await session.commit()
