"""PostgreSQL repository for the scalper bot's trade history.

Append-only log of the bot's own executions (opens/closes) for future
performance analysis. Owns its own async engine/lifecycle, like the other
repositories. Manual trades are never written — only the bot's `_run_bot`
path and bot `open_result`s call `record`.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.models import BotTrade
from db.schema import BotTradeRow

logger = logging.getLogger(__name__)


class PostgresBotTradeRepository:
    """Append + recent-read over the `bot_trades` table."""

    def __init__(self, dsn: str) -> None:
        self._engine = create_async_engine(dsn, pool_size=2, max_overflow=3, future=True)
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    async def record(
        self,
        *,
        kind: str,
        symbol: str,
        side: str | None = None,
        lots: float | None = None,
        ticket: int | None = None,
        price: float | None = None,
        pnl: float | None = None,
        reason: str | None = None,
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            session.add(
                BotTradeRow(
                    kind=kind,
                    symbol=symbol,
                    side=side,
                    lots=lots,
                    ticket=ticket,
                    price=price,
                    pnl=pnl,
                    reason=reason,
                )
            )

    async def list_recent(self, limit: int = 200) -> list[BotTrade]:
        async with self._sessionmaker() as session:
            stmt = select(BotTradeRow).order_by(BotTradeRow.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            return [
                BotTrade(
                    id=row.id,
                    kind=row.kind,  # type: ignore[arg-type]
                    symbol=row.symbol,
                    side=row.side,
                    lots=row.lots,
                    ticket=row.ticket,
                    price=row.price,
                    pnl=row.pnl,
                    reason=row.reason,
                    created_at=row.created_at,
                )
                for row in result.scalars().all()
            ]

    async def close(self) -> None:
        await self._engine.dispose()
