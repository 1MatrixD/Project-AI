"""Системный диалог выбора каталога.

Сам диалог здесь не открывается: он модальный и ждёт человека, а в тестах его
некому закрыть. Проверяется то, что можно проверить без GUI — что скрипт для
PowerShell собирается корректно и путь с апострофом его не ломает.
"""

from __future__ import annotations

import base64

from app.routers.fs import _PICK_SCRIPT


def test_pick_script_escapes_quotes() -> None:
    script = _PICK_SCRIPT.format(initial="D:\\it's\\weird".replace("'", "''"))
    # апостроф удвоен — строка PowerShell не рвётся посередине
    assert "'D:\\it''s\\weird'" in script
    assert script.count("$dlg.SelectedPath = ") == 1


def test_pick_script_has_no_leftover_braces() -> None:
    """В шаблоне фигурные скобки PowerShell экранированы удвоением; если где-то
    забыть — .format() либо упадёт, либо оставит одинарную скобку не на месте."""
    script = _PICK_SCRIPT.format(initial="")
    assert "{{" not in script and "}}" not in script
    assert script.count("{") == script.count("}") > 0
    # первым делом ставится UTF-8: иначе кириллица в пути приедет в OEM-кодировке
    assert script.strip().startswith("[Console]::OutputEncoding")


def test_pick_script_is_valid_utf16_for_encoded_command() -> None:
    script = _PICK_SCRIPT.format(initial="C:\\Проекты")
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    assert base64.b64decode(encoded).decode("utf-16-le") == script
