"""Environment-backed settings for the Bug Investigator API."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    github_token: str = ""
    github_repo_owner: str = ""
    github_repo_name: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    runs_root: str = "/tmp/runs"
    sandbox_image: str = "bug-investigator-sandbox:latest"
    sandbox_timeout_sec: int = 120
    sandbox_mem_limit: str = "512m"
    sandbox_nano_cpus: int = 1_000_000_000  # 1 CPU
    buggy_app_base_url: str = "http://127.0.0.1:8001"
    require_pr_approval: bool = True
    auto_create_pr: bool = False
    # Absolute path on the Docker *host* that mirrors RUNS_ROOT inside the api
    # container. Required when api uses docker.sock to mount clone dirs into sandboxes.
    sandbox_bind_root: str = ""

    @property
    def github_clone_url(self) -> str:
        if not (self.github_token and self.github_repo_owner and self.github_repo_name):
            raise ValueError(
                "GITHUB_TOKEN, GITHUB_REPO_OWNER, and GITHUB_REPO_NAME must be set"
            )
        return (
            f"https://{self.github_token}@github.com/"
            f"{self.github_repo_owner}/{self.github_repo_name}.git"
        )

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    def host_path_for_sandbox(self, container_path: str) -> str:
        """Map an in-container runs path to the host path Docker daemon can bind."""
        if not self.sandbox_bind_root:
            return container_path
        container = container_path.replace("\\", "/").rstrip("/")
        runs = self.runs_root.replace("\\", "/").rstrip("/")
        bind_root = self.sandbox_bind_root.replace("\\", "/").rstrip("/")
        if container == runs:
            return bind_root
        prefix = runs + "/"
        if container.startswith(prefix):
            return f"{bind_root}/{container[len(prefix):]}"
        return container_path.replace("\\", "/")


# Friendly UI labels -> Anthropic API model ids
_MODEL_ALIASES = {
    "claude sonnet 5": "claude-sonnet-5",
    "sonnet 5": "claude-sonnet-5",
    "claude sonnet 4": "claude-sonnet-4-6",
    "claude sonnet 4.6": "claude-sonnet-4-6",
    "sonnet 4.6": "claude-sonnet-4-6",
}


def normalize_anthropic_model(name: str) -> str:
    """Map display names like 'Claude Sonnet 5' to API ids like 'claude-sonnet-5'."""
    raw = (name or "").strip()
    if not raw:
        return "claude-sonnet-5"
    return _MODEL_ALIASES.get(raw.lower(), raw)


def get_settings() -> Settings:
    return Settings(
        github_token=os.getenv("GITHUB_TOKEN", ""),
        github_repo_owner=os.getenv("GITHUB_REPO_OWNER", ""),
        github_repo_name=os.getenv("GITHUB_REPO_NAME", ""),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        anthropic_model=normalize_anthropic_model(
            os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
        ),
        langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
        langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
        langfuse_host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        runs_root=os.getenv("RUNS_ROOT", "/tmp/runs"),
        sandbox_image=os.getenv("SANDBOX_IMAGE", "bug-investigator-sandbox:latest"),
        sandbox_timeout_sec=int(os.getenv("SANDBOX_TIMEOUT_SEC", "120")),
        sandbox_mem_limit=os.getenv("SANDBOX_MEM_LIMIT", "512m"),
        sandbox_nano_cpus=int(os.getenv("SANDBOX_NANO_CPUS", "1000000000")),
        buggy_app_base_url=os.getenv("BUGGY_APP_BASE_URL", "http://127.0.0.1:8001"),
        require_pr_approval=os.getenv("REQUIRE_PR_APPROVAL", "true").lower()
        in {"1", "true", "yes"},
        auto_create_pr=os.getenv("AUTO_CREATE_PR", "false").lower()
        in {"1", "true", "yes"},
        sandbox_bind_root=os.getenv("SANDBOX_BIND_ROOT", ""),
    )
