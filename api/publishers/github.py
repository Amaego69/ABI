"""GitHub implementation of PRPublisher via PyGithub."""

from __future__ import annotations

from github import Github, GithubException, InputGitTreeElement

from api.config import get_settings
from api.publishers.base import PRPublisher
from api.schemas import PRResult


class GitHubPublisher(PRPublisher):
    """Publishes branches/commits/PRs to the repo configured via env."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.github_token:
            raise ValueError("GITHUB_TOKEN is required for GitHubPublisher")
        if not settings.github_repo_owner or not settings.github_repo_name:
            raise ValueError("GITHUB_REPO_OWNER and GITHUB_REPO_NAME are required")

        self._settings = settings
        self._gh = Github(settings.github_token)
        self._repo = self._gh.get_repo(
            f"{settings.github_repo_owner}/{settings.github_repo_name}"
        )

    def _resolve_base(self, base: str) -> str:
        try:
            self._repo.get_git_ref(f"heads/{base}")
            return base
        except GithubException:
            alt = "master" if base == "main" else "main"
            self._repo.get_git_ref(f"heads/{alt}")
            return alt

    def create_branch(self, base: str, branch_name: str) -> None:
        resolved = self._resolve_base(base)
        base_ref = self._repo.get_git_ref(f"heads/{resolved}")
        sha = base_ref.object.sha
        try:
            self._repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sha)
        except GithubException as exc:
            if getattr(exc, "status", None) != 422:
                raise

    def _upsert_file(
        self,
        branch_name: str,
        file_path: str,
        content: str,
        message: str,
    ) -> None:
        try:
            existing = self._repo.get_contents(file_path, ref=branch_name)
            if isinstance(existing, list):
                raise IsADirectoryError(file_path)
            self._repo.update_file(
                path=file_path,
                message=message,
                content=content,
                sha=existing.sha,
                branch=branch_name,
            )
        except GithubException as exc:
            if getattr(exc, "status", None) == 404:
                self._repo.create_file(
                    path=file_path,
                    message=message,
                    content=content,
                    branch=branch_name,
                )
            else:
                raise

    def commit_and_push(
        self,
        branch_name: str,
        file_path: str,
        content: str,
        message: str,
    ) -> None:
        self.commit_and_push_files(
            branch_name=branch_name,
            files={file_path: content},
            message=message,
        )

    def commit_and_push_files(
        self,
        branch_name: str,
        files: dict[str, str],
        message: str,
    ) -> None:
        if not files:
            return
        if len(files) == 1:
            path, content = next(iter(files.items()))
            self._upsert_file(branch_name, path, content, message)
            return

        # Multi-file atomic commit — PyGithub requires InputGitTreeElement, not dicts
        ref = self._repo.get_git_ref(f"heads/{branch_name}")
        base_commit = self._repo.get_git_commit(ref.object.sha)
        elements: list[InputGitTreeElement] = []
        for path, content in files.items():
            blob = self._repo.create_git_blob(content, "utf-8")
            elements.append(
                InputGitTreeElement(
                    path=path,
                    mode="100644",
                    type="blob",
                    sha=blob.sha,
                )
            )
        tree = self._repo.create_git_tree(elements, base_commit.tree)
        commit = self._repo.create_git_commit(message, tree, [base_commit])
        ref.edit(commit.sha)

    def open_pr(self, branch_name: str, title: str, body: str) -> PRResult:
        base = self._resolve_base("main")
        try:
            pr = self._repo.create_pull(
                title=title,
                body=body,
                head=branch_name,
                base=base,
            )
            return PRResult(
                branch_name=branch_name,
                pr_url=pr.html_url,
                pr_number=pr.number,
                status="created",
            )
        except GithubException as exc:
            if getattr(exc, "status", None) == 422:
                pulls = self._repo.get_pulls(
                    state="open",
                    head=f"{self._repo.owner.login}:{branch_name}",
                )
                for pr in pulls:
                    return PRResult(
                        branch_name=branch_name,
                        pr_url=pr.html_url,
                        pr_number=pr.number,
                        status="created",
                    )
            return PRResult(
                branch_name=branch_name,
                pr_url=None,
                pr_number=None,
                status="failed",
            )


def get_publisher() -> PRPublisher:
    """Factory used by the API layer — swap here for GiteaPublisher later."""
    return GitHubPublisher()
