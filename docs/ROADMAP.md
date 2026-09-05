# Roadmap

*Русская версия: [ROADMAP.ru.md](ROADMAP.ru.md).*

## Done (v0.1)

- Auth, projects, directory picker, background indexing with diff reports
- Neo4j knowledge graph: structure + AI file analysis + overview synthesis
- Chat (SSE, Opus 5 by default, reasoning depth), project MCP tools
- Kanban + task extraction from materials + AI verification of completed work
- Whisper transcription, text extraction from documents
- RLM engine, knowledge-map refresh from work logs, Claude Code plugin generator
- Project decisions, RLM task briefing, git history import
- Tests against a fake claude binary

## Done (v0.2)

- SSE push of background job progress and kanban events (instead of polling every 3 s)
- Analysis queue: automatic continuation of the backlog ("until the backlog is empty" on the Overview tab)
- Cancelling background jobs from the UI; retries of failed batches —
  transient failures immediately, files in error state on a manual "Update index"
- Knowledge map export to markdown
- Task details: files with roles (AFFECTS edges from the graph + RLM) and work-log history
- Alembic migrations instead of create_all (older installs are stamped automatically)

## Done (v0.3)

- Planner: a task from a call → RLM investigation → overall plan → decomposition into
  kanban subtasks with dependencies (depends_on, DEPENDS_ON / SUBTASK_OF edges in the graph);
  "Decompose" button on a task, `task_plan` MCP tool for chat and plugins
- Directory watcher (watchdog): code edits trigger an incremental index with a debounce;
  enabled per project on the Overview tab, survives a server restart

## Done (v0.4)

- Semantic search: Qdrant + local embeddings (fastembed, ONNX, no API cost);
  /graph/search became hybrid — Neo4j full-text + semantics; finds files, material
  summaries and decisions both by exact words and by meaning
- Multi-repo projects: several directories per project (e.g. separate backend and
  frontend repositories); files of extra roots live with an `alias/` prefix in the registry,
  graph, vectors and kanban; AI analysis runs with the cwd of its own root, the watcher
  covers all roots, git import sees every repository

## Done (v0.5)

- Task briefing rewritten as a dossier for the executor instead of a prescribed plan:
  reading, hypothesis with confidence, where to look, reference nearby, pitfalls (impact),
  how to verify, open questions; optional follow-up investigation of unresolved points
- Clarifying materials: a spec or note uploaded after a call extends the tasks born from
  that call instead of duplicating them; owner notes survive re-briefing
- Configurable RLM depth (a tree instead of a single layer), job concurrency
- Per-project tool access for the external plugin vs the built-in chat
- Two UI languages (RU / EN, next-intl) and `AI_LANGUAGE` for AI-generated content

## Next

### Near term
- [ ] Speaker diarization in transcripts (pyannote)
- [ ] OCR for scanned PDFs (tesseract)
- [ ] Linux/macOS parity for the one-command start (shell script next to `start.ps1`)

### Mid term
- [ ] Reranker / filters for semantic search (by node type, by directory)
- [ ] Incremental knowledge-map export (only what changed)

### Long term
- [ ] Team mode: roles, project sharing, task comments
- [ ] Cloud mode with a local scanner agent
- [ ] Autonomous agents: "do the task" → the AI writes code in a branch → PR + work-log report
