# Project AI — architecture

*Русская версия: [ARCHITECTURE.ru.md](ARCHITECTURE.ru.md).*

## Big picture

```
Browser (Next.js 16, :3010)
   │  REST + SSE
   ▼
FastAPI (:8010) ──── JobRunner (in-process background workers)
   │        │                │
   │        │                ├─ index: scan → diff → graph → AI analysis → synthesis → work log
   │        │                ├─ enrich_tasks: RLM investigation → brief for the executor
   │        │                ├─ plan_task: RLM investigation → subtasks with dependencies
   │        │                ├─ process_material: whisper / text extraction → summary → tasks
   │        │                ├─ verify_tasks: AI check of what is already implemented
   │        │                ├─ git_import: commit history → completed work items
   │        │                └─ plugin_generate: Claude Code plugin from the knowledge map
   │        │
   │        ├─ Postgres (docker): users, projects, files, chats, jobs,
   │        │                     tasks (kanban), work log, materials, change reports
   │        ├─ Neo4j (docker):    knowledge graph + full-text search
   │        └─ Qdrant (docker):   semantic search — embeddings of files, materials
   │                              and decisions (fastembed, computed locally)
   │
   └─ claude -p (Claude Code CLI, headless)
        │  --mcp-config → MCP server "projectai" (stdio, backend/mcp_main.py)
        └─ tools: graph_search, graph_cypher, rlm_query, task_*, log_work, …
```

Everything runs locally (self-hosted): the backend has direct access to the project
directories, `claude -p` uses the local Claude Code login, Whisper runs on the GPU/CPU.

## Knowledge graph schema (Neo4j)

Every node carries `project_id` and a unique `uid` = `project_id|kind|identifier`.

| Node | What it is | Key relations |
|---|---|---|
| `Project` | project root | `CONTAINS`, `HAS_COMPONENT`, `HAS_FEATURE`, `HAS_DOCUMENT`, `HAS_TASK`, `HAS_WORKLOG` |
| `Directory` | directory | `CONTAINS` (nesting) |
| `File` | file: role, summary, tags | `DEFINES → Entity`, `RELATES {type} → File` |
| `Entity` | class / function / endpoint / model / screen / config parameter | — |
| `Component` | component / service / feature from the synthesis | `INCLUDES → File` |
| `Document` | material (transcript, spec) | `MENTIONS → File` |
| `Task` | kanban task | `AFFECTS → File`, `DEPENDS_ON → Task`, `SUBTASK_OF → Task` |
| `WorkLog` | "what was done" entry | `UPDATED → File` |
| `Decision` | project decision | — |

The full-text index `knowledge_fulltext` over name / path / summary / title plus semantic
search over embeddings (Qdrant, `services/vectors.py`) form the hybrid `graph_search`: every hit
has `match: fulltext | semantic | both`. Embeddings are computed locally (fastembed / ONNX,
multilingual MiniLM) during AI file analysis, material processing and when decisions are
recorded; an unavailable Qdrant does not break the pipelines (search degrades to full-text).
`graph_cypher` is read-only — write and administrative clauses are rejected.

## Multi-repo (`services/roots.py`)

A project may consist of several directories: the main one (`root_path`, files without a prefix)
and extra roots (`meta.extra_roots: [{alias, path}]`, files prefixed `alias/` in the registry,
graph, vectors and tasks). The alias is chosen so that it never collides with a top-level entry
of the main directory, so every path resolves unambiguously. AI analysis runs per root (cwd of
that root, local paths in the prompt), RLM substitutes absolute paths for files of foreign roots,
the watcher covers all roots, git import finds repositories in every directory. Removing a root
cleans its files from the registry, the graph and the vector index.

## Indexing pipeline (`services/indexer.py`)

1. **Scan** (`scanner.py`): directory walk with ignore lists (node_modules, .git, build, …)
   **and `.gitignore`** — including nested .gitignore files of monorepo sub-projects (pathspec);
   sha256 hashes (reused when mtime + size are unchanged), file-kind classification.
2. **Diff**: added / modified / deleted → `change_reports` ("what changed" on the Overview tab).
3. **Structure graph**: batched MERGE of Project / Directory / File, removal of vanished files.
4. **Detection** (`detect.py`): project kind and stack from marker files (package.json, pubspec, …).
5. **AI analysis**: batches of `AI_BATCH_SIZE` files → `claude -p` (model `AI_MODEL`, usually
   sonnet) with the Read tool and strict JSON output: role, summary, entities, links → graph.
   The budget is `AI_MAX_FILES_PER_RUN` per run; the rest is processed by subsequent
   "Update index" runs (or automatically with *analyze until the backlog is empty*).
6. **Synthesis**: project overview (architecture, components, business logic, conventions,
   how-to) → `Project.summary`, `Component` nodes, `project.meta.overview`.
7. **Plugin** is regenerated with the fresh knowledge.

Modes: `initial` (on creation), `update` (changes + continuation of the analysis backlog),
`reverify` (reset every mark → full re-analysis).

## RLM — Recursive Language Models

The idea ([Zhang, Khattab]): with large contexts the model should not swallow the whole window —
the context lives "in the environment", the model explores it programmatically and recursively
calls sub-models over fragments.

Implementation (`services/rlm.py` + the `rlm_query` MCP tool):

- **Environment** = project directory + knowledge graph + file registry with roles.
- **Root** (plan): receives a digest of the graph, full-text search results and the file index →
  picks groups of files (up to 4 groups × 12 files) for the question.
- **Sub-calls**: isolated `claude -p` processes with the Read tool; each reads only its group
  and returns a compressed answer.
- **Synthesis**: the root call assembles the final answer from the sub-answers.
- **Depth** (`RLM_MAX_DEPTH`): `1` — root plus one layer of sub-agents; `2` and more — a
  sub-agent that lacks something in its assigned files appends a "NEEDS CLARIFICATION" block, and
  the same pipeline runs recursively for each question; `0` — unlimited. Branching per level is
  `RLM_BRANCHING`; the overall safety valve is `RLM_MAX_NODES` (nested investigations per run)
  plus a hard depth cap. The concurrency semaphore is shared across the whole tree, so depth does
  not multiply processes.

The chat assistant is itself a root RLM agent: its system prompt teaches it to call `rlm_query`
instead of reading dozens of files into its own context. `POST /api/projects/{id}/ask` is an RLM
question without a chat.

## Keeping the knowledge current

```
AI or a person does the work
   └─ task_done(report, files) / log_work(...)   ← MCP or UI
        └─ WorkLogEntry (synced=False) accumulates; the header badge shows the count
             └─ manual "⟳ Index" (or request_reindex)
                  ├─ scan diff → changed files → re-analysis → graph
                  ├─ WorkLog / Task nodes → UPDATED / AFFECTS edges to files
                  ├─ cleanup of Task nodes of deleted tasks (orphans)
                  └─ ChangeReport ("what changed")
```

Deleting a task removes its node immediately, but the graph may be unavailable at that moment,
so indexing additionally sweeps orphans. This is not cosmetic: a Task node's title is the task
wording, it sits in the full-text index and lands in the top-15 hits for a similar question —
the very list from which RLM picks files to read.

The map update is manual: an automatic `knowledge_update` after every task competed for AI
slots with briefings during batch work. The job type is kept for history; all the work (scan +
work-log accounting) happens inside `index_project`.

`verify_tasks`: for every open task the AI (Read / Grep / Glob over the code) returns a
yes / partial / no verdict — "yes" marks the task done with a report and the files as evidence.

## RLM task briefing (`services/task_enrich.py`)

The key scenario: after a call, tasks are short ("fix the delete button of the integration"),
and the system prepares a brief for the executor — a person or an AI agent who decides how to
do it. The solution is deliberately NOT prescribed: a plan built by the model at briefing time
becomes a ceiling for a stronger executor, while facts are a floor. The `enrich_tasks` pipeline:

1. **RLM investigation** of the task: the root picks file groups from the knowledge map,
   sub-agents read them and return facts — exact paths, how it works now, the likely cause of
   the bug, a "reference" implementation nearby, the test setup next to it.
2. **Brief synthesis**: from the investigation facts plus the list of existing tasks (done and
   open!) the model assembles `reading` (how the task was understood), `hypothesis` (likely cause
   with confidence), `where_to_look` (places + what to check there), `reference` (where the same
   thing is done right nearby), `how_to_verify` (what must become true and which test / command
   checks it). Imperatives ("add / change") are forbidden by the prompt; the `plan` field is no
   longer filled by the briefing.
3. **Open questions and impact**: `open_questions` — what a human must decide (two defensible
   options with consequences; an empty list means "the choice is obvious"), `impact` — what the
   change will touch besides the place of the change: thresholds, state machines, contracts between
   layers. Without these fields the model silently decided for the product — the shape of the
   answer dictates behaviour.
4. **Follow-up investigation** (optional, `ENRICH_FOLLOWUP`): the synthesis lists in a separate
   `unresolved` field what it could not find in the code; if the list is non-empty, one narrow RLM
   pass runs for it and the description is rebuilt. Otherwise a guess ("probably somewhere") settles
   into the task.
5. **Relations**: `related_tasks` (duplicate / continuation / overlaps) and `duplicate_of` — so
   that tasks from calls are not duplicated and continuations find their parents; task files go into
   the graph as `AFFECTS` edges.

Triggered automatically after task extraction from materials, by the UI buttons ("🧠 Brief" on a
task, "Brief new tasks (RLM)" on the board) and by the `task_enrich` MCP tool. Task extraction from
new materials also sees the existing tasks and does not create duplicates.

## Chat (`routers/chats.py`)

- `claude -p` with `stream-json` streaming → SSE (`delta`, `tool`, `done`, `error`).
- Sessions: `--resume <session_id>` — the dialogue context lives in Claude Code.
- Model per chat: `--model opus|sonnet|haiku` (opus = Opus 5 by default).
- Reasoning per chat: none / low / medium / high → `MAX_THINKING_TOKENS` (0 / 4k / 12k / 32k).
- Tools: Read / Grep / Glob / LS + the whole `projectai` MCP. The chat has no write access to
  files — project changes are recorded through tasks and the work log.

## MCP server (`app/mcp/server.py`)

A stdio server (FastMCP) started by Claude Code itself (from the chat or from an installed plugin).
It works through the backend HTTP API with a **service JWT** scoped to one project.
Tools: `project_overview`, `graph_search`, `graph_cypher`, `component_info`, `file_info`,
`list_files`, `list_documents`, `read_document`, `list_decisions`, `record_decision`, `rlm_query`,
`task_list / get / create / update / move / done / enrich / plan`, `log_work`, `request_reindex`,
`git_import`. Which tool groups a surface (built-in chat vs external plugin) may use is configured
per project (`services/tool_access.py`); technical operations are off for the plugin by default.

## Claude Code plugins (`services/plugin_gen.py`)

`data/plugins/<slug>/`: `.claude-plugin/plugin.json`, `.mcp.json` (the same MCP server),
`skills/architecture`, `skills/services`, `skills/business-logic`, `skills/project-workflow`,
`skills/task-briefing`, `skills/how-to-search` — generated from the knowledge map on every
indexing run and whenever decisions change. `data/plugins/.claude-plugin/marketplace.json` is
the marketplace of all projects: `claude plugin marketplace add <path>` once, then
`claude plugin install <slug>@projectai`. The per-project install writes the marketplace and the
plugin into `<project>/.claude/settings.local.json` instead.

## Materials (`services/materials.py`)

- Audio / video → faster-whisper (large-v3, CUDA float16 with a CPU int8 fallback), timestamps
  in the transcript.
- pdf → pypdf, docx → python-docx, xlsx → openpyxl, txt / md / json — directly (encoding via
  charset-normalizer).
- Text → AI summary + task extraction (source = meeting / doc) → kanban + a Document node.
- A note in your own words (`POST /materials/note`) is the same kind of material, just typed by
  hand. There is deliberately no separate mechanism for it.

### Clarifying materials

A call gives the skeleton of the tasks; a spec or a note that arrives later gives the logic
without which they cannot be done. Previously this was lost: the extraction prompt told the model
to skip anything that refines an already existing task, and the second half of the intent stayed
in the file.

A material can be uploaded as a clarification of an earlier one (`?clarifies=<id>`, stored in
`material.meta`). Then:

1. Tasks born from that material (`task.extra.from_material`) go into the prompt with their FULL
   description — 120 characters from the general list are not enough to decide between "extend"
   and "create".
2. The extraction contract knows the verb "extend": `updates` with the exact task title. A missed
   title is logged and skipped — the task is not corrupted.
3. The addition is stored in `task.extra.clarifications`, NOT in the description: the briefing
   rebuilds the description as a whole and would overwrite anything appended there.
4. The `enriched` flag is cleared and the task goes back to briefing — the brief is rebuilt with
   the new logic.

`task.extra.notes` (the task owner's notes) live there too. Both blocks are read by the briefing
(`human_input_block`) and never overwritten: this is direct speech of people, which outweighs
conclusions drawn from the code.

## Localization

- **UI**: next-intl without URL prefixes. The locale comes from a cookie set by the RU / EN switch
  or, on first visit, from the browser's `Accept-Language`; catalogues live in
  `frontend/messages/*.json`. Dates and byte units follow the locale.
- **API messages**: the frontend sends the UI locale as `Accept-Language`; a pure ASGI middleware
  stores it in a context variable and `i18n._()` picks the translation (gettext style, the Russian
  string is the key and the fallback).
- **AI content and background jobs**: `AI_LANGUAGE` (`en` / `ru`) — the language note in every
  prompt template is substituted, a language directive is appended to every `claude -p` system
  prompt, and job progress messages, the knowledge-map export and the generated plugin skills use
  the same setting.

## Security

- JWT (HS256), bcrypt; service tokens are scoped to a project_id.
- `graph_cypher` is read-only; the chat has no Write / Bash.
- Secrets live in `.env` (not in git); the service token is never returned by the project API.
- Designed for a local, trusted machine (the filesystem browser exposes directories to the
  account owner).
