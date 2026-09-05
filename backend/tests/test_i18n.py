"""Локализация: ошибки API — на языке Accept-Language, фон — на языке AI_LANGUAGE,
пометка языка в промптах не трогает фразы, по которым фейковый claude узнаёт промпт."""
from __future__ import annotations

import uuid

from app import i18n
from app.config import get_settings
from app.services import prompts
from app.services.claude_cli import _with_language


def test_accept_language_parsing():
    assert i18n.parse_accept_language("en-US,en;q=0.9,ru;q=0.8") == "en"
    assert i18n.parse_accept_language("ru-RU,ru;q=0.9,en;q=0.8") == "ru"
    assert i18n.parse_accept_language("de,fr;q=0.7") is None
    assert i18n.parse_accept_language(None) is None


def test_translation_follows_request_language():
    token = i18n.set_request_language("en")
    try:
        assert i18n._("Задача не найдена") == "Task not found"
        assert i18n._("Каталог не найден: {path}").format(path="x") == "Directory not found: x"
        # без перевода — исходник, ничего не падает
        assert i18n._("строка без перевода") == "строка без перевода"
        assert i18n.text("skill_workflow_body").startswith("# Workflow")
    finally:
        i18n.reset_request_language(token)
    # тесты идут с AI_LANGUAGE=ru: без языка запроса действует системный
    assert i18n._("Задача не найдена") == "Задача не найдена"
    assert i18n.text("skill_workflow_body").startswith("# Рабочий процесс")


def test_every_translation_keeps_placeholders():
    """Плейсхолдеры перевода обязаны совпадать с оригиналом — иначе .format() упадёт."""
    import re

    for ru, en in i18n.EN.items():
        assert set(re.findall(r"{\w+}", ru)) == set(re.findall(r"{\w+}", en)), ru


def test_prompt_language_note(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "ai_language", "en")
    localized = prompts.localized(prompts.FILE_ANALYSIS_PROMPT)
    assert "по-русски" not in localized and "in English" in localized
    # маркер, по которому фейковый claude узнаёт промпт анализа, не тронут
    assert "Проанализируй следующие файлы" in localized
    assert prompts.localized("Answer in Russian.") == "Answer in English."
    assert _with_language("SYS").endswith("in English.")

    monkeypatch.setattr(s, "ai_language", "ru")
    assert prompts.localized(prompts.FILE_ANALYSIS_PROMPT) == prompts.FILE_ANALYSIS_PROMPT
    assert _with_language("SYS") == "SYS"


async def test_api_errors_follow_accept_language(client):
    url = f"/api/projects/{uuid.uuid4()}"
    r = await client.get(url, headers={"Accept-Language": "en-US,en;q=0.9"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Not authenticated"

    r = await client.get(url, headers={"Accept-Language": "ru-RU,ru;q=0.9"})
    assert r.json()["detail"] == "Не авторизован"

    # без заголовка — системный язык (в тестах ru)
    r = await client.get(url)
    assert r.json()["detail"] == "Не авторизован"
