"""PostgreSQL repository for Q&A entries: implements `core.interfaces.QARepository`.

Kept separate from `db_postgres.PostgresSnapshotRepository` because the Q&A
knowledge base is an independent concern (user-curated CRUD) from the
append-only market time-series. It owns its own async engine so it can be
constructed and disposed on its own lifecycle (see `api/app.py`).
"""

from __future__ import annotations

import logging
from typing import cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.models import QAEntry
from db.schema import QAEntryRow

logger = logging.getLogger(__name__)


class PostgresQARepository:
    """CRUD over the `qa_entries` table."""

    def __init__(self, dsn: str) -> None:
        self._engine = create_async_engine(dsn, pool_size=5, max_overflow=5, future=True)
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    @staticmethod
    def _to_entry(row: QAEntryRow) -> QAEntry:
        return QAEntry(
            id=row.id,
            question=row.question,
            answer=row.answer,
            tags=list(row.tags or []),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def list_entries(self) -> list[QAEntry]:
        async with self._sessionmaker() as session:
            stmt = select(QAEntryRow).order_by(QAEntryRow.updated_at.desc())
            result = await session.execute(stmt)
            return [self._to_entry(row) for row in result.scalars().all()]

    async def get_entry(self, entry_id: int) -> QAEntry | None:
        async with self._sessionmaker() as session:
            row = await session.get(QAEntryRow, entry_id)
            return self._to_entry(row) if row is not None else None

    async def create_entry(self, *, question: str, answer: str, tags: list[str]) -> QAEntry:
        async with self._sessionmaker() as session, session.begin():
            row = QAEntryRow(question=question, answer=answer, tags=tags)
            session.add(row)
            await session.flush()
            return self._to_entry(row)

    async def update_entry(
        self, entry_id: int, *, question: str, answer: str, tags: list[str]
    ) -> QAEntry | None:
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(QAEntryRow, entry_id)
            if row is None:
                return None
            row.question = question
            row.answer = answer
            row.tags = tags
            await session.flush()
            # `updated_at` is set server-side via onupdate=now(); reload it so
            # the returned entry carries the fresh timestamp instead of a value
            # SQLAlchemy expired (which would trigger sync IO outside greenlet).
            await session.refresh(row)
            return self._to_entry(row)

    async def delete_entry(self, entry_id: int) -> bool:
        async with self._sessionmaker() as session, session.begin():
            result = cast(
                CursorResult[object],
                await session.execute(delete(QAEntryRow).where(QAEntryRow.id == entry_id)),
            )
            return result.rowcount > 0

    async def close(self) -> None:
        await self._engine.dispose()
