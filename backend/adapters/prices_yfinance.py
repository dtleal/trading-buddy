"""Yahoo Finance prices adapter.

`yfinance` is sync — calls are dispatched to a thread pool so the rest of the
service stays async.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, cast

import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

from core.models import IntradayBar, PriceQuote

logger = logging.getLogger(__name__)

# Map our internal symbols to Yahoo tickers.
YAHOO_TICKERS: dict[str, str] = {
    "USTEC": "^NDX",
    "SPX": "^GSPC",
    "GOLD": "GC=F",
    "VIX": "^VIX",
    "VIX9D": "^VIX9D",
    "VIX3M": "^VIX3M",
}


class YFinancePricesGateway:
    """Implements `core.interfaces.PricesGateway`."""

    def __init__(self) -> None:
        self._ticker_cache: dict[str, Any] = {}

    def _ticker(self, symbol: str) -> Any:
        yahoo = YAHOO_TICKERS.get(symbol, symbol)
        if yahoo not in self._ticker_cache:
            self._ticker_cache[yahoo] = yf.Ticker(yahoo)
        return self._ticker_cache[yahoo]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def _fetch_quote_sync(self, symbol: str) -> PriceQuote:
        ticker = self._ticker(symbol)
        info = ticker.fast_info
        price = float(info["last_price"]) if "last_price" in info else float(info["lastPrice"])
        prev_close = float(
            info.get("previous_close")
            or info.get("previousClose")
            or info.get("regularMarketPreviousClose")
            or price
        )
        change_pct = ((price - prev_close) / prev_close) * 100.0 if prev_close else None
        return PriceQuote(
            symbol=symbol,
            price=price,
            timestamp=datetime.now(timezone.utc),
            change_pct=change_pct,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def _fetch_ma200_sync(self, symbol: str, interval: str) -> float | None:
        ticker = self._ticker(symbol)
        period = "2y" if interval == "1d" else "60d"
        hist = ticker.history(period=period, interval=interval, auto_adjust=False)
        if hist is None or hist.empty or len(hist) < 200:
            return None
        ma200 = hist["Close"].rolling(window=200).mean().iloc[-1]
        return float(ma200) if ma200 == ma200 else None  # NaN check

    async def get_quote(self, symbol: str) -> PriceQuote:
        return await asyncio.to_thread(self._fetch_quote_sync, symbol)

    async def get_ma200(self, symbol: str, interval: str) -> float | None:
        return cast(
            float | None,
            await asyncio.to_thread(self._fetch_ma200_sync, symbol, interval),
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def _fetch_intraday_bars_sync(
        self,
        symbol: str,
        interval: str,
        lookback_days: int,
    ) -> list[IntradayBar]:
        ticker = self._ticker(symbol)
        period = f"{lookback_days}d"
        hist = ticker.history(period=period, interval=interval, auto_adjust=False)
        if hist is None or hist.empty:
            return []
        bars: list[IntradayBar] = []
        for ts, row in hist.iterrows():
            py_ts = ts.to_pydatetime()
            if py_ts.tzinfo is None:
                py_ts = py_ts.replace(tzinfo=timezone.utc)
            else:
                py_ts = py_ts.astimezone(timezone.utc)
            bars.append(
                IntradayBar(
                    timestamp=py_ts,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row["Volume"]) if row["Volume"] == row["Volume"] else 0.0,
                )
            )
        return bars

    async def get_intraday_bars(
        self,
        symbol: str,
        interval: str = "5m",
        lookback_days: int = 2,
    ) -> list[IntradayBar]:
        """Fetch recent intraday OHLCV bars. Default: 5-min bars, last 2 days.

        yfinance limits: 1m up to 7d, 5m/15m/30m up to 60d. Use 5m for
        day-trading levels — gives enough resolution without rate-limit pain.
        """
        return cast(
            list[IntradayBar],
            await asyncio.to_thread(
                self._fetch_intraday_bars_sync, symbol, interval, lookback_days
            ),
        )
