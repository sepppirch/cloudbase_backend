# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project

Multiplayer backend for the Cloudbase flight sim. It is built on the `datadivr`
library (FastAPI + WebSockets, in `datadivr/`); the game server itself lives in
`examples/gameserver/gameserver.py`, with HTML templates in `templates/` and
browser assets in `static/`.

- Run locally: `uv run python examples/gameserver/gameserver.py` (serves on `127.0.0.1:8765`).
- Production mode is enabled by setting `PERSISTANT_PATH` (storage dir for
  `users.json`, `userskins/`, `tasks/`, `tracks/`).
- Required env vars in production: `ADMIN_TOKEN` (admin panel is disabled
  without it), `SESSION_SECRET` (signs login cookies), `MAIL_PASSWORD`.
- Never commit `users.json` or `.env`: they hold user data and secrets.

## Model usage

Use expensive models only where they pay off:

- **Expensive / most capable model**: writing and changing code.
- **Cheaper models**: everything else, such as code review, exploring or
  searching the codebase, summarizing, docs, and other read-only or mechanical work.

When spawning subagents or workflows, choose the model by this rule rather
than inheriting the most expensive one by default.
