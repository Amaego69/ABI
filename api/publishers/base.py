"""Abstract PR publisher interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from api.schemas import PRResult


class PRPublisher(ABC):
    @abstractmethod
    def create_branch(self, base: str, branch_name: str) -> None: ...

    @abstractmethod
    def commit_and_push(
        self,
        branch_name: str,
        file_path: str,
        content: str,
        message: str,
    ) -> None: ...

    def commit_and_push_files(
        self,
        branch_name: str,
        files: dict[str, str],
        message: str,
    ) -> None:
        """Commit multiple file updates. Default: one commit per file."""
        for path, content in files.items():
            self.commit_and_push(
                branch_name=branch_name,
                file_path=path,
                content=content,
                message=message,
            )

    @abstractmethod
    def open_pr(self, branch_name: str, title: str, body: str) -> PRResult: ...
