"""Язык строк, которые видит пользователь: ошибки API, ход фоновых работ,
заголовки экспорта и сгенерированных скиллов плагина.

Стиль gettext: ключ — русская строка как она написана в коде. Исходники остаются
читаемыми, а русский автоматически служит запасным вариантом, если перевода нет.

Откуда берётся язык:
- HTTP-запрос — из заголовка Accept-Language (middleware в main.py); фронтенд
  шлёт туда язык интерфейса, поэтому ошибки приходят на языке экрана;
- фоновые работы и генерация артефактов (плагин, отчёты) — из настройки
  AI_LANGUAGE: у них нет запроса, а язык должен совпадать с языком, на котором
  ИИ пишет содержимое карты знаний.
"""
from __future__ import annotations

from contextvars import ContextVar, Token

from .config import get_settings

SUPPORTED = ("ru", "en")
DEFAULT = "en"

_request_lang: ContextVar[str | None] = ContextVar("projectai_request_lang", default=None)


def normalize(value: str | None) -> str | None:
    """'en-US' → 'en'; неизвестные и пустые значения → None."""
    if not value:
        return None
    base = value.strip().lower().split("-")[0]
    return base if base in SUPPORTED else None


def parse_accept_language(header: str | None) -> str | None:
    """Первый поддерживаемый язык из Accept-Language (порядок = предпочтение)."""
    if not header:
        return None
    for part in header.split(","):
        lang = normalize(part.split(";")[0])
        if lang:
            return lang
    return None


def set_request_language(lang: str | None) -> Token:
    return _request_lang.set(lang)


def reset_request_language(token: Token) -> None:
    _request_lang.reset(token)


def system_language() -> str:
    """Язык ИИ-контента и фоновых работ (AI_LANGUAGE)."""
    return normalize(get_settings().ai_language) or DEFAULT


def current_language() -> str:
    return _request_lang.get() or system_language()


def _(text: str) -> str:
    """Перевод строки для текущего языка; без перевода возвращает исходник.

    Строки с подстановками держат {плейсхолдеры} и форматируются ПОСЛЕ перевода:
    `i18n._("Каталог не найден: {path}").format(path=p)`.

    Вызывается через модуль (`i18n._`), а не голым `_`: в сервисах `_` — привычное
    имя для выброшенных значений (`obj, _ = ...`), и локальная переменная затеняла
    бы функцию в той же области видимости.
    """
    if current_language() == "ru":
        return text
    return EN.get(text, text)


def text(key: str) -> str:
    """Длинные тексты (тела скиллов плагина): обе версии лежат в TEXTS под ключом."""
    lang = current_language()
    return TEXTS.get(lang, TEXTS["ru"]).get(key) or TEXTS["ru"][key]


class LanguageMiddleware:
    """Чистый ASGI-middleware: язык запроса из Accept-Language.

    Не BaseHTTPMiddleware — тот оборачивает тело ответа и мешает SSE-стримам
    (события фоновых работ и чата идут через StreamingResponse)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        header = None
        for name, value in scope.get("headers") or []:
            if name == b"accept-language":
                header = value.decode("latin-1", errors="replace")
                break
        token = set_request_language(parse_accept_language(header))
        try:
            await self.app(scope, receive, send)
        finally:
            reset_request_language(token)


EN: dict[str, str] = {
    # --- авторизация и доступ ---
    "Не авторизован": "Not authenticated",
    "Соглашение не найдено": "Decision not found",
    "Claude Code CLI не найден ({bin}). Установи и авторизуй claude.": "Claude Code CLI not found ({bin}). Install and log in to claude.",
    "Недействительный токен": "Invalid token",
    "Пользователь не найден": "User not found",
    "Проект не найден": "Project not found",
    "Токен не для этого проекта": "The token was issued for a different project",
    "Нет доступа к проекту": "Access to the project is denied",
    "Пользователь с таким email уже есть": "A user with this email already exists",
    "Неверный email или пароль": "Invalid email or password",
    # --- проекты, файлы, граф ---
    "Каталог не найден: {path}": "Directory not found: {path}",
    "Каталог не существует": "Directory does not exist",
    "Нет доступа к каталогу": "Access to the directory is denied",
    "Системный диалог доступен только на Windows": "The native folder dialog is only available on Windows",
    "PowerShell не найден": "PowerShell not found",
    "Диалог выбора каталога уже открыт": "A folder dialog is already open",
    "Диалог выбора каталога не закрыли вовремя": "The folder dialog was not closed in time",
    "Системный диалог недоступен: {detail}": "Native dialog unavailable: {detail}",
    "Идёт индексация — дубль получился бы половинчатым": "Indexing is in progress — a duplicate would be incomplete",
    "Индексация уже идёт": "Indexing is already running",
    "Наблюдение не запустилось: {error}": "Could not start watching: {error}",
    "Этот каталог уже в проекте": "This directory is already part of the project",
    "Каталог «{alias}» не найден в проекте": "Directory “{alias}” not found in the project",
    "Поиск по графу недоступен: {error}": "Graph search unavailable: {error}",
    "Компонент «{name}» не найден в карте знаний": "Component “{name}” not found in the knowledge map",
    "Файл «{path}» не найден в карте знаний": "File “{path}” not found in the knowledge map",
    "Пустой запрос": "Empty query",
    "Ошибка Cypher: {error}": "Cypher error: {error}",
    "Запрос отклонён: запись/административная операция ({keyword})": "Query rejected: write or administrative operation ({keyword})",
    "RLM-запрос не удался: {error}": "RLM query failed: {error}",
    "Импорт git уже идёт": "Git import is already running",
    "Не выбран ни один репозиторий": "No repository selected",
    "Файл не найден": "File not found",
    "Файл не читается как текст": "File is not readable as text",
    "Каталог проекта не найден: {path}": "Project directory not found: {path}",
    "{path} — не читается как JSON: {error}": "{path} is not valid JSON: {error}",
    "{path} — ожидался объект JSON": "{path}: expected a JSON object",
    "{base} — копия": "{base} — copy",
    "{base} — копия {n}": "{base} — copy {n}",
    # --- задачи и фоновые работы ---
    "Задача не найдена": "Task not found",
    "Фоновая задача не найдена": "Background job not found",
    "Фоновая задача уже завершена": "Background job already finished",
    "Статус: {options}": "Status must be one of: {options}",
    "Неверный статус": "Invalid status",
    "Проверка уже идёт": "Verification is already running",
    "Проработка уже идёт": "Briefing is already running",
    "Планирование уже идёт": "Planning is already running",
    "Задача «{title}»: {report}": "Task “{title}”: {report}",
    "Чат не найден": "Chat not found",
    "Модель: {options}": "Model must be one of: {options}",
    "Reasoning: {options}": "Reasoning must be one of: {options}",
    "Прервано перезапуском сервера": "Interrupted by a server restart",
    "Отменено пользователем": "Cancelled by the user",
    "Отменяется…": "Cancelling…",
    # --- материалы ---
    "Материал для уточнения не найден": "The material to clarify was not found",
    "Файл больше 2 ГБ": "File is larger than 2 GB",
    "Материал не найден": "Material not found",
    "Текст ещё не готов (статус: {status})": "Text is not ready yet (status: {status})",
    "Файл текста недоступен": "Text file unavailable",
    "Материал или проект не найден": "Material or project not found",
    "Транскрибация (whisper)": "Transcription (whisper)",
    "Извлечение текста": "Extracting text",
    "Пустой текст после обработки": "Empty text after processing",
    "ИИ: выжимка и извлечение задач": "AI: summary and task extraction",
    "Ожидался JSON-объект с summary/tasks": "Expected a JSON object with summary/tasks",
    "faster-whisper не установлен: {error}": "faster-whisper is not installed: {error}",
    "Не удалось загрузить модель whisper: {error}": "Could not load the whisper model: {error}",
    "Транскрибация не удалась: {error}": "Transcription failed: {error}",
    "Не удалось определить кодировку": "Could not detect the text encoding",
    "PDF не содержит извлекаемого текста (возможно, скан — нужен OCR)": "The PDF contains no extractable text (probably a scan — OCR needed)",
    "Документ пуст": "The document is empty",
    "## Лист: {title}": "## Sheet: {title}",
    "Формат .doc (старый Word) не поддерживается — сохрани как .docx": "The legacy .doc format is not supported — save it as .docx",
    "Это аудио/видео — используется транскрибация, не извлечение текста": "This is audio/video — it is transcribed, not text-extracted",
    "Неподдерживаемый формат: {ext}": "Unsupported format: {ext}",
    # --- индексация ---
    "Сканирование каталогов": "Scanning directories",
    "Обновление реестра файлов": "Updating the file registry",
    "Синхронизация структуры в граф": "Syncing structure into the graph",
    "ИИ-анализ файлов": "AI file analysis",
    "ИИ-анализ файлов: батч {done}/{total}": "AI file analysis: batch {done}/{total}",
    "Синтез обзора проекта": "Synthesizing the project overview",
    "байт": "bytes",
    "Проверено задач: {done}/{total}": "Tasks checked: {done}/{total}",
    "[ИИ-проверка] Реализовано. {report}\nФайлы: {files}": "[AI check] Implemented. {report}\nFiles: {files}",
    "[ИИ-проверка] Частично реализовано. {report}\nФайлы: {files}": "[AI check] Partially implemented. {report}\nFiles: {files}",
    "[ИИ-проверка] Не найдено в коде. {report}": "[AI check] Not found in the code. {report}",
    # --- RLM и проработка ---
    "читаю файлы: {count}": "reading files: {count}",
    "план не построен — отвечает один агент": "no plan built — a single agent answers",
    "план готов, групп файлов: {count}": "plan ready, file groups: {count}",
    "углубляюсь на уровень {level}: вопросов — {count}": "going deeper to level {level}: {count} question(s)",
    "под-агенты: {done}/{total} — {focus}": "sub-agents: {done}/{total} — {focus}",
    "свожу ответы под-агентов": "merging sub-agent answers",
    "исследование — {detail}": "investigation — {detail}",
    "исследование — выбираю файлы по карте знаний": "investigation — choosing files from the knowledge map",
    "исследование готово, файлов: {count}": "investigation done, files: {count}",
    "исследование не удалось — опираюсь на карту знаний": "investigation failed — relying on the knowledge map",
    "собираю досье: где смотреть, нюансы, как проверить": "assembling the brief: where to look, pitfalls, how to verify",
    "доисследование: вопросов без ответа — {count}": "follow-up investigation: {count} unanswered question(s)",
    "доисследование — {detail}": "follow-up — {detail}",
    "пересобираю описание с учётом доисследования": "rebuilding the description with the follow-up findings",
    "сохраняю досье и связи с файлами": "saving the brief and file links",
    "RLM-проработка, задач: {count}": "RLM briefing, tasks: {count}",
    "ошибка: {error}": "error: {error}",
    "проработана": "briefed",
    "проработано {done} из {total}, с ошибкой: {errors} — карточки без досье отправь на проработку ещё раз": "{done} of {total} briefed, {errors} failed — send the cards without a brief for briefing again",
    "Синтез не выполнялся": "Synthesis did not run",
    "Ожидался JSON-объект проработки": "Expected a JSON object with the brief",
    # --- планировщик ---
    "Планировщик: исследование «{title}»": "Planner: investigating “{title}”",
    "Планировщик: декомпозиция на подзадачи": "Planner: decomposing into subtasks",
    "Планировщик: создаю подзадачи ({count})": "Planner: creating subtasks ({count})",
    "Ожидался JSON-объект с подзадачами": "Expected a JSON object with subtasks",
    "Планировщик не вернул ни одной подзадачи": "The planner returned no subtasks",
    # --- git-импорт ---
    "Поиск git-репозиториев": "Looking for git repositories",
    "Импорт git: {repo}": "Git import: {repo}",
    "корень": "root",
    "[git-импорт] Частично выполнено коммитами ({repo}): {commits}. Шаги плана: {steps}.\n{description}": "[git import] Partially done by commits ({repo}): {commits}. Plan steps: {steps}.\n{description}",
    "[git-импорт] Подтверждено коммитами ({repo}): {commits}.\n{description}": "[git import] Confirmed by commits ({repo}): {commits}.\n{description}",
    "[git-импорт] Коммиты ({repo}): {commits}": "[git import] Commits ({repo}): {commits}",
    # --- claude cli ---
    "Не удалось запустить claude: {error}": "Could not start claude: {error}",
    "claude завершился с кодом {code}: {stderr}": "claude exited with code {code}: {stderr}",
    "Невалидный JSON от claude (код {code}): {out} / stderr: {stderr}": "Invalid JSON from claude (code {code}): {out} / stderr: {stderr}",
    "claude вернул ошибку: {detail} (subtype={subtype}, stderr={stderr})": "claude returned an error: {detail} (subtype={subtype}, stderr={stderr})",
    "без деталей": "no details",
    # --- группы MCP-инструментов (вкладка «Плагин») ---
    "Знания: граф, обзор, компоненты, файлы": "Knowledge: graph, overview, components, files",
    "Материалы: ТЗ, документы, транскрипты созвонов": "Materials: specs, documents, call transcripts",
    "Задачи: канбан, отчёты, worklog": "Tasks: kanban, reports, work log",
    "Соглашения проекта": "Project decisions",
    "RLM-запросы по кодовой базе": "RLM queries over the codebase",
    "Технические: реиндексация, git-импорт": "Technical: re-indexing, git import",
    # --- описания MCP-инструментов (вкладка «Плагин») ---
    "Обзор проекта: описание, стек, компоненты, статистика карты знаний": "Project overview: description, stack, components, knowledge map statistics",
    "Полнотекстовый поиск по карте знаний (файлы, сущности, компоненты, документы, задачи)": "Hybrid search over the knowledge map (files, entities, components, documents, tasks)",
    "Read-only Cypher-запрос к графу Neo4j": "Read-only Cypher query against the Neo4j graph",
    "Реестр файлов проекта с ролями из ИИ-анализа": "Project file registry with roles from the AI analysis",
    "Материалы: транскрипты созвонов, ТЗ, документы": "Materials: call transcripts, specs, documents",
    "Чтение текста материала (транскрипта/документа)": "Read the text of a material (transcript/document)",
    "Детали компонента/сервиса: за что отвечает, ключевые файлы с ролями": "Component/service details: responsibilities, key files with roles",
    "Досье файла: роль, сущности, связи, задачи и работы по нему": "File dossier: role, entities, relations, related tasks and work",
    "Соглашения проекта: актуальные решения и смены подходов": "Project decisions: current decisions and changes of approach",
    "Зафиксировать решение/смену подхода (обновляет совпадающую тему)": "Record a decision or change of approach (updates a matching topic)",
    "Импорт истории git (вложенные репо) в канбан выполненными работами": "Import git history (nested repos included) into the kanban as completed work",
    "Рекурсивный анализ кодовой базы (RLM): под-агенты читают файлы и возвращают ответ": "Recursive codebase analysis (RLM): sub-agents read the files and return an answer",
    "Канбан-доска задач проекта": "Project kanban board",
    "Задача целиком: досье разбора, файлы, история работ": "Full task: brief, files, work history",
    "Создать задачу в канбане (enrich=true — сразу на RLM-разбор)": "Create a kanban task (enrich=true sends it straight to RLM briefing)",
    "Улучшить/уточнить задачу (название, описание, план)": "Refine a task (title, description, plan)",
    "Переместить задачу между колонками": "Move a task between columns",
    "Пометить выполненной с отчётом → суб-агент обновит карту знаний": "Mark as done with a report → picked up by the next index update",
    "RLM-проработка: короткая задача → досье (где смотреть, нюансы, как проверить)": "RLM briefing: a short task → a brief (where to look, pitfalls, how to verify)",
    "Зафиксировать сделанную работу → суб-агент обновит карту знаний": "Log completed work → picked up by the next index update",
    "Запустить обновление индекса (update/reverify)": "Start an index update (update/reverify)",
    # --- экспорт карты знаний ---
    "Запланировано": "Planned",
    "В работе": "In progress",
    "Ревью": "Review",
    "Готово": "Done",
    "Отменено": "Cancelled",
    "# Карта знаний: {name}": "# Knowledge map: {name}",
    "> Экспортировано {now} · файлов: {files}, проанализировано ИИ: {analyzed}": "> Exported {now} · files: {files}, analyzed by AI: {analyzed}",
    "> Каталог: `{path}`": "> Directory: `{path}`",
    "> Каталог «{alias}/»: `{path}`": "> Directory “{alias}/”: `{path}`",
    "## Обзор": "## Overview",
    "**Тип:** ": "**Type:** ",
    "**Стек:** ": "**Stack:** ",
    "## Компоненты": "## Components",
    "Ключевые файлы: ": "Key files: ",
    "## Бизнес-логика": "## Business logic",
    "## Конвенции кода": "## Code conventions",
    "## Как запускать": "## How to run",
    "## Соглашения проекта": "## Project decisions",
    "Актуальные решения — «как принято сейчас» (не баги, а осознанный выбор):": "Current decisions — “how things are done now” (deliberate choices, not bugs):",
    "## Задачи": "## Tasks",
    " _(план {done}/{total})_": " _(plan {done}/{total})_",
    "## Материалы": "## Materials",
    "## Файлы": "## Files",
    "### корень": "### root",
    # --- плагин Claude Code: манифест и скиллы ---
    "Знания и инструменты проекта «{name}» (Проекты ИИ)": "Knowledge and tools of the “{name}” project (Project AI)",
    "Проекты ИИ": "Project AI",
    "# Архитектура проекта «{name}»": "# Architecture of “{name}”",
    "## Стек": "## Stack",
    "## Конвенции": "## Conventions",
    "## Соглашения и актуальные решения": "## Decisions and current agreements",
    "Код, противоречащий этим решениям, — легаси, а не эталон. Актуальный список — `list_decisions`.": "Code that contradicts these decisions is legacy, not the reference. The live list is `list_decisions`.",
    "## Как работать с проектом": "## Working with the project",
    "Запуск": "Run",
    "Тесты": "Tests",
    "Миграции": "Migrations",
    "Деплой": "Deploy",
    "Актуальные детали ищи в карте знаний: инструменты `graph_search`, `graph_cypher`, `project_overview` MCP-сервера projectai.": "For up-to-date details query the knowledge map: the `graph_search`, `graph_cypher` and `project_overview` tools of the projectai MCP server.",
    "Архитектура, компоненты и конвенции проекта «{name}». Используй при любых вопросах об устройстве проекта.": "Architecture, components and conventions of “{name}”. Use for any question about how the project is built.",
    "# Сервисы и компоненты «{name}»": "# Services and components of “{name}”",
    "За деталями по компоненту — MCP `component_info(name)`; по файлу — `file_info(path)`.": "For component details call MCP `component_info(name)`; for a file, `file_info(path)`.",
    "Сервисы и компоненты проекта «{name}»: за что каждый отвечает, ключевые файлы. Используй при вопросах «где реализовано X».": "Services and components of “{name}”: what each one is responsible for, key files. Use for “where is X implemented” questions.",
    "# Бизнес-логика «{name}»": "# Business logic of “{name}”",
    "Бизнес-фичи проекта «{name}»: как они работают с точки зрения продукта и кода.": "Business features of “{name}”: how they work from the product and code perspective.",
    "Рабочий процесс задач проекта: канбан, фиксация сделанного и решений, обновление карты знаний. Используй при работе над задачами.": "Task workflow of the project: kanban, logging completed work and decisions, refreshing the knowledge map. Use while working on tasks.",
    "Разбор тяжёлой или мутно сформулированной задачи: RLM-досье — где смотреть, нюансы, как проверить. Используй ПЕРЕД тем, как браться за такую задачу.": "Briefing for a heavy or vaguely worded task: an RLM brief — where to look, pitfalls, how to verify. Use BEFORE taking on such a task.",
    "Как искать по проекту: когда graph_search, когда rlm_query, когда file_info/component_info. Используй, когда нужно что-то найти или понять в кодовой базе.": "How to search the project: when to use graph_search, rlm_query, file_info/component_info. Use whenever you need to find or understand something in the codebase.",
}


#: длинные тексты по ключу: {name} — имя проекта
TEXTS: dict[str, dict[str, str]] = {
    "ru": {
        "skill_workflow_body": """# Рабочий процесс проекта «{name}»

Проект подключён к системе «Проекты ИИ» (карта знаний + канбан). Доступны MCP-инструменты сервера `projectai`:

## Перед началом работы
1. `task_list` — посмотри доску задач (planned / in_progress / review / done).
2. `project_overview`, `graph_search` — изучи контекст по карте знаний, не читая весь код.
3. `list_decisions` — актуальные соглашения: код, противоречащий им, — легаси, а не эталон.
4. Тяжёлая или мутная задача — сначала разбор (скилл `task-briefing`).

## Во время работы
- Возьми задачу: `task_move` в `in_progress`.
- Новые обнаруженные задачи создавай через `task_create`; мутные — с `enrich=true`.
- Уточняй описания через `task_update`.

## Соглашения — ОБЯЗАТЕЛЬНО
Пользователь поправил понимание проекта («это не баг, мы сменили подход», «роль X
упразднили») — сразу фиксируй через `record_decision(topic, text)`. Совпадающая тема
обновляется. Без этого каждая будущая проработка снова назовёт смену подхода багом.

## После работы — ОБЯЗАТЕЛЬНО
- `task_done(task_id, report, files)` — пометь задачу выполненной с отчётом и списком изменённых файлов.
- Если работа вне задачи — `log_work(description, files)`.
Отчёты копятся и попадают в карту знаний при следующем обновлении индекса
(кнопка «⟳ Индекс» в приложении или `request_reindex`, если он включён для плагина).
""",
        "skill_briefing_body": """# Разбор задачи через RLM («{name}»)

Когда задача большая, мутная или сформулирована «своими словами с созвона» — не бросайся
делать. Система разберёт её по реальной кодовой базе и соберёт досье:
как понята задача, гипотеза, **где смотреть** (файлы + что в них проверить), образец
рядом, **нюансы** (что заденет работа), **как проверить** и развилки, которые должен
решить человек. Досье не предписывает решение — как делать, решаешь ты.

## Как
1. Новая задача: `task_create(title, description, enrich=true)` — заводится на доске
   и уходит в разбор. Существующая: `task_enrich(task_id)`.
2. Разбор идёт в фоне минуты (RLM-исследование кодовой базы). Займись другим или подожди.
3. `task_get(task_id)` — забери досье (поля extra: reading, hypothesis, where_to_look,
   reference, impact, how_to_verify, open_questions). Если `extra.enriched` ещё нет —
   разбор не закончился.
4. Развилки из open_questions реши с пользователем ДО начала работы.
5. Работай от досье: места и нюансы уже найдены, план строишь сам.
""",
        "skill_search_body": """# Как искать по «{name}»

Порядок — от дешёвого к дорогому; не читай десятки файлов в свой контекст.

1. **Знаешь, что ищешь по названию/смыслу** → `graph_search(query)` — гибридный поиск
   (полнотекст + семантика) по файлам, сущностям, компонентам, документам, задачам,
   соглашениям. Начинай почти всегда с него.
2. **Нужно досье конкретного места** → `file_info(path)` — роль файла, сущности, связи,
   задачи и работы по нему; `component_info(name)` — за что отвечает компонент и его
   ключевые файлы.
3. **Вопрос структурный** («какие эндпоинты без тестов», «кто импортирует X») →
   `graph_cypher` — read-only Cypher по графу (Project, File, Entity, Component,
   Document, Task, WorkLog; $pid уже передан).
4. **Вопрос широкий, ответ размазан по многим файлам** («как устроена авторизация»,
   «что сломается, если поменять Y») → `rlm_query(question, paths?)` — под-агент
   прочитает файлы и вернёт ответ, не засоряя твой контекст. paths можно не задавать —
   система сама спланирует группы по карте знаний.
5. **Что было решено людьми** (не кодом) → `list_decisions`; материалы созвонов и ТЗ →
   `list_documents` + `read_document`.

Точечное чтение файлов инструментом Read — после того, как места найдены, а не вместо поиска.
""",
    },
    "en": {
        "skill_workflow_body": """# Workflow of “{name}”

The project is connected to Project AI (knowledge map + kanban). The `projectai` MCP server provides these tools:

## Before starting
1. `task_list` — look at the board (planned / in_progress / review / done).
2. `project_overview`, `graph_search` — study the context via the knowledge map instead of reading all the code.
3. `list_decisions` — current decisions: code that contradicts them is legacy, not the reference.
4. Heavy or vague task — get a brief first (the `task-briefing` skill).

## While working
- Take a task: `task_move` to `in_progress`.
- Create newly discovered tasks with `task_create`; vague ones with `enrich=true`.
- Refine descriptions with `task_update`.

## Decisions — MANDATORY
When the user corrects your understanding of the project (“this is not a bug, we changed the approach”, “role X was removed”) — record it immediately with `record_decision(topic, text)`. A matching topic is updated. Without this, every future briefing will call the change of approach a bug again.

## After the work — MANDATORY
- `task_done(task_id, report, files)` — mark the task done with a report and the list of changed files.
- Work outside a task — `log_work(description, files)`.
Reports accumulate and reach the knowledge map at the next index update
(the “⟳ Index” button in the app or `request_reindex`, if it is enabled for the plugin).
""",
        "skill_briefing_body": """# Briefing a task with RLM (“{name}”)

When a task is big, vague or worded “in someone's own words from a call” — do not rush to implement.
The system investigates it against the real codebase and assembles a brief:
how the task was understood, a hypothesis, **where to look** (files + what to check in them), a reference
nearby, **pitfalls** (what the work will affect), **how to verify**, and open questions a human
must decide. The brief does not prescribe a solution — how to do it is up to you.

## How
1. New task: `task_create(title, description, enrich=true)` — lands on the board and goes into briefing.
   Existing task: `task_enrich(task_id)`.
2. Briefing runs in the background for minutes (RLM investigation of the codebase). Do something else or wait.
3. `task_get(task_id)` — fetch the brief (fields in extra: reading, hypothesis, where_to_look,
   reference, impact, how_to_verify, open_questions). If `extra.enriched` is missing, the briefing is not done yet.
4. Settle the open_questions with the user BEFORE starting.
5. Work from the brief: the places and pitfalls are already found, the plan is yours.
""",
        "skill_search_body": """# How to search “{name}”

Order — from cheap to expensive; do not read dozens of files into your own context.

1. **You know what you are looking for by name or meaning** → `graph_search(query)` — hybrid search
   (full-text + semantic) over files, entities, components, documents, tasks and decisions. Start here almost always.
2. **You need a dossier of a specific place** → `file_info(path)` — the file's role, entities, relations,
   tasks and work items touching it; `component_info(name)` — what a component is responsible for and its key files.
3. **A structural question** (“which endpoints have no tests”, “who imports X”) →
   `graph_cypher` — read-only Cypher over the graph (Project, File, Entity, Component,
   Document, Task, WorkLog; $pid is already bound).
4. **A broad question with the answer spread across many files** (“how does auth work”,
   “what breaks if I change Y”) → `rlm_query(question, paths?)` — a sub-agent reads the files and returns
   an answer without polluting your context. paths is optional — the system plans file groups from the knowledge map itself.
5. **What people decided** (not the code) → `list_decisions`; call and spec materials →
   `list_documents` + `read_document`.

Reading files with the Read tool is for after the places are found, not instead of searching.
""",
    },
}
