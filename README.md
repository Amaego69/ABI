# Automated Bug Investigator

Multi-agent Bug Fixer as a Service (FastAPI + LangGraph + React).

## Quick start (Docker)

1. Copy env and fill secrets:
   ```bash
   copy .env.example .env
   ```
2. On **Windows**, set an absolute path for sandbox binds in `.env`:
   ```
   SANDBOX_BIND_ROOT=D:/AAI/Automated_Bug_Investigator/data/runs
   ```
3. Start the stack (**buggy-app is not included**):
   ```bash
   docker compose up --build
   ```
4. Open UI: http://127.0.0.1:3000 · API docs: http://127.0.0.1:8000/docs

## buggy-app (separate)

```bash
cd buggy-app
docker compose up --build
```

UI: http://127.0.0.1:8001/ — trigger a bug, copy traceback from logs into the main UI.
