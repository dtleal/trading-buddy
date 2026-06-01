"""REST endpoints for the Q&A knowledge base (CRUD).

The repository is built once at app startup and stored on `app.state` (see
`api/app.py`); each request reads it through the `_qa_repository` dependency so
we reuse a single connection pool instead of rebuilding the engine per call.
"""

from __future__ import annotations

import logging
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core.interfaces import QARepository
from core.models import QAEntry
from use_cases.manage_qa import (
    CreateQAEntryUseCase,
    DeleteQAEntryUseCase,
    ListQAEntriesUseCase,
    QAValidationError,
    UpdateQAEntryUseCase,
)

logger = logging.getLogger(__name__)


class QAEntryInput(BaseModel):
    """Create/update payload. `tags` are normalised server-side."""

    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)


def _qa_repository(request: Request) -> QARepository:
    repo = getattr(request.app.state, "qa_repository", None)
    if repo is None:  # pragma: no cover - only hit if lifespan didn't run
        raise HTTPException(status_code=503, detail="Q&A storage not ready")
    return cast(QARepository, repo)


router = APIRouter(prefix="/api/qa", tags=["qa"])


@router.get("", response_model=list[QAEntry])
async def list_qa(repo: QARepository = Depends(_qa_repository)) -> list[QAEntry]:
    return await ListQAEntriesUseCase(repo).execute()


@router.post("", response_model=QAEntry, status_code=201)
async def create_qa(payload: QAEntryInput, repo: QARepository = Depends(_qa_repository)) -> QAEntry:
    try:
        return await CreateQAEntryUseCase(repo).execute(
            question=payload.question, answer=payload.answer, tags=payload.tags
        )
    except QAValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{entry_id}", response_model=QAEntry)
async def update_qa(
    entry_id: int,
    payload: QAEntryInput,
    repo: QARepository = Depends(_qa_repository),
) -> QAEntry:
    try:
        updated = await UpdateQAEntryUseCase(repo).execute(
            entry_id, question=payload.question, answer=payload.answer, tags=payload.tags
        )
    except QAValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Q&A entry {entry_id} not found")
    return updated


@router.delete("/{entry_id}", status_code=204)
async def delete_qa(entry_id: int, repo: QARepository = Depends(_qa_repository)) -> None:
    deleted = await DeleteQAEntryUseCase(repo).execute(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Q&A entry {entry_id} not found")
