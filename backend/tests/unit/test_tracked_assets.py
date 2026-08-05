"""Guards for the tracked-asset list.

Adding an instrument means touching several unrelated tables (Yahoo ticker, bot
lot size, USD-per-point, the order-flow symbol default). Miss one and the app
still boots — the asset just silently goes missing from a panel, or the scalper
bot quietly skips it. These tests fail loudly instead.
"""

from __future__ import annotations

from adapters.prices_yfinance import YAHOO_TICKERS
from api.routes.orderflow import _DEFAULT_LOTS
from core.enums import TRACKED_ASSETS, AssetSymbol
from settings import Settings
from use_cases.replay_scalper import DEFAULT_LOTS, DEFAULT_USD_PER_POINT


def test_bitcoin_is_retired_but_still_parseable() -> None:
    # Kept in the enum so snapshots saved before it was dropped still load.
    assert AssetSymbol("BITCOIN") is AssetSymbol.BITCOIN
    assert AssetSymbol.BITCOIN not in TRACKED_ASSETS


def test_every_tracked_asset_has_a_yahoo_ticker() -> None:
    missing = [a.value for a in TRACKED_ASSETS if a.value not in YAHOO_TICKERS]
    assert missing == []


def test_every_tracked_asset_has_a_bot_lot_size() -> None:
    # A symbol missing here is skipped outright by the scalper bot.
    missing = [a.value for a in TRACKED_ASSETS if a not in _DEFAULT_LOTS]
    assert missing == []


def test_replay_defaults_cover_every_tracked_asset() -> None:
    # Without these the backtest reports the wrong absolute P&L.
    assert [a.value for a in TRACKED_ASSETS if a not in DEFAULT_LOTS] == []
    assert [a.value for a in TRACKED_ASSETS if a not in DEFAULT_USD_PER_POINT] == []


def test_default_orderflow_symbols_match_the_tracked_list() -> None:
    # The class default, not the loaded .env — a local .env may deliberately
    # narrow the list, and that must not fail the suite.
    default = str(Settings.model_fields["orderflow_symbols"].default)
    parsed = [AssetSymbol(s.strip()) for s in default.split(",")]
    assert parsed == list(TRACKED_ASSETS)
