"""Performance REST surface (the Performance tab).

One endpoint: `GET /api/performance` returns the whole report for a filter
selection — summary numbers, equity/drawdown curve, day/week/month buckets,
breakdowns (asset, origin, side, weekday, hour) and the trade list.

The trades themselves come from the collector's `trade_history` push (handled
in `api/routes/orderflow.py`, which owns the ingest socket) and live in the
`TradeHistory` store below, shared by both modules.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status

from adapters.trade_history import TradeHistory
from core.models import PerformanceReport
from settings import get_settings
from use_cases.compute_performance import compute_performance

router = APIRouter(tags=["performance"])


def _build_store() -> TradeHistory:
    """Closed-trade store — persisted to JSON unless the directory is empty."""
    raw = get_settings().trade_history_dir.strip()
    return TradeHistory(Path(raw) if raw else None)


# Process-wide singleton: the order-flow ingest handler writes it, this route
# reads it (API and ingest share one process, like the other stores).
trade_history = _build_store()


# Ready-made windows for the UI buttons ("all" = every trade the backend holds).
Preset = Literal["today", "week", "month", "last_month", "7d", "30d", "90d", "all"]


def _resolve_window(
    preset: Preset | None, start: str | None, end: str | None, now: datetime
) -> tuple[datetime | None, datetime | None]:
    """Turn a preset (or explicit ISO dates) into a UTC window.

    An explicit `start`/`end` always wins. A date without a time means the whole
    day: `start` opens at 00:00 and `end` closes at 23:59:59.999.
    """
    if start or end:
        return _parse_bound(start, end_of_day=False), _parse_bound(end, end_of_day=True)
    if preset is None or preset == "all":
        return None, None
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if preset == "today":
        return today, None
    if preset == "week":  # current ISO week (Monday-based)
        return today - timedelta(days=today.weekday()), None
    if preset == "month":
        return today.replace(day=1), None
    if preset == "last_month":
        this_month = today.replace(day=1)
        prev_month = (this_month - timedelta(days=1)).replace(day=1)
        return prev_month, this_month - timedelta(microseconds=1)
    days = {"7d": 7, "30d": 30, "90d": 90}[preset]
    return now - timedelta(days=days), None


def _parse_bound(raw: str | None, *, end_of_day: bool) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"data inválida: {raw} (use YYYY-MM-DD ou ISO 8601)",
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    date_only = len(raw) <= 10
    if end_of_day and date_only:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed


@router.get("/api/performance", response_model=PerformanceReport, tags=["performance"])
async def get_performance(
    preset: Preset | None = Query(
        None,
        description=(
            "Janela pronta: today, week (semana atual), month (mês atual), "
            "last_month, 7d, 30d, 90d, all. Ignorada quando start/end vêm."
        ),
    ),
    start: str | None = Query(None, description="Início (YYYY-MM-DD ou ISO 8601, UTC)"),
    end: str | None = Query(None, description="Fim (YYYY-MM-DD ou ISO 8601, UTC)"),
    symbols: str | None = Query(None, description="Ativos separados por vírgula (vazio = todos)"),
    source: Literal["all", "manual", "bot"] = Query("all", description="Origem das operações"),
    trades_limit: int = Query(500, ge=1, le=5000, description="Máximo de trades na lista"),
) -> PerformanceReport:
    """Performance of the closed trades the backend holds, for one filter
    selection. Empty (all-zero) until the collector's first `trade_history`
    push."""
    window_start, window_end = _resolve_window(preset, start, end, datetime.now(timezone.utc))
    asof = None
    if trade_history.asof:
        try:
            asof = datetime.fromisoformat(trade_history.asof)
        except ValueError:  # collector sent something odd — not worth failing on
            asof = None
    return compute_performance(
        trade_history.snapshot(),
        account_balance=trade_history.balance,
        cash_flows=trade_history.cash_flows(),
        start=window_start,
        end=window_end,
        symbols=symbols.split(",") if symbols else None,
        source=source,
        trades_limit=trades_limit,
        currency=trade_history.currency,
        asof=asof,
    )
