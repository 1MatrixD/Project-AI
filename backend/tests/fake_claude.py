"""Фейковый claude CLI для тестов: имитирует ответы по типу промпта."""

import json
import os
import re
import sys


def get_arg(flag: str) -> str | None:
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
    return None


def result_payload(text: str) -> dict:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": text,
        "session_id": "fake-session-123",
        "total_cost_usd": 0.001,
        "duration_ms": 42,
        "num_turns": 1,
    }


def answer_for(prompt: str) -> str:
    if "Проанализируй следующие файлы" in prompt:
        paths = re.findall(r"^- (.+?) \(", prompt, flags=re.MULTILINE)
        items = []
        for p in paths:
            items.append(
                {
                    "path": p,
                    "role": f"Тестовая роль {p}",
                    "summary": f"Файл {p} делает тестовые вещи.",
                    "kind": "code",
                    "entities": [
                        {"name": f"entity_{p.split('/')[-1].split('.')[0]}", "etype": "function", "summary": "тестовая функция"}
                    ],
                    "links": [],
                    "tags": ["тест"],
                }
            )
        return json.dumps(items, ensure_ascii=False)
    if "цельное представление о проекте" in prompt:
        return json.dumps(
            {
                "summary": "Тестовый проект для проверки пайплайна.",
                "project_kinds": ["backend"],
                "stack": ["Python"],
                "components": [
                    {"name": "Ядро", "kind": "module", "summary": "Основной модуль", "paths": []}
                ],
                "business_logic": [{"name": "Тест-фича", "summary": "Работает в тестах"}],
                "conventions": "Пишем тесты.",
                "how_to": {"run": "pytest"},
            },
            ensure_ascii=False,
        )
    if "Извлеки из материала" in prompt:
        return json.dumps(
            {
                "summary": "Обсудили две задачи.",
                "tasks": [
                    {"title": "Сделать фичу А", "description": "Описание фичи А из созвона", "plan": ["шаг 1", "шаг 2"]},
                    {"title": "Починить баг Б", "description": "Описание бага Б", "plan": []},
                ],
                "decisions": [
                    {"topic": "Роли в тесте", "text": "Решили: роль X упразднена, используем Y с доп. пермишенами."}
                ],
            },
            ensure_ascii=False,
        )
    if "Сгруппируй коммиты" in prompt:
        hashes = re.findall(r"^- ([0-9a-f]{6,12}) \[", prompt, flags=re.MULTILINE)
        groups = []
        if hashes:
            groups.append(
                {
                    "title": "Работа из git-истории",
                    "description": "Сводная работа по коммитам теста.",
                    "commits": hashes[:5],
                    "files": ["main.py"],
                    "matches_existing_task": None,
                }
            )
        if "Сделать фичу А" in prompt and hashes:
            groups.append(
                {
                    "title": "Закрытие фичи А по коммитам",
                    "description": "Коммиты подтверждают фичу А.",
                    "commits": hashes[:1],
                    "files": ["main.py"],
                    "matches_existing_task": "Сделать фичу А",
                    "coverage": "full",
                }
            )
        if "Частичная фича В" in prompt and hashes:
            groups.append(
                {
                    "title": "Частичный прогресс по фиче В",
                    "description": "Сделан только первый шаг.",
                    "commits": hashes[:1],
                    "files": ["main.py"],
                    "matches_existing_task": "Частичная фича В",
                    "coverage": "partial",
                    "completed_plan_steps": [1],
                }
            )
        return json.dumps({"groups": groups}, ensure_ascii=False)
    if "реализована ли эта задача" in prompt or "Проверь по кодовой базе" in prompt:
        implemented = "yes" if "Сделать фичу А" in prompt else "no"
        return json.dumps(
            {
                "implemented": implemented,
                "confidence": "high",
                "report": "Тестовая проверка.",
                "files": ["main.py"] if implemented == "yes" else [],
            },
            ensure_ascii=False,
        )
    if '"groups"' in prompt or "групп файлов для рекурсивного анализа" in prompt:
        return json.dumps({"groups": [{"focus": "тест", "paths": ["main.py"]}]}, ensure_ascii=False)
    if "Разбей задачу на подзадачи" in prompt:
        return json.dumps(
            {
                "plan_summary": "Сначала модель данных, затем API поверх неё, в конце экран на фронте.",
                "subtasks": [
                    {
                        "title": "Подзадача: модель и миграция",
                        "description": "Добавить модель в main.py",
                        "plan": ["описать модель", "миграция"],
                        "files": ["main.py"],
                        "depends_on": [],
                    },
                    {
                        "title": "Подзадача: API-эндпоинт",
                        "description": "Эндпоинт поверх модели",
                        "plan": ["хендлер", "тест"],
                        "files": ["main.py"],
                        "depends_on": [0],
                    },
                    {
                        "title": "Подзадача: экран на фронте",
                        "description": "Экран, дергающий API",
                        "plan": ["компонент"],
                        "files": ["src/util.py"],
                        "depends_on": [1, 99, 2],
                    },
                ],
            },
            ensure_ascii=False,
        )
    if "собираешь ДОСЬЕ по короткой задаче" in prompt:
        # Симуляция реального сбоя: модель дописала досье, но JSON синтаксически
        # битый. BAD_JSON=1 — всегда (проверка честного финала джобы),
        # BAD_JSON_ONCE_FILE — только первый вызов (проверка ретрая синтеза).
        broken = '```json\n{"description": "обрыв посреди'
        if os.environ.get("FAKE_CLAUDE_BAD_JSON") == "1":
            return broken
        once_flag = os.environ.get("FAKE_CLAUDE_BAD_JSON_ONCE_FILE")
        if once_flag and not os.path.exists(once_flag):
            open(once_flag, "w").close()
            return broken
        # Второй проход синтеза получает блок доисследования — значит вопросы закрыты.
        second_pass = "Доисследование:" in prompt
        unresolved = []
        if os.environ.get("FAKE_CLAUDE_UNRESOLVED") == "1" and not second_pass:
            unresolved = ["чем отдаётся ответ обработчика"]
        return json.dumps(
            {
                "description": "Детальная проработка: обработчик в main.py объявлен, но нигде не подключён; рабочий аналог живёт в src/util.py.",
                "reading": "Кнопка не реагирует, потому что обработчик не подключён; другое прочтение — подключён, но падает.",
                "hypothesis": {"text": "обработчик не подключён", "confidence": "high"},
                "where_to_look": [
                    {"path": "main.py", "why": "объявление обработчика: подключён ли он"},
                    {"path": "src/util.py", "why": "рабочий аналог подключения"},
                ],
                "reference": "src/util.py — тот же обработчик подключён и работает",
                "how_to_verify": [
                    {
                        "what": "клик по кнопке вызывает обработчик",
                        "how": "тестов рядом нет, проверка руками в браузере",
                    }
                ],
                # files сознательно не отдаём: досье без него должно взять пути
                # из where_to_look (фолбэк в task_enrich)
                "related_tasks": [
                    {"title": "Сделать фичу А", "relation": "overlaps", "note": "общие файлы"}
                ],
                "duplicate_of": None,
                "open_questions": [
                    {
                        "question": "Чинить обработчик или переносить логику в util.py?",
                        "options": ["поправить на месте — быстрее", "перенести — единая точка"],
                        "lean": "поправить на месте",
                    }
                ],
                "impact": [
                    {"what": "src/util.py", "why": "тот же обработчик используется оттуда"}
                ],
                "unresolved": unresolved,
            },
            ensure_ascii=False,
        )
    if "Назначенные тебе файлы" in prompt:
        # ветка просит углубления, только если ей это разрешили (блок про «НУЖНО УТОЧНИТЬ»)
        if os.environ.get("FAKE_CLAUDE_DEEP") == "1" and "НУЖНО УТОЧНИТЬ" in prompt:
            return (
                "Тестовый ответ ассистента.\n\n"
                "НУЖНО УТОЧНИТЬ:\n- чем именно отдаётся ответ обработчика\n"
            )
        return "Тестовый ответ ассистента."
    return "Тестовый ответ ассистента."


def main() -> None:
    prompt = get_arg("-p") or ""
    fmt = get_arg("--output-format") or "text"

    # Управляемый сбой RLM-синтеза: так проверяется, что выводы под-агентов
    # не теряются, когда финальная сводка не удалась.
    if os.environ.get("FAKE_CLAUDE_FAIL_SYNTH") == "1" and "Синтезируй один цельный" in prompt:
        sys.stdout.write(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "error_max_turns",
                    "is_error": True,
                    "result": "error_max_turns",
                    "session_id": "fake-session-123",
                    "total_cost_usd": 0.0,
                    "duration_ms": 5,
                    "num_turns": 1,
                },
                ensure_ascii=False,
            )
        )
        sys.exit(0)

    text = answer_for(prompt)

    if fmt == "stream-json":
        events = [
            {"type": "system", "subtype": "init", "session_id": "fake-session-123", "model": get_arg("--model") or "opus"},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "mcp__projectai__graph_search", "input": {"query": "тест"}},
                    ]
                },
            },
            {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}},
            result_payload(text),
        ]
        for e in events:
            sys.stdout.write(json.dumps(e, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    else:
        sys.stdout.write(json.dumps(result_payload(text), ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
