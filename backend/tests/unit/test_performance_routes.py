"""API-level tests for the Performance surface.

Drives the real stack: the collector's `trade_history` message through the
order-flow ingest socket → the closed-trade store → `GET /api/performance`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import api.routes.orderflow as of
import api.routes.performance as perf
from adapters.trade_history import TradeHistory
from api.app import create_app
from settings import Settings

TOKEN = "test-secret-token"


def push(client: TestClient, trades: list[dict], balance: float = 1000.0) -> None:
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(
            {
                "type": "trade_history",
                "days": 180,
                "currency": "USD",
                "balance": balance,
                "asof": "2026-03-02T15:00:00+00:00",
                "trades": trades,
            }
        )
        # A second message we can wait on, so the first is fully handled.
        ws.send_json({"type": "hello", "source": "test"})


def trade(tid: int, net: float, **kw) -> dict:
    base = {
        "id": tid,
        "symbol": "USTEC",
        "broker_symbol": "UsaTecSep26",
        "side": "buy",
        "source": "manual",
        "lots": 0.01,
        "open_ts": "2026-03-02T14:00:00+00:00",
        "close_ts": "2026-03-02T14:01:00+00:00",
        "open_price": 100.0,
        "close_price": 110.0,
        "profit": net,
        "net": net,
    }
    return {**base, **kw}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    enabled = Settings(orderflow_enabled=True, orderflow_ingest_token=SecretStr(TOKEN))
    monkeypatch.setattr(of, "get_settings", lambda: enabled)
    monkeypatch.setattr(of, "_tape_recorder", None)
    # In-memory store: no JSON file as a test side effect.
    store = TradeHistory(None)
    monkeypatch.setattr(perf, "trade_history", store)
    monkeypatch.setattr(of, "trade_history", store)
    app = create_app()
    with TestClient(app) as test_client:
        of._bot_trade_repo = None
        yield test_client


def test_empty_report_before_any_push(client: TestClient) -> None:
    body = client.get("/api/performance").json()
    assert body["summary"]["trades"] == 0
    assert body["equity_curve"] == []
    assert body["available_symbols"] == []


def test_pushed_trades_land_in_the_report(client: TestClient) -> None:
    push(
        client,
        [
            trade(1, 10.0),
            trade(2, -4.0, close_ts="2026-03-02T14:05:00+00:00", symbol="GOLD", source="bot"),
        ],
        balance=1006.0,
    )
    body = client.get("/api/performance").json()
    assert body["summary"]["trades"] == 2
    assert body["summary"]["net"] == 6.0
    assert body["summary"]["win_rate"] == 50.0
    assert body["start_balance"] == 1000.0
    assert body["end_balance"] == 1006.0
    assert body["currency"] == "USD"
    assert body["available_symbols"] == ["GOLD", "USTEC"]
    assert [t["id"] for t in body["trades"]] == [2, 1]  # newest first


def test_repeated_pushes_do_not_duplicate_trades(client: TestClient) -> None:
    push(client, [trade(1, 10.0)], balance=1010.0)
    push(client, [trade(1, 10.0), trade(2, 5.0, close_ts="2026-03-02T14:09:00+00:00")], 1015.0)
    body = client.get("/api/performance").json()
    assert body["summary"]["trades"] == 2
    assert body["summary"]["net"] == 15.0


def test_source_and_symbol_filters(client: TestClient) -> None:
    push(
        client,
        [
            trade(1, 10.0),
            trade(2, -4.0, close_ts="2026-03-02T14:05:00+00:00", symbol="GOLD", source="bot"),
        ],
        balance=1006.0,
    )
    only_bot = client.get("/api/performance?source=bot").json()
    assert only_bot["summary"]["trades"] == 1
    assert only_bot["summary"]["net"] == -4.0

    only_ustec = client.get("/api/performance?symbols=USTEC").json()
    assert only_ustec["summary"]["trades"] == 1
    assert only_ustec["summary"]["net"] == 10.0


def test_explicit_date_window_covers_the_whole_end_day(client: TestClient) -> None:
    push(client, [trade(1, 10.0)], balance=1010.0)
    inside = client.get("/api/performance?start=2026-03-02&end=2026-03-02").json()
    assert inside["summary"]["trades"] == 1
    outside = client.get("/api/performance?start=2026-03-03").json()
    assert outside["summary"]["trades"] == 0


def test_a_bad_date_is_a_400(client: TestClient) -> None:
    assert client.get("/api/performance?start=ontem").status_code == 400


def test_unknown_preset_is_rejected(client: TestClient) -> None:
    assert client.get("/api/performance?preset=decade").status_code == 422
