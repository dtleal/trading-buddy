"""Use cases for the Q&A knowledge base: list, create, update, delete.

These wrap a `QARepository` and own the small amount of domain logic the
persistence layer should not care about: trimming input, rejecting empty
questions/answers, and normalising tags (trim, lowercase, de-dupe, keep order).
"""

from __future__ import annotations

from core.interfaces import QARepository
from core.models import QAEntry


class QAValidationError(ValueError):
    """Raised when a question or answer is empty after trimming."""


def _clean_text(value: str, *, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise QAValidationError(f"{field} não pode ficar vazio.")
    return cleaned


def _normalise_tags(tags: list[str]) -> list[str]:
    """Trim, lowercase, drop blanks, de-dupe while preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in tags:
        tag = raw.strip().lower()
        if tag and tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


class ListQAEntriesUseCase:
    """Return every saved Q&A entry, most recently updated first."""

    def __init__(self, repository: QARepository) -> None:
        self._repository = repository

    async def execute(self) -> list[QAEntry]:
        return await self._repository.list_entries()


class CreateQAEntryUseCase:
    """Persist a new Q&A entry after validating and normalising its fields."""

    def __init__(self, repository: QARepository) -> None:
        self._repository = repository

    async def execute(self, *, question: str, answer: str, tags: list[str]) -> QAEntry:
        return await self._repository.create_entry(
            question=_clean_text(question, field="Pergunta"),
            answer=_clean_text(answer, field="Resposta"),
            tags=_normalise_tags(tags),
        )


class UpdateQAEntryUseCase:
    """Update an existing entry. Returns None when the id does not exist."""

    def __init__(self, repository: QARepository) -> None:
        self._repository = repository

    async def execute(
        self, entry_id: int, *, question: str, answer: str, tags: list[str]
    ) -> QAEntry | None:
        return await self._repository.update_entry(
            entry_id,
            question=_clean_text(question, field="Pergunta"),
            answer=_clean_text(answer, field="Resposta"),
            tags=_normalise_tags(tags),
        )


class DeleteQAEntryUseCase:
    """Delete an entry by id. Returns False when the id does not exist."""

    def __init__(self, repository: QARepository) -> None:
        self._repository = repository

    async def execute(self, entry_id: int) -> bool:
        return await self._repository.delete_entry(entry_id)


__all__ = [
    "QAValidationError",
    "ListQAEntriesUseCase",
    "CreateQAEntryUseCase",
    "UpdateQAEntryUseCase",
    "DeleteQAEntryUseCase",
]
