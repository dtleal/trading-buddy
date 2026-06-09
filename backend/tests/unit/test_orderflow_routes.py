"""API-level tests for the order-flow WebSocket + REST surface.

Exercises the real FastAPI stack end-to-end: collector → ingest WS →
aggregator → broadcaster → browser WS, plus the REST snapshot and the token
auth gate. The aggregator/broadcaster are process singletons, so each test
resets them first.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import api.routes.orderflow as of
from api.app import create_app
from api.orderflow_broadcaster import orderflow_broadcaster
from settings import Settings

TOKEN = "test-secret-token"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # Enable the feature with a known token for the route's runtime check.
    enabled = Settings(orderflow_enabled=True, orderflow_ingest_token=SecretStr(TOKEN))
    monkeypatch.setattr(of, "get_settings", lambda: enabled)

    # Reset the shared singletons so tests don't leak state into each other.
    of.aggregator = of._build_aggregator()
    orderflow_broadcaster._latest.clear()

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def _book_msg() -> dict:
    return {
        "type": "book",
        "symbol": "USTEC",
        "asof": "2026-06-09T14:00:00Z",
        "bids": [[100.0, 5.0], [99.75, 8.0]],
        "asks": [[100.25, 3.0], [100.5, 6.0]],
    }


def test_ingest_then_rest_snapshot(client: TestClient) -> None:
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_book_msg())
        ws.send_json(
            {
                "type": "trade",
                "symbol": "USTEC",
                "at": "2026-06-09T14:00:01Z",
                "price": 100.25,
                "volume": 2.0,
                "side": "buy",
            }
        )

    snaps = client.get("/api/orderflow").json()
    ustec = next(s for s in snaps if s["symbol"] == "USTEC")
    assert ustec["book"]["bids"][0] == {"price": 100.0, "volume": 5.0}
    assert ustec["book"]["asks"][0] == {"price": 100.25, "volume": 3.0}
    assert ustec["recent_trades"][-1]["side"] == "buy"
    bar = ustec["footprint"][-1]
    cell = next(c for c in bar["cells"] if c["price"] == 100.25)
    assert cell["ask_volume"] == 2.0
    assert bar["delta"] == 2.0


def test_browser_ws_replays_latest_snapshot(client: TestClient) -> None:
    # Ingest first so the broadcaster has a cached latest snapshot to replay.
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ingest:
        ingest.send_json(_book_msg())

    with client.websocket_connect("/ws/orderflow") as viewer:
        msg = viewer.receive_json()
        assert msg["symbol"] == "USTEC"
        assert msg["book"]["asks"][0]["price"] == 100.25


def test_ingest_live_push_reaches_subscriber(client: TestClient) -> None:
    # Subscriber connected BEFORE the trade prints should receive the live push.
    with client.websocket_connect("/ws/orderflow") as viewer:
        with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ingest:
            ingest.send_json(
                {
                    "type": "trade",
                    "symbol": "GOLD",
                    "at": "2026-06-09T14:00:05Z",
                    "price": 4350.0,
                    "volume": 1.0,
                    "side": "sell",
                }
            )
            msg = viewer.receive_json()
    assert msg["symbol"] == "GOLD"
    assert msg["recent_trades"][-1]["price"] == 4350.0


def test_malformed_message_does_not_drop_stream(client: TestClient) -> None:
    # A bad message (missing price) is skipped; the next good one still lands.
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json({"type": "trade", "symbol": "USTEC", "at": "2026-06-09T14:00:00Z"})
        ws.send_json(_book_msg())
    snaps = client.get("/api/orderflow").json()
    ustec = next(s for s in snaps if s["symbol"] == "USTEC")
    assert ustec["book"]["bids"][0]["price"] == 100.0


def test_ingest_rejects_bad_token(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/ingest/orderflow?token=wrong") as ws:
            ws.receive_json()


def test_ingest_ignores_untracked_symbol(client: TestClient) -> None:
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(
            {
                "type": "trade",
                "symbol": "BITCOIN",
                "at": "2026-06-09T14:00:00Z",
                "price": 60000.0,
                "volume": 1.0,
                "side": "buy",
            }
        )
    snaps = client.get("/api/orderflow").json()
    assert all(s["symbol"] != "BITCOIN" for s in snaps)
