# Bug Investigator UI

React SPA for the Automated Bug Investigator dashboard (dark Linear/Vercel-style).

## Develop

```bash
# terminal 1 — API
cd ..
uvicorn api.main:app --reload --port 8000

# terminal 2 — frontend
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:3000 — Vite proxies `/api` to the backend.

## Env (optional)

```
VITE_API_BASE_URL=
VITE_BUGGY_APP_README_URL=https://github.com/<owner>/buggy-app#readme
```

## Build

```bash
npm run build
```
