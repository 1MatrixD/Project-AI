from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
import string
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_current_user

log = logging.getLogger("projectai.api.fs")

router = APIRouter(prefix="/fs", tags=["fs"], dependencies=[Depends(get_current_user)])

HIDDEN_PREFIXES = (".", "$", "~")
SKIP_NAMES = {"System Volume Information", "Recovery", "PerfLogs"}

#: диалог модальный и ждёт человека — но не бесконечно, иначе висящий процесс
#: PowerShell переживёт вкладку, из которой его открыли
PICK_TIMEOUT_SEC = 300
#: два диалога одновременно означали бы две системные модалки поверх друг друга
_pick_lock = asyncio.Lock()


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


# --- системный диалог выбора каталога ---------------------------------------
#
# Приложение — обычное браузерное SPA, и из JS настоящий диалог Windows не
# вызвать: File System Access API и <input webkitdirectory> абсолютного пути не
# отдают, а для индексации нужен именно он. Зато бэкенд стоит на той же машине
# (на этом допущении построен весь /fs/*), поэтому диалог открывает он —
# средствами PowerShell, а браузер получает уже готовый путь.

_PICK_SCRIPT = """
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$dlg = New-Object System.Windows.Forms.FolderBrowserDialog
$dlg.Description = 'Каталог проекта'
$dlg.ShowNewFolderButton = $false
if ('{initial}' -ne '') {{ $dlg.SelectedPath = '{initial}' }}
# Диалог модальный по отношению к владельцу: без TopMost-владельца он открылся бы
# позади окна браузера, и выглядело бы это как зависший запрос.
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.Size = New-Object System.Drawing.Size(1, 1)
$owner.StartPosition = 'CenterScreen'
$null = $owner.Show()
$owner.Activate()
try {{
    if ($dlg.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {{
        [Console]::Out.Write($dlg.SelectedPath)
    }}
}} finally {{
    $owner.Close()
    $owner.Dispose()
}}
"""


def _powershell_bin() -> str | None:
    # pwsh 7 рисует современный диалог проводника, powershell 5.1 — старое дерево
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


@router.post("/pick-dir")
async def pick_dir(body: dict | None = None) -> dict:
    """Открыть системный диалог выбора каталога НА МАШИНЕ С БЭКЕНДОМ.

    Возвращает {"path": str|None, "cancelled": bool}. 501 — если системного
    диалога здесь нет (не Windows, нет PowerShell): фронт откатывается на
    свой DirPicker.
    """
    if os.name != "nt":
        raise HTTPException(status_code=501, detail="Системный диалог доступен только на Windows")
    ps = _powershell_bin()
    if ps is None:
        raise HTTPException(status_code=501, detail="PowerShell не найден")
    if _pick_lock.locked():
        raise HTTPException(status_code=409, detail="Диалог выбора каталога уже открыт")

    initial = str((body or {}).get("initial") or "").strip()
    if not Path(initial).is_dir():
        initial = ""
    script = _PICK_SCRIPT.format(initial=initial.replace("'", "''"))
    # -EncodedCommand снимает вопрос экранирования и кодировки: скрипт едет
    # UTF-16LE в base64, минуя кавычки командной строки
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")

    async with _pick_lock:
        proc = await asyncio.create_subprocess_exec(
            ps, "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=PICK_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            proc.kill()
            raise HTTPException(status_code=504, detail="Диалог выбора каталога не закрыли вовремя")

    if proc.returncode != 0:
        detail = err.decode("utf-8", "replace").strip()[:300]
        log.warning("Системный диалог не открылся (%s): %s", ps, detail)
        raise HTTPException(status_code=501, detail=f"Системный диалог недоступен: {detail}")

    path = out.decode("utf-8", "replace").strip()
    if not path:
        return {"path": None, "cancelled": True}
    if not Path(path).is_dir():
        raise HTTPException(status_code=400, detail=f"Каталог не найден: {path}")
    return {"path": str(Path(path).resolve()), "cancelled": False}
