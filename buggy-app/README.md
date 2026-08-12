# buggy-app

Standalone FastAPI demo app with **three intentional bugs**.  
Used as the target repository for Bug Investigator demos — **not** part of the main app's docker-compose.

## Run with Docker (recommended)

```bash
cd buggy-app
docker compose up --build
```

App UI: http://127.0.0.1:8001/  
API docs: http://127.0.0.1:8001/docs  

Follow logs (here is where the traceback appears):

```bash
docker compose logs -f buggy-app
```

Or one-shot:

```bash
docker build -t buggy-app .
docker run --rm -p 8001:8001 --name buggy-app buggy-app
# traceback: docker logs -f buggy-app
```

## Run locally (without Docker)

```bash
cd buggy-app
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

## Trigger the bugs (copy traceback from logs)

Open http://127.0.0.1:8001/ and click the three buttons — or use curl below.

Each endpoint raises an unhandled exception. Copy the full traceback from **container/terminal logs** into Bug Investigator.

After Bug Investigator merges a fix and you rebuild/restart this container against the fixed code, the same buttons should show a green **OK** response.

### Bug 1 — IndexError (empty cart)

```bash
curl -X POST http://127.0.0.1:8001/trigger/empty-cart-checkout
```

### Bug 2 — TypeError (str vs number discount)

Windows (PowerShell / cmd):

```bash
curl -X POST http://127.0.0.1:8001/trigger/invalid-discount-type -H "Content-Type: application/json" -d "{\"price\": \"99.99\", \"discount_percent\": 10}"
```

macOS / Linux:

```bash
curl -X POST http://127.0.0.1:8001/trigger/invalid-discount-type \
  -H "Content-Type: application/json" \
  -d '{"price": "99.99", "discount_percent": 10}'
```

### Bug 3 — forgotten `await`

```bash
curl "http://127.0.0.1:8001/trigger/async-price-fetch?product_id=1"
```

## Project layout

```
buggy-app/
  main.py
  models.py
  services.py
  utils.py
  routers/triggers.py
  static/index.html   # simple demo UI
  Dockerfile
  docker-compose.yml
  requirements.txt
  README.md
```

## Note for GitHub

Publish this folder as its **own** GitHub repository. Point Bug Investigator `.env` at that repo:

```
GITHUB_REPO_OWNER=<your-user>
GITHUB_REPO_NAME=buggy-app
```
