"""Фейковый claude CLI для тестов: имитирует ответы по типу промпта."""

import json
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
    if "прорабатываешь короткую задачу в детальную" in prompt:
        return json.dumps(
            {
                "description": "Детальная проработка: обработчик в main.py не подключён. Нужно добавить onClick по аналогии с util.py.",
                "plan": [
                    {"text": "Посмотреть обработчик в main.py"},
                    {"text": "Подключить вызов по аналогии с src/util.py"},
                    {"text": "Проверить в браузере"},
                ],
                "files": ["main.py", "src/util.py"],
                "related_tasks": [
                    {"title": "Сделать фичу А", "relation": "overlaps", "note": "общие файлы"}
                ],
                "duplicate_of": None,
            },
            ensure_ascii=False,
        )
    return "Тестовый ответ ассистента."


def main() -> None:
    prompt = get_arg("-p") or ""
    fmt = get_arg("--output-format") or "text"
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
