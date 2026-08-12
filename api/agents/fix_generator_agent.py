"""Fix generator agent: rewrite whole files via LLM (no snippet matching)."""

from __future__ import annotations

import ast
import builtins
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from api.agents.llm import call_structured
from api.schemas import FilePatch, GraphState, ProposedFix

_BUILTIN_NAMES = set(dir(builtins)) | {"True", "False", "None"}


class FileRewriteLLM(BaseModel):
    file_path: str = Field(description="Repo-relative path to overwrite")
    content: str = Field(description="Complete new file contents after the fix")


class FixLLMResult(BaseModel):
    files: list[FileRewriteLLM] = Field(
        description="One or more full-file rewrites that together fix the bug"
    )
    explanation: str = Field(description="Why this set of changes resolves the bug")


def _strip_line_prefixes(block: str) -> str:
    cleaned: list[str] = []
    for line in block.splitlines():
        match = re.match(r"^\s*\d+\|\s?(.*)$", line)
        cleaned.append(match.group(1) if match else line)
    return "\n".join(cleaned)


def _read_repo_file(repo: Path, rel: str) -> str:
    path = repo / rel
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _caller_files(state: GraphState) -> list[tuple[str, str]]:
    if not state.repo_path or not state.code_location:
        return []
    repo = Path(state.repo_path)
    func = state.code_location.function_name
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(rel: str) -> None:
        if rel in seen or (state.code_location and rel == state.code_location.file_path):
            return
        text = _read_repo_file(repo, rel)
        if text:
            found.append((rel, text))
            seen.add(rel)

    add("routers/triggers.py")
    add("services.py")
    add("utils.py")

    if func:
        for path in repo.rglob("*.py"):
            if ".git" in path.parts:
                continue
            rel = path.relative_to(repo).as_posix()
            if rel in seen or rel == state.code_location.file_path:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if func in text:
                found.append((rel, text))
                seen.add(rel)
            if len(found) >= 6:
                break
    return found


def _caller_context(callers: list[tuple[str, str]]) -> str:
    if not callers:
        return ""
    chunks = [f"--- {rel} ---\n{text}" for rel, text in callers]
    return (
        "\n\nRelated files (include additional full-file rewrites when the fix "
        "spans callers/routes):\n" + "\n\n".join(chunks)
    )


def _clean_file_content(text: str) -> str:
    """Strip markdown fences; keep the rest intact (including leading indent)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    body = "\n".join(lines)
    if body and not body.endswith("\n"):
        body += "\n"
    return body


def _module_defined_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names


def _validate_file_content(after: str) -> None:
    try:
        tree = ast.parse(after)
    except SyntaxError as exc:
        raise ValueError(f"Rewritten file has syntax error: {exc}") from exc

    defined = _module_defined_names(tree) | _BUILTIN_NAMES
    raised: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            func = node.exc.func
            if isinstance(func, ast.Name):
                raised.add(func.id)
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Name):
            raised.add(node.exc.id)

    undefined = sorted(n for n in raised if n not in defined)
    if undefined:
        raise ValueError(
            "File raises undefined name(s): "
            + ", ".join(undefined)
            + ". Define them in the same file or use HTTPException/ValueError."
        )


def _validate_rewrites(
    repo: Path | None,
    rewrites: list[FileRewriteLLM],
    allowed: set[str],
) -> list[FilePatch]:
    if not rewrites:
        raise ValueError("files list is empty")

    validated: list[FilePatch] = []
    seen_paths: set[str] = set()
    for item in rewrites:
        rel = item.file_path.replace("\\", "/").lstrip("./")
        if rel not in allowed:
            raise ValueError(f"file_path '{rel}' is not in allowed set {sorted(allowed)}")
        if rel in seen_paths:
            raise ValueError(f"duplicate file_path '{rel}'")
        seen_paths.add(rel)

        content = _clean_file_content(item.content)
        if not content.strip():
            raise ValueError(f"empty content for {rel}")

        before = _read_repo_file(repo, rel) if repo else ""
        if not before:
            raise ValueError(f"cannot read target file {rel}")
        if content == before:
            raise ValueError(f"no-op rewrite for {rel} (content unchanged)")

        _validate_file_content(content)
        validated.append(
            FilePatch(
                file_path=rel,
                content=content,
                original_code=before,
                fixed_code=content,
            )
        )
    return validated


def _ask_for_fix(
    *,
    state: GraphState,
    primary_source: str,
    caller_ctx: str,
    allowed_files: set[str],
    extra_feedback: str = "",
) -> FixLLMResult:
    loc = state.code_location
    report = state.bug_report
    cause = state.root_cause
    assert loc is not None and cause is not None

    retry_context = ""
    if state.retry_count > 0 and state.test_results:
        last = state.test_results[-1]
        retry_context = (
            f"\n\nThis is retry attempt #{state.retry_count}. "
            f"Previous sandbox output:\n{last.output[:3000]}\n"
            "Provide a COMPLETE multi-file rewrite if needed."
        )

    return call_structured(
        system=(
            "You are a careful Python/FastAPI engineer.\n"
            "Return the FULL new contents of every file you change — do NOT return "
            "snippets, diffs, or search/replace pairs.\n"
            "CRITICAL SCOPE RULES:\n"
            "1) Fix ONLY the single reported exception / failing trigger endpoint.\n"
            "2) Do NOT fix other bugs, even if you see comments like "
            "'BUG 1', 'BUG 2', 'BUG 3', 'intentionally buggy', or missing awaits "
            "in unrelated functions. Leave those other intentional defects untouched.\n"
            "3) Change the minimum code needed for THIS error. Prefer editing one "
            "function. Touch a second file only if the reported call chain requires it.\n"
            "4) Do not rewrite docstrings of unrelated functions just to 'clean them up'.\n"
            "5) `content` must be the entire file, ready to write to disk.\n"
            "6) Prefer ValueError / plain returns over inventing exception classes. "
            "HTTPException is OK only when it directly replaces the reported crash.\n"
            "7) After the change, the reported trigger must not return HTTP 500. "
            "Other triggers may still crash — that is expected.\n"
            "8) Only use allowed file paths. No markdown fences inside `content`."
        ),
        user=(
            f"Fix ONLY this incident — nothing else:\n"
            f"Error: {report.error_type}: {report.error_message}\n"
            f"Root cause ({cause.confidence}): {cause.hypothesis}\n"
            f"Primary file: {loc.file_path} @ line {loc.line_number} "
            f"({loc.function_name})\n"
            f"Triggered endpoint: {state.triggered_endpoint}\n"
            f"Allowed file_path values: {sorted(allowed_files)}\n\n"
            f"Reminder: other functions in these files may contain SEPARATE "
            f"intentional bugs. Do not repair them.\n\n"
            f"CURRENT full contents of {loc.file_path}:\n"
            f"```python\n{primary_source}\n```"
            f"{caller_ctx}"
            f"{retry_context}"
            f"{extra_feedback}"
        ),
        schema=FixLLMResult,
        trace_name="fix_generator_agent",
    )


def fix_generator_agent(state: GraphState) -> dict[str, Any]:
    """Generate full-file rewrites, validate syntax, return ProposedFix."""
    if state.code_location is None or state.root_cause is None:
        raise RuntimeError("code_location and root_cause are required")

    loc = state.code_location
    repo = Path(state.repo_path) if state.repo_path else None
    primary_source = (
        _read_repo_file(repo, loc.file_path)
        if repo
        else _strip_line_prefixes(loc.surrounding_code)
    )
    if not primary_source:
        primary_source = _strip_line_prefixes(loc.surrounding_code)

    callers = _caller_files(state)
    caller_ctx = _caller_context(callers)
    allowed_files = {loc.file_path, *(rel for rel, _ in callers)}

    feedback = ""
    last_error = "unknown"
    for _ in range(3):
        try:
            result = _ask_for_fix(
                state=state,
                primary_source=primary_source,
                caller_ctx=caller_ctx,
                allowed_files=allowed_files,
                extra_feedback=feedback,
            )
            patches = _validate_rewrites(repo, result.files, allowed_files)
            return {
                "proposed_fix": ProposedFix(
                    files=patches,
                    explanation=result.explanation,
                ),
                "current_stage": "fix_generator",
            }
        except Exception as exc:
            last_error = str(exc)
            feedback = (
                f"\n\nPrevious proposal REJECTED by validation:\n{last_error}\n"
                "Return complete file contents again (full files, not snippets)."
            )

    return {
        "proposed_fix": ProposedFix(
            files=[],
            explanation=f"LLM fix generation failed: {last_error}",
        ),
        "current_stage": "fix_generator",
    }
