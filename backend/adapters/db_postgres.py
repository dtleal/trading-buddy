"""PostgreSQL repository: implements `core.interfaces.SnapshotRepository`."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone
from typing import cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.enums import LLMOutputKind
from core.models import (
    BiasReport,
    EconomicEvent,
    LLMOutput,
    MarketSnapshot,
    NewsItem,
)
from db.schema import (
    BiasReportRow,
    EconomicEventRow,
    LLMOutputRow,
    MarketSnapshotRow,
    NewsItemRow,
)

logger = logging.getLogger(__name__)


class PostgresSnapshotRepository:
    """All writes are append-only / upsert by natural key."""

    def __init__(self, dsn: str) -> None:
        self._engine = create_async_engine(dsn, pool_size=5, max_overflow=5, future=True)
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    # -- Writes ----------------------------------------------------------

    async def save_market_snapshot(self, snapshot: MarketSnapshot) -> None:
        async with self._sessionmaker() as session, session.begin():
            for symbol, quote in snapshot.assets.items():
                session.add(
                    MarketSnapshotRow(
                        symbol=symbol.value,
                        timestamp=quote.timestamp,
                        price=quote.price,
                        ma200_d=quote.ma200_d,
                        ma200_h4=quote.ma200_h4,
                        change_pct=quote.change_pct,
                    )
                )
            session.add(
                MarketSnapshotRow(
                    symbol="VIX",
                    timestamp=snapshot.timestamp,
                    price=snapshot.vix.vix,
                )
            )

    async def save_bias_reports(self, reports: list[BiasReport]) -> None:
        async with self._sessionmaker() as session, session.begin():
            for report in reports:
                session.add(
                    BiasReportRow(
                        asset=report.asset.value,
                        timestamp=report.timestamp,
                        score=report.score,
                        level=report.level.value,
                        components=report.components.model_dump(),
                        rationale=report.rationale,
                    )
                )

    async def save_events(self, events: list[EconomicEvent]) -> None:
        if not events:
            return
        async with self._sessionmaker() as session, session.begin():
            for event in events:
                stmt = (
                    pg_insert(EconomicEventRow)
                    .values(
                        name=event.name,
                        currency=event.currency,
                        impact=event.impact.value,
                        scheduled_at=event.scheduled_at,
                        forecast=event.forecast,
                        previous=event.previous,
                        actual=event.actual,
                        source=event.source,
                    )
                    .on_conflict_do_update(
                        index_elements=["name", "scheduled_at"],
                        set_={
                            "forecast": event.forecast,
                            "previous": event.previous,
                            "actual": event.actual,
                            "impact": event.impact.value,
                        },
                    )
                )
                await session.execute(stmt)

    async def save_news(self, items: list[NewsItem]) -> None:
        if not items:
            return
        async with self._sessionmaker() as session, session.begin():
            for item in items:
                stmt = (
                    pg_insert(NewsItemRow)
                    .values(
                        headline=item.headline,
                        source=item.source,
                        url=item.url,
                        published_at=item.published_at,
                        summary=item.summary,
                        sentiment_label=(
                            item.sentiment_label.value if item.sentiment_label else None
                        ),
                        sentiment_score=item.sentiment_score,
                    )
                    .on_conflict_do_update(
                        index_elements=["url"],
                        set_={
                            "sentiment_label": (
                                item.sentiment_label.value if item.sentiment_label else None
                            ),
                            "sentiment_score": item.sentiment_score,
                        },
                    )
                )
                await session.execute(stmt)

    async def save_llm_output(self, output: LLMOutput) -> None:
        async with self._sessionmaker() as session, session.begin():
            session.add(
                LLMOutputRow(
                    kind=output.kind.value,
                    model=output.model,
                    prompt_hash=output.prompt_hash,
                    content=output.content,
                    meta=output.metadata,
                    created_at=output.created_at,
                )
            )

    # -- Reads -----------------------------------------------------------

    async def latest_briefing_for(self, day: date) -> LLMOutput | None:
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = datetime.combine(day, time.max, tzinfo=timezone.utc)
        async with self._sessionmaker() as session:
            stmt = (
                select(LLMOutputRow)
                .where(
                    LLMOutputRow.kind == LLMOutputKind.BRIEFING.value,
                    LLMOutputRow.created_at >= start,
                    LLMOutputRow.created_at <= end,
                )
                .order_by(LLMOutputRow.created_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return LLMOutput(
                kind=LLMOutputKind(row.kind),
                model=row.model,
                prompt_hash=row.prompt_hash,
                content=row.content,
                created_at=row.created_at,
                metadata=cast(dict[str, object], row.meta) if row.meta else {},
            )

    async def close(self) -> None:
        await self._engine.dispose()
