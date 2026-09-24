"""Jev trader: the Jev's entry rule, the fixed ATR exits, GOLD mean reversion,
the read it gets, and the arm gate."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import api.routes.orderflow as of
from core.enums import AssetSymbol
from use_cases.jev_trader import decide, mean_reversion_signal
from use_cases.leitura_ao_vivo import ler_estado


def test_opens_the_side_the_jev_leads_by_01_at_028_or_more() -> None:
    assert decide({"comprar": 0.15, "vender": 0.30}) == "sell"
    assert decide({"comprar": 0.36, "vender": 0.25}) == "buy"


def test_waits_when_the_jev_is_not_sure() -> None:
    assert decide({"comprar": 0.6, "vender": 0.55}) == "wait"  # gap < 0.1
    assert decide({"comprar": 0.15, "vender": 0.27}) == "wait"  # below 0.28


# --- the read -----------------------------------------------------------------


def _bars(highs: list[float]) -> list[dict]:
    t0 = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)
    return [
        {"timestamp": (t0 + timedelta(minutes=5 * i)).isoformat(), "open": h - 1,
         "high": h, "low": h - 2, "close": h - 1.5, "volume": 100.0}
        for i, h in enumerate(highs)
    ]


def test_the_read_sees_falling_15m_highs() -> None:
    highs = [110 - i for i in range(18)]  # 6 candles of 15m, each lower
    snap = {"book": {"bids": [{"price": 92.0}]}, "footprint": [{"delta": -5.0}] * 3}
    price, text = ler_estado("GOLD", _bars(highs), snap)
    assert price == 92.0
    assert "maximas caindo 5/5" in text


def test_the_read_works_without_a_book() -> None:
    price, _ = ler_estado("BRA50", _bars([110 - i for i in range(18)]), {"book": None, "footprint": []})
    assert price == 91.5  # last close


def test_the_read_has_2_minute_candles_from_the_footprint() -> None:
    fp = [
        {"bar_open": f"2026-09-23T14:{m:02d}:00Z", "cells": [], "poc_price": 100.0 - m, "delta": -3.0}
        for m in range(6)
    ]
    _, text = ler_estado("SPX", _bars([110 - i for i in range(18)]), {"footprint": fp})
    assert "2m ultimos 3: maximas caindo 2/2" in text and "andou -4.00 pts em 6 min" in text


# --- one tick -------------------------------------------------------------------


def _candle(i: int, close: float, high: float | None = None, low: float | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        timestamp=datetime(2026, 9, 23, tzinfo=timezone.utc) + timedelta(minutes=5 * i),
        open=close, close=close, high=high if high is not None else close + 0.5,
        low=low if low is not None else close - 0.5, model_dump=lambda mode: {},
    )


FLAT = [_candle(i, 4350.0 + (0.6 if i % 2 else -0.6)) for i in range(100)]  # ATR5m = 1, bands ±1.2


def _pos(side: str, open_: float, profit: float, age: float = 600) -> SimpleNamespace:
    return SimpleNamespace(side=side, volume=0.01, profit=profit, price_open=open_, seconds_open=age)


def _tick(
    monkeypatch: pytest.MonkeyPatch,
    answers: dict,
    positions: list,
    symbol: AssetSymbol = AssetSymbol.USTEC,
    bars: list | None = None,
    price: float = 4350.0,
    state: of._JevTraderState | None = None,
) -> list[dict]:
    sent: list[dict] = []

    async def fake_send(payload: dict) -> bool:
        sent.append(payload)
        return True

    async def fake_ask(state, questions, timeout):
        return {k: answers.get(k, 0.0) for k in questions}

    async def fake_orderflow():
        return [SimpleNamespace(symbol=symbol, model_dump=lambda mode: {})]

    monkeypatch.setattr(of, "_send_to_collector", fake_send)
    monkeypatch.setattr(of, "ask", fake_ask)
    monkeypatch.setattr(of, "get_orderflow", fake_orderflow)
    monkeypatch.setattr(of, "ler_estado", lambda sym, bars, snap: (price, "estado"))
    monkeypatch.setitem(of._candles_store, symbol, bars or FLAT)
    monkeypatch.setitem(of._positions_store, symbol, positions)
    monkeypatch.setattr(of, "_jev_trader", state or of._JevTraderState())
    asyncio.run(of._jev_trader_tick())
    return sent


def test_the_jev_opens_a_min_lot(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _tick(monkeypatch, {"comprar": 0.1, "vender": 0.9}, [])
    assert sent == [{"type": "open", "symbol": "USTEC", "side": "sell", "lots": 0.01}]


def test_only_one_new_entry_per_symbol_every_15_min(monkeypatch: pytest.MonkeyPatch) -> None:
    state = of._JevTraderState()
    state.last_entry[AssetSymbol.USTEC] = of.time.monotonic() - 60
    assert _tick(monkeypatch, {"comprar": 0.1, "vender": 0.9}, [], state=state) == []
    assert "espera" in state.last["USTEC"]


def test_a_single_lot_is_stopped_at_1_atr(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _tick(monkeypatch, {}, [_pos("sell", 4349.0, -1.0)])  # 1 ATR against
    assert sent[0]["type"] == "close_symbol" and sent[0]["side"] == "sell"


def test_it_holds_inside_the_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _tick(monkeypatch, {}, [_pos("sell", 4349.6, -0.4)]) == []


def test_each_atr_in_our_favour_adds_a_lot(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _tick(monkeypatch, {}, [_pos("sell", 4351.0, 1.0)])
    assert sent == [{"type": "open", "symbol": "USTEC", "side": "sell", "lots": 0.01}]
    assert _tick(monkeypatch, {}, [_pos("sell", 4351.0, 1.0)] * 5) == []  # cap


def test_a_stacked_position_trails_1_atr_from_the_best(monkeypatch: pytest.MonkeyPatch) -> None:
    state = of._JevTraderState()
    state.best[AssetSymbol.USTEC] = 4348.0  # best seen; price is back at 4350
    sent = _tick(monkeypatch, {}, [_pos("sell", 4353.0, 3.0)] * 2, state=state)
    assert sent[0]["type"] == "close_symbol"


def test_stops_when_the_day_goal_is_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    state = of._JevTraderState()
    state.realized = 90.0
    sent = _tick(monkeypatch, {}, [_pos("buy", 4300.0, 12.0)], state=state)
    assert sent[0]["type"] == "close_symbol" and sent[0]["side"] == "buy"
    assert state.realized == 102.0 and "parou" in state.last_result


# --- GOLD mean reversion ----------------------------------------------------------


def test_a_poke_below_the_band_in_a_flat_market_is_a_buy() -> None:
    poke = FLAT[:-1] + [_candle(99, 4349.9, high=4350.2, low=4347.0)]
    assert mean_reversion_signal(poke) == "buy"
    assert mean_reversion_signal(FLAT) == "wait"


def test_no_mean_reversion_when_the_market_trends() -> None:
    trend = [_candle(i, 4300.0 + i) for i in range(99)] + [_candle(99, 4398.0, low=4390.0)]
    assert mean_reversion_signal(trend) == "wait"


def test_gold_takes_the_band_signal_without_asking_the_jev(monkeypatch: pytest.MonkeyPatch) -> None:
    bars = FLAT[:-2] + [_candle(98, 4349.9, high=4350.2, low=4347.0), _candle(99, 4350.0)]
    state = of._JevTraderState()
    sent = _tick(monkeypatch, {}, [], symbol=AssetSymbol.GOLD, bars=bars, state=state)
    assert sent == [{"type": "open", "symbol": "GOLD", "side": "buy", "lots": 0.01}]
    assert AssetSymbol.GOLD in state.mr


def test_a_mean_reversion_trade_takes_profit_at_the_other_band(monkeypatch: pytest.MonkeyPatch) -> None:
    state = of._JevTraderState()
    state.mr[AssetSymbol.GOLD] = of.time.monotonic()
    sent = _tick(
        monkeypatch, {}, [_pos("buy", 4348.0, 3.0)], symbol=AssetSymbol.GOLD, price=4352.0, state=state
    )
    assert sent[0]["type"] == "close_symbol"
    assert "banda" in state.last["GOLD"]


def test_cannot_arm_while_the_scalper_is_armed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(of, "_bot", of._BotState())
    of._bot.enabled, of._bot.armed = True, True
    with pytest.raises(of.HTTPException) as err:
        asyncio.run(of.set_jev_trader(of.JevTraderRequest(armed=True)))
    assert err.value.status_code == 409
    assert of._jev_trader.task is None
