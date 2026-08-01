from __future__ import annotations

import os
import string
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_current_user

router = APIRouter(prefix="/fs", tags=["fs"], dependencies=[Depends(get_current_user)])

HIDDEN_PREFIXES = (".", "$", "~")
SKIP_NAMES = {"System Volume Information", "Recovery", "PerfLogs"}


@router.get("/drives")
async def drives() -> list[str]:
    if os.name != "nt":
        return ["/"]
    return [f"{d}:\\" for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]


@router.get("/list")
async def list_dir(path: str) -> dict:
    p = Path(path)
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Каталог не существует")
    dirs = []
    try:
        for child in sorted(p.iterdir(), key=lambda c: c.name.lower()):
            try:
                if not child.is_dir():
                    continue
            except OSError:
                continue
            name = child.name
            if name.startswith(HIDDEN_PREFIXES) or name in SKIP_NAMES:
                continue
            dirs.append({"name": name, "path": str(child)})
    except PermissionError:
        raise HTTPException(status_code=403, detail="Нет доступа к каталогу")
    parent = str(p.parent) if p.parent != p else None
    return {"path": str(p), "parent": parent, "dirs": dirs[:500]}
