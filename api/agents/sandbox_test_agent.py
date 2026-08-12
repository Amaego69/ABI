"""Sandbox test agent: apply fix and verify inside an isolated Docker container."""

from __future__ import annotations

import re
import textwrap
import time
from pathlib import Path
from typing import Any

from api.config import get_settings
from api.schemas import GraphState, TestResult


def _apply_fix(repo_path: Path, file_path: str, content: str) -> str:
    """Write the full fixed file contents to disk."""
    target = repo_path / file_path
    if not target.exists() and not target.parent.exists():
        raise FileNotFoundError(f"Cannot apply fix — parent missing for: {file_path}")
    if not content:
        raise ValueError(f"empty content for {file_path}")
    text = content if content.endswith("\n") else content + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return "wrote full file content"


def _discover_routes(repo_path: Path) -> list[tuple[str, str]]:
    """
    Find FastAPI routes in the clone: list of (METHOD, path).

    Understands `@router.get/post("/...")` plus `APIRouter(prefix=...)`.
    """
    routes: list[tuple[str, str]] = []
    prefix_by_file: dict[Path, str] = {}

    for path in repo_path.rglob("*.py"):
        if ".git" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        prefix_match = re.search(
            r"APIRouter\s*\([^)]*prefix\s*=\s*[\"']([^\"']+)[\"']",
            text,
        )
        prefix = prefix_match.group(1).rstrip("/") if prefix_match else ""
        prefix_by_file[path] = prefix

        for match in re.finditer(
            r"@\w+\.(get|post|put|patch|delete)\(\s*[\"']([^\"']+)[\"']",
            text,
            flags=re.IGNORECASE,
        ):
            method = match.group(1).upper()
            route = match.group(2)
            if not route.startswith("/"):
                route = "/" + route
            full = f"{prefix}{route}" if prefix else route
            routes.append((method, full))
    return routes


def _normalize_endpoint_candidate(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    if not value.startswith("/"):
        value = "/" + value
    # Common LLM mistake: underscores instead of hyphens in demo routes
    if value.startswith("/trigger/"):
        head, _, tail = value.partition("/trigger/")
        value = "/trigger/" + tail.replace("_", "-")
    return value


def _resolve_trigger_endpoint(state: GraphState) -> tuple[str, str]:
    """
    Return (METHOD, path) for the failing trigger.

    Prefers real routes discovered in the cloned repo over LLM/traceback guesses.
    """
    repo = Path(state.repo_path) if state.repo_path else None
    discovered = _discover_routes(repo) if repo and repo.exists() else []
    trigger_routes = [(m, p) for m, p in discovered if "/trigger/" in p]

    candidates: list[str] = []
    if state.triggered_endpoint:
        candidates.append(state.triggered_endpoint)
    tb = state.bug_report.raw_traceback or ""
    candidates.extend(re.findall(r"(/trigger/[A-Za-z0-9\-_/]+)", tb))

    # Function-name hints → path-like guesses
    for name in (
        state.bug_report.function_name,
        state.code_location.function_name if state.code_location else None,
    ):
        if not name:
            continue
        slug = name
        if slug.startswith("trigger_"):
            slug = slug[len("trigger_") :]
        slug = slug.replace("_", "-")
        candidates.append(f"/trigger/{slug}")

    normalized = [_normalize_endpoint_candidate(c) for c in candidates]
    normalized = [c for c in normalized if c]

    # Exact match against discovered routes
    for cand in normalized:
        for method, path in trigger_routes:
            if path == cand:
                return method, path

    # Fuzzy: ignore hyphen/underscore differences
    def canon(p: str) -> str:
        return p.replace("_", "-").rstrip("/")

    for cand in normalized:
        cc = canon(cand)
        for method, path in trigger_routes:
            if canon(path) == cc:
                return method, path

    # Keyword overlap with error / function
    hay = " ".join(
        filter(
            None,
            [
                state.bug_report.function_name,
                state.bug_report.error_message,
                state.bug_report.raw_traceback[:500],
            ],
        )
    ).lower()
    scored: list[tuple[int, str, str]] = []
    for method, path in trigger_routes:
        score = 0
        for token in re.split(r"[/\-_]+", path.lower()):
            if token and token in hay:
                score += 1
        scored.append((score, method, path))
    scored.sort(reverse=True)
    if scored and scored[0][0] > 0:
        return scored[0][1], scored[0][2]

    if normalized:
        # Last resort: guessed path (may 404, but better than health-only)
        path = normalized[0]
        method = "GET" if "async" in path or "fetch" in path else "POST"
        return method, path

    if trigger_routes:
        return trigger_routes[0]

    return "GET", "/health"


def _infer_curl_command(state: GraphState) -> tuple[str, str, str]:
    """
    Return (METHOD, endpoint, curl_command).

    curl_command writes the body to /tmp/trigger_out and prints only the HTTP code.
    """
    method, endpoint = _resolve_trigger_endpoint(state)

    if endpoint == "/health":
        curl = (
            'curl -s -o /tmp/trigger_out -w "%{http_code}" '
            '"http://127.0.0.1:8000/health"'
        )
        return method, endpoint, curl

    if method == "GET":
        url = f"http://127.0.0.1:8000{endpoint}"
        if "async-price-fetch" in endpoint and "product_id" not in endpoint:
            url += "?product_id=1"
        curl = f'curl -s -o /tmp/trigger_out -w "%{{http_code}}" "{url}"'
    else:
        body = "{}"
        if "invalid-discount" in endpoint:
            body = '{"price":"99.99","discount_percent":10}'
        curl = (
            f'curl -s -o /tmp/trigger_out -w "%{{http_code}}" -X POST '
            f'"http://127.0.0.1:8000{endpoint}" '
            f'-H "Content-Type: application/json" -d \'{body}\''
        )
    return method, endpoint, curl


def _build_container_script(state: GraphState) -> str:
    """Shell script executed inside the sandbox container."""
    method, endpoint, curl = _infer_curl_command(state)
    has_pytest = False
    if state.repo_path:
        repo = Path(state.repo_path)
        has_pytest = any(repo.rglob("test_*.py")) or (repo / "tests").exists()

    pytest_branch = ""
    if has_pytest:
        pytest_branch = textwrap.dedent(
            """
            if [ -d /work/tests ] || ls /work/test_*.py >/dev/null 2>&1; then
              echo "Running pytest..."
              pytest -q /work || { echo "PYTEST_FAILED"; exit 1; }
            fi
            """
        )

    return textwrap.dedent(
        f"""
        set -e
        mkdir -p /work
        cp -a /app/. /work/
        cd /work
        if [ -f requirements.txt ]; then
          pip install -q --no-cache-dir -r requirements.txt || true
        fi
        uvicorn main:app --host 127.0.0.1 --port 8000 >/tmp/uvicorn.log 2>&1 &
        UV_PID=$!
        for i in $(seq 1 30); do
          if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
            break
          fi
          sleep 0.5
        done
        echo "Resolved trigger: {method} {endpoint}"
        echo "Triggering endpoint..."
        CODE=$({curl})
        echo "TRIGGER_HTTP_$CODE"
        echo "TRIGGER_BODY=$(head -c 400 /tmp/trigger_out 2>/dev/null || true)"
        if [ -z "$CODE" ] || [ "$CODE" = "000" ] || [ "$CODE" -ge 500 ]; then
          echo "TRIGGER_FAILED"
          echo "----- uvicorn log -----"
          cat /tmp/uvicorn.log || true
          kill $UV_PID >/dev/null 2>&1 || true
          exit 1
        fi
        echo "TRIGGER_OK"
        {pytest_branch}
        kill $UV_PID >/dev/null 2>&1 || true
        echo "SANDBOX_PASSED"
        """
    ).strip()


def sandbox_test_agent(state: GraphState) -> dict[str, Any]:
    """
    Apply the proposed fix to the clone and verify it in a locked-down Docker container.

    No LLM. Container is always removed afterwards.
    """
    import docker
    from docker.errors import DockerException, ImageNotFound

    if not state.repo_path or state.proposed_fix is None:
        raise RuntimeError("repo_path and proposed_fix are required for sandbox testing")

    settings = get_settings()
    repo = Path(state.repo_path)
    fix = state.proposed_fix
    attempt = state.retry_count + 1

    apply_notes = ""
    patches = list(fix.files) if fix.files else []
    if not patches and fix.file_path and (fix.fixed_code or fix.original_code):
        from api.schemas import FilePatch

        patches = [
            FilePatch(
                file_path=fix.file_path,
                content=fix.fixed_code or "",
                original_code=fix.original_code or "",
                fixed_code=fix.fixed_code or "",
            )
        ]
    if not patches:
        result = TestResult(
            passed=False,
            output="Failed to apply fix: proposed_fix.files is empty",
            attempt_number=attempt,
        )
        return {
            "test_results": [*state.test_results, result],
            "retry_count": attempt,
            "current_stage": "sandbox_test",
        }

    try:
        # Reset all target files so retries apply against the original clone
        try:
            from git import Repo as GitRepo

            paths = [p.file_path for p in patches]
            GitRepo(str(repo)).git.checkout("--", *paths)
            apply_notes += f"reset {len(paths)} file(s) from git; "
        except Exception as reset_exc:
            apply_notes += f"git reset skipped ({reset_exc}); "
        for patch in patches:
            body = patch.content or patch.fixed_code
            note = _apply_fix(repo, patch.file_path, body)
            apply_notes += f"{patch.file_path}: {note}; "
    except Exception as exc:
        result = TestResult(
            passed=False,
            output=f"Failed to apply fix: {exc}",
            attempt_number=attempt,
        )
        return {
            "test_results": [*state.test_results, result],
            "retry_count": attempt,
            "current_stage": "sandbox_test",
        }

    script = _build_container_script(state)
    client = docker.from_env()
    container = None
    output = f"apply: {apply_notes}\n"
    passed = False

    try:
        try:
            client.images.get(settings.sandbox_image)
        except ImageNotFound:
            # Fall back to a public slim image (needs network at image-pull time on host)
            output += (
                f"Sandbox image '{settings.sandbox_image}' not found locally; "
                "falling back to python:3.12-slim\n"
            )
            image = "python:3.12-slim"
        else:
            image = settings.sandbox_image

        # Host may be Windows; Docker Desktop accepts the path via the engine.
        # When api runs in Compose with docker.sock, bind the *host* mirror of RUNS_ROOT.
        bind_path = settings.host_path_for_sandbox(str(repo.resolve()))
        container = client.containers.run(
            image=image,
            command=["bash", "-lc", script],
            volumes={bind_path: {"bind": "/app", "mode": "ro"}},
            working_dir="/work",
            network_mode="none",
            mem_limit=settings.sandbox_mem_limit,
            nano_cpus=settings.sandbox_nano_cpus,
            detach=True,
            stdout=True,
            stderr=True,
        )

        deadline = time.time() + settings.sandbox_timeout_sec
        while container.status in {"created", "running"} and time.time() < deadline:
            container.reload()
            time.sleep(0.5)
            if container.status not in {"created", "running"}:
                break
        else:
            if container.status in {"created", "running"}:
                container.kill()
                output += "TIMEOUT: sandbox exceeded time limit\n"

        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
        output += logs
        exit_code = container.wait().get("StatusCode", 1)
        passed = exit_code == 0 and "SANDBOX_PASSED" in logs and "TRIGGER_FAILED" not in logs
    except DockerException as exc:
        output += f"Docker error: {exc}\n"
        passed = False
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except DockerException:
                pass

    result = TestResult(passed=passed, output=output[-8000:], attempt_number=attempt)
    return {
        "test_results": [*state.test_results, result],
        "retry_count": attempt,
        "needs_manual_review": (not passed) and attempt >= state.max_retries,
        "current_stage": "sandbox_test",
    }
