# Contributing

Thanks for taking an interest. Bug reports, ideas and pull requests are welcome.

## Before you start

- Open an issue first for anything bigger than a small fix, so the approach can be
  discussed before you spend time on it.
- Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): it explains the knowledge-graph
  schema, the indexing pipeline, RLM and the task-briefing pipeline that most changes touch.

## Development setup

The [README](README.md#getting-started) covers the full setup. In short: `docker compose up -d`,
a Python 3.13 venv in `backend/`, `npm install` in `frontend/`, and a logged-in Claude Code CLI.

Checks that must pass before a pull request:

```bash
cd backend && .venv/Scripts/python -m pytest -q      # integration tests on a fake claude binary
cd frontend && npm run lint && npx tsc --noEmit      # frontend
```

## Conventions

- Backend: SQLAlchemy models in `app/models.py` are the single source of the schema; schema
  changes go through Alembic (`alembic revision --autogenerate`, then read the generated file).
  User-facing strings are wrapped in `i18n._()` with an English translation in `app/i18n.py`.
- Frontend: every visible string lives in both `frontend/messages/ru.json` and `en.json`
  with the same keys.
- Keep pull requests focused: one change, with a short explanation of *why* in the description.

## License of contributions

The project is released under the [MIT License](LICENSE). By submitting a pull request you
agree that your contribution is licensed under the same terms.
