# Архитектура «Проекты ИИ»

## Общая схема

```
Браузер (Next.js 16, :3010)
   │  REST + SSE
   ▼
FastAPI (:8010) ──── JobRunner (встроенные фоновые воркеры)
   │        │                │
   │        │                ├─ index: скан → diff → граф → ИИ-анализ → синтез
   │        │                ├─ process_material: whisper/извлечение → задачи
   │        │                ├─ knowledge_update: суб-агент актуализации графа
   │        │                ├─ verify_tasks: ИИ-проверка выполненности
   │        │                └─ plugin_generate: плагин Claude Code
   │        │
   │        ├─ Postgres (docker): users, projects, files, chats, jobs,
   │        │                     tasks (канбан), worklog, materials, change_reports
   │        └─ Neo4j (docker):    карта знаний (граф)
   │
   └─ claude -p (Claude Code CLI, headless)
        │  --mcp-config → MCP-сервер projectai (stdio, backend/mcp_main.py)
        └─ инструменты: graph_search, graph_cypher, rlm_query, task_*, log_work…
```

Всё крутится локально (self-hosted): бэкенд имеет прямой доступ к каталогам проектов,
`claude -p` использует локальную авторизацию Claude Code, Whisper работает на GPU/CPU.

## Схема графа знаний (Neo4j)

Все узлы несут `project_id` и уникальный `uid` = `project_id|вид|идентификатор`.

| Узел | Что это | Ключевые связи |
|---|---|---|
| `Project` | корень проекта | `CONTAINS`, `HAS_COMPONENT`, `HAS_FEATURE`, `HAS_DOCUMENT`, `HAS_TASK`, `HAS_WORKLOG` |
| `Directory` | каталог | `CONTAINS` (вложенность) |
| `File` | файл: роль, summary, теги | `DEFINES → Entity`, `RELATES {type} → File` |
| `Entity` | класс/функция/эндпоинт/модель/экран/параметр | — |
| `Component` | компонент/сервис/фича из синтеза | `INCLUDES → File` |
| `Document` | материал (транскрипт, ТЗ) | `MENTIONS → File` |
| `Task` | задача канбана | `AFFECTS → File` |
| `WorkLog` | запись «что сделано» | `UPDATED → File` |

Полнотекстовый индекс `knowledge_fulltext` по name/path/summary/title — основа
`graph_search`. `graph_cypher` — read-only (записи отклоняются).

## Пайплайн индексации (`services/indexer.py`)

1. **Скан** (`scanner.py`): обход каталога с игнор-листами (node_modules, .git, build…),
   sha256-хэши (с переиспользованием по mtime+size), классификация kind.
2. **Diff**: added/modified/deleted → `change_reports` (то самое «что обновилось»).
3. **Граф структуры**: батчевые MERGE Project/Directory/File, удаление исчезнувших.
4. **Детект** (`detect.py`): тип проекта и стек по маркер-файлам (package.json, pubspec…).
5. **ИИ-анализ**: батчи по `AI_BATCH_SIZE` файлов → `claude -p` (модель `AI_MODEL`,
   обычно sonnet) с инструментом Read и строгим JSON-выводом: роль, summary, сущности,
   связи → граф. Бюджет — `AI_MAX_FILES_PER_RUN` за прогон; остаток дообрабатывается
   следующими «Обновить индекс».
6. **Синтез**: обзор проекта (архитектура, компоненты, бизнес-логика, конвенции,
   how-to) → `Project.summary`, `Component`-узлы, `project.meta.overview`.
7. **Плагин** перегенерируется со свежими знаниями.

Режимы: `initial` (при создании), `update` (изменения + продолжение бэклога анализа),
`reverify` (сброс всех меток → полный пере-анализ).

## RLM — Recursive Language Models (MIT)

Идея ([Zhang, Khattab]): при больших контекстах модель не должна глотать всё окно —
контекст лежит «в среде», модель исследует его программно и рекурсивно вызывает
саб-модели над фрагментами.

Реализация (`services/rlm.py` + MCP-инструмент `rlm_query`):

- **Среда** = каталог проекта + граф знаний + реестр файлов с ролями.
- **Корень** (план): получает выжимку графа, результаты fulltext-поиска и индекс файлов →
  выбирает группы файлов (до 4 групп × 12 файлов) под вопрос.
- **Под-вызовы**: изолированные `claude -p` с инструментом Read, каждый читает только
  свою группу и возвращает сжатый ответ.
- **Синтез**: корневой вызов собирает финальный ответ из под-ответов.

Чат-ассистент — сам корневой RLM-агент: системный промпт учит его не читать десятки
файлов в свой контекст, а звать `rlm_query`. Эндпоинт `POST /api/projects/{id}/ask` —
RLM-вопрос без чата.

## Цикл актуальности знаний

```
ИИ/пользователь делает работу
   └─ task_done(отчёт, файлы) / log_work(...)   ← MCP или UI
        └─ WorkLogEntry + job knowledge_update   ← «суб-агент»
             ├─ скан diff → изменённые файлы → пере-анализ → граф
             ├─ WorkLog/Task-узлы → связи UPDATED/AFFECTS с файлами
             └─ ChangeReport («что обновилось»)
```

Плюс `verify_tasks`: для каждой открытой задачи ИИ (Read/Grep/Glob по коду) выносит
вердикт yes/partial/no — «yes» помечается done с отчётом и файлами-доказательствами.

## Чат (`routers/chats.py`)

- `claude -p` со стримингом `stream-json` → SSE (`delta`, `tool`, `done`, `error`).
- Сессии: `--resume <session_id>` — контекст диалога живёт в Claude Code.
- Модель per-chat: `--model opus|sonnet|haiku` (**opus = Opus 5 по умолчанию**).
- Reasoning per-chat: none/low/medium/high → `MAX_THINKING_TOKENS` (0/4k/12k/32k).
- Инструменты: Read/Grep/Glob/LS + весь MCP `projectai`. Запись в файлы чату не дана —
  изменения проекта фиксируются через задачи/worklog.

## MCP-сервер (`app/mcp/server.py`)

Stdio-сервер (FastMCP), запускается самим Claude Code (из чата или плагина).
Работает через HTTP API бэкенда с **сервисным JWT**, ограниченным одним проектом.
Инструменты: `project_overview`, `graph_search`, `graph_cypher`, `list_files`,
`list_documents`, `read_document`, `rlm_query`, `task_list/create/update/move/done`,
`log_work`, `request_reindex`.

## Плагины Claude Code (`services/plugin_gen.py`)

`data/plugins/<slug>/`: `.claude-plugin/plugin.json`, `.mcp.json` (тот же MCP-сервер),
`skills/architecture`, `skills/business-logic`, `skills/project-workflow` — генерируются
из карты знаний при каждой индексации. `data/plugins/.claude-plugin/marketplace.json` —
маркетплейс всех проектов: `claude plugin marketplace add <path>` один раз, дальше
`claude plugin install <slug>@projectai`.

## Материалы (`services/materials.py`)

- Аудио/видео → faster-whisper (large-v3, CUDA float16 с фолбэком на CPU int8),
  таймкоды в транскрипте.
- pdf → pypdf, docx → python-docx, xlsx → openpyxl, txt/md/json — напрямую
  (кодировка через charset-normalizer).
- Текст → ИИ-выжимка + извлечение задач (source=meeting/doc) → канбан + Document-узел.

## Безопасность

- JWT (HS256), bcrypt; сервисные токены скоупятся project_id.
- `graph_cypher` — только чтение; чат без Write/Bash.
- Секреты в `.env` (не в гите); сервисный токен не отдаётся в API проекта.
- Система рассчитана на локальный/доверенный контур (fs-браузер отдаёт каталоги
  владельцу аккаунта).
