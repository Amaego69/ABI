"""Locator agent: find the exact fault site in the cloned repo and extract context."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from api.agents.llm import call_structured
from api.schemas import CodeLocation, GraphState


class LocatorDecision(BaseModel):
    file_path: str
    function_name: str | None = None
    line_number: int | None = None
    rationale: str = ""


def _read_file(repo_path: Path, rel_path: str) -> str:
    target = (repo_path / rel_path).resolve()
    if not str(target).startswith(str(repo_path.resolve())):
        raise ValueError(f"Path escapes repo root: {rel_path}")
    return target.read_text(encoding="utf-8")


def _grep_repo(repo_path: Path, pattern: str, max_hits: int = 40) -> str:
    """Search the repo with ripgrep if available, else a recursive Python walk."""
    try:
        result = subprocess.run(
            ["rg", "-n", "--no-heading", "-S", pattern, str(repo_path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        return "\n".join(lines[:max_hits])
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    hits: list[str] = []
    regex = re.compile(pattern)
    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.parts):
            continue
        if path.suffix not in {".py", ".md", ".txt", ".toml", ".cfg", ".ini"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                rel = path.relative_to(repo_path).as_posix()
                hits.append(f"{rel}:{i}:{line}")
                if len(hits) >= max_hits:
                    return "\n".join(hits)
    return "\n".join(hits)


def _resolve_repo_file(repo_path: Path, candidate: str | None) -> str | None:
    """Resolve a traceback/LLM path to a repo-relative file that exists."""
    if not candidate:
        return None
    normalized = candidate.replace("\\", "/").lstrip("./")
    # Already repo-relative
    if (repo_path / normalized).is_file():
        return normalized
    # Absolute / container path — try suffix match against known files
    name = Path(normalized).name
    if name:
        matches = [
            p.relative_to(repo_path).as_posix()
            for p in repo_path.rglob(name)
            if p.is_file() and ".git" not in p.parts
        ]
        if len(matches) == 1:
            return matches[0]
        # Prefer shorter / top-level paths
        if matches:
            matches.sort(key=lambda m: (m.count("/"), len(m)))
            return matches[0]
    # Try last N path segments
    parts = [p for p in normalized.split("/") if p]
    for n in range(min(3, len(parts)), 0, -1):
        tail = "/".join(parts[-n:])
        if (repo_path / tail).is_file():
            return tail
    return None


def _surrounding_code(source: str, line_number: int | None, radius: int = 15) -> str:
    lines = source.splitlines()
    if not lines:
        return ""
    if line_number is None:
        # Return whole file if small, else first 60 lines
        return "\n".join(lines[:60])
    idx = max(1, min(line_number, len(lines)))
    start = max(1, idx - radius)
    end = min(len(lines), idx + radius)
    numbered = [f"{i:>4}| {lines[i - 1]}" for i in range(start, end + 1)]
    return "\n".join(numbered)


def _extract_function_block(source: str, line_number: int | None) -> tuple[str | None, str]:
    """Best-effort: find enclosing def/async def and return (name, block with context)."""
    lines = source.splitlines()
    if not lines:
        return None, ""
    if line_number is None:
        return None, _surrounding_code(source, None)

    idx = max(1, min(int(line_number), len(lines))) - 1
    idx = max(0, min(idx, len(lines) - 1))

    func_name = None
    start = idx
    for i in range(idx, -1, -1):
        match = re.match(r"^(async\s+def|def)\s+([A-Za-z_]\w*)\s*\(", lines[i])
        if match:
            func_name = match.group(2)
            start = i
            break

    # Expand a bit above the def for decorators
    deco_start = start
    while deco_start > 0 and lines[deco_start - 1].lstrip().startswith("@"):
        deco_start -= 1

    # Walk forward until dedent to column 0 at another top-level def/class
    end = start
    base_indent = len(lines[start]) - len(lines[start].lstrip())
    for j in range(start + 1, len(lines)):
        raw = lines[j]
        if not raw.strip():
            end = j
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent <= base_indent and re.match(r"^(async\s+def|def|class)\s+", raw):
            break
        end = j

    # Include a few lines of outer context
    ctx_start = max(0, deco_start - 3)
    ctx_end = min(len(lines) - 1, end + 3)
    block = "\n".join(
        f"{i + 1:>4}| {lines[i]}" for i in range(ctx_start, ctx_end + 1)
    )
    return func_name, block


def locator_agent(state: GraphState) -> dict[str, Any]:
    """Locate the buggy code in the cloned repository and extract surrounding context."""
    if not state.repo_path:
        raise RuntimeError("repo_path is missing — run repo_fetch_agent first")

    repo = Path(state.repo_path)
    report = state.bug_report
    hint_path = _resolve_repo_file(
        repo,
        report.file_path
        or (state.code_location.file_path if state.code_location else None),
    )
    hint_line = report.line_number or (
        state.code_location.line_number if state.code_location else None
    )

    file_preview = ""
    if hint_path:
        file_preview = _read_file(repo, hint_path)

    grep_query = report.error_type or report.error_message or "Error"
    grep_hits = _grep_repo(repo, re.escape(grep_query) if grep_query else "def ")

    # Also grep for the function name if known
    if report.function_name:
        grep_hits += "\n" + _grep_repo(repo, rf"def\s+{re.escape(report.function_name)}\b")

    try:
        decision = call_structured(
            system=(
                "You are a code locator agent. Given a traceback summary and repository "
                "search results, choose the single most likely file_path (repo-relative), "
                "function_name, and line_number where the bug lives. "
                "file_path must be relative to the repo root (e.g. utils.py or routers/triggers.py)."
            ),
            user=(
                f"Error type: {report.error_type}\n"
                f"Error message: {report.error_message}\n"
                f"Traceback hint file: {hint_path}\n"
                f"Traceback hint line: {hint_line}\n"
                f"Hint function: {report.function_name}\n\n"
                f"Grep hits:\n{grep_hits[:4000]}\n\n"
                f"File preview (may be empty):\n{file_preview[:4000]}\n\n"
                f"Raw traceback (truncated):\n{report.raw_traceback[:3000]}"
            ),
            schema=LocatorDecision,
            trace_name="locator_agent",
        )
    except Exception:
        decision = LocatorDecision(
            file_path=hint_path or "main.py",
            function_name=report.function_name,
            line_number=hint_line,
            rationale="fallback from triage hints",
        )

    rel = (
        _resolve_repo_file(repo, decision.file_path)
        or hint_path
        or _resolve_repo_file(repo, "main.py")
        or decision.file_path.replace("\\", "/")
    )

    source = ""
    if (repo / rel).is_file():
        source = _read_file(repo, rel)
    line_no = decision.line_number or hint_line
    # Clamp hallucinated line numbers to the real file
    if source and line_no is not None:
        line_count = len(source.splitlines()) or 1
        if line_no < 1 or line_no > line_count:
            line_no = hint_line if hint_line and 1 <= hint_line <= line_count else min(
                max(line_no, 1), line_count
            )
    func_name, block = _extract_function_block(source, line_no)
    if not block:
        block = _surrounding_code(source, line_no)
    if not block and not source:
        block = f"# File not found in repo clone: {rel}"

    location = CodeLocation(
        file_path=rel,
        function_name=func_name or decision.function_name or report.function_name,
        line_number=line_no,
        surrounding_code=block,
    )

    return {
        "code_location": location,
        "current_stage": "locator",
    }
