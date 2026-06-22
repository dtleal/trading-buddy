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
    of._positions_store.clear()
    of._liquidity_store.clear()
    of._autoclose = of._AutoCloseState()
    of._bot = of._BotState()
    of._bot.lots = dict(of._DEFAULT_LOTS)
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


def _positions_msg(symbol: str = "USTEC", **over) -> dict:
    pos = {
        "ticket": 12345,
        "side": "buy",
        "volume": 0.5,
        "price_open": 100.0,
        "price_current": 100.4,
        "profit": 20.0,
        "sl": 99.0,
        "tp": 101.0,
        "seconds_open": 8.0,
    }
    pos.update(over)
    return {"type": "positions", "symbol": symbol, "positions": [pos]}


def test_positions_stamped_on_snapshot(client: TestClient) -> None:
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_positions_msg())
    ustec = next(s for s in client.get("/api/orderflow").json() if s["symbol"] == "USTEC")
    assert len(ustec["positions"]) == 1
    p = ustec["positions"][0]
    assert p["ticket"] == 12345
    assert p["side"] == "buy"
    assert p["profit"] == 20.0
    assert p["sl"] == 99.0 and p["tp"] == 101.0
    assert p["seconds_open"] == 8.0


def test_positions_empty_list_clears_a_closed_trade(client: TestClient) -> None:
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_positions_msg())  # open
        ws.send_json({"type": "positions", "symbol": "USTEC", "positions": []})  # now flat
    ustec = next(s for s in client.get("/api/orderflow").json() if s["symbol"] == "USTEC")
    assert ustec["positions"] == []


def test_position_unset_sl_tp_become_null(client: TestClient) -> None:
    # MT5 reports an unset SL/TP as 0.0; the parser must surface that as null.
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_positions_msg(sl=0.0, tp=0.0))
    ustec = next(s for s in client.get("/api/orderflow").json() if s["symbol"] == "USTEC")
    p = ustec["positions"][0]
    assert p["sl"] is None and p["tp"] is None


def test_positions_live_push_reaches_subscriber(client: TestClient) -> None:
    with client.websocket_connect("/ws/orderflow") as viewer:
        with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ingest:
            ingest.send_json(_positions_msg(symbol="GOLD", side="sell", profit=-12.0))
            # GOLD positions ride the same per-symbol snapshot broadcast.
            msg = viewer.receive_json()
    assert msg["symbol"] == "GOLD"
    assert msg["positions"][0]["side"] == "sell"
    assert msg["positions"][0]["profit"] == -12.0


def test_malformed_position_does_not_drop_stream(client: TestClient) -> None:
    # Bad side → parse raises → the message is skipped, the stream survives.
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_positions_msg(side="hold"))
        ws.send_json(_book_msg())
    ustec = next(s for s in client.get("/api/orderflow").json() if s["symbol"] == "USTEC")
    assert ustec["book"]["bids"][0]["price"] == 100.0
    assert ustec["positions"] == []


def test_signals_stamped_when_flow_turns_against_a_position(client: TestClient) -> None:
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_positions_msg(side="buy"))  # long USTEC
        # A burst of sell-aggressor prints → flow leaning hard against the long.
        ws.send_json(
            {
                "type": "trades",
                "symbol": "USTEC",
                "trades": [
                    {"at": "2026-06-09T14:00:01Z", "price": 100.0, "volume": 1.0, "side": "sell"}
                    for _ in range(12)
                ],
            }
        )
    ustec = next(s for s in client.get("/api/orderflow").json() if s["symbol"] == "USTEC")
    assert len(ustec["signals"]) == 1
    sig = ustec["signals"][0]
    assert sig["code"] == "pressure_against"
    assert sig["stance"] == "against"
    assert sig["ticket"] == 12345


def test_no_signals_without_a_position(client: TestClient) -> None:
    # Same lopsided flow but flat → no positions, so no signals.
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(
            {
                "type": "trades",
                "symbol": "USTEC",
                "trades": [
                    {"at": "2026-06-09T14:00:01Z", "price": 100.0, "volume": 1.0, "side": "sell"}
                    for _ in range(12)
                ],
            }
        )
    ustec = next(s for s in client.get("/api/orderflow").json() if s["symbol"] == "USTEC")
    assert ustec["signals"] == []


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


# --- auto-close + manual close ----------------------------------------------


def test_autoclose_status_defaults(client: TestClient) -> None:
    st = client.get("/api/orderflow/autoclose").json()
    assert st["enabled"] is False and st["armed"] is False and st["target_usd"] is None


def test_hello_sets_execution_capability(client: TestClient) -> None:
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json({"type": "hello", "source": "FTMO", "auto_close_enabled": True})
    assert client.get("/api/orderflow/autoclose").json()["enabled"] is True


def test_arm_refused_when_collector_cannot_execute(client: TestClient) -> None:
    of._autoclose.enabled = False
    resp = client.post("/api/orderflow/autoclose", json={"armed": True, "target_usd": 100.0})
    assert resp.status_code == 409


def test_arm_refused_with_non_positive_target(client: TestClient) -> None:
    of._autoclose.enabled = True
    resp = client.post("/api/orderflow/autoclose", json={"armed": True, "target_usd": 0.0})
    assert resp.status_code == 422


def test_arm_and_disarm(client: TestClient) -> None:
    of._autoclose.enabled = True
    armed = client.post(
        "/api/orderflow/autoclose", json={"armed": True, "target_usd": 250.0}
    ).json()
    assert armed["armed"] is True and armed["target_usd"] == 250.0
    disarmed = client.post("/api/orderflow/autoclose", json={"armed": False}).json()
    assert disarmed["armed"] is False


def test_autoclose_fires_close_all_over_target(client: TestClient) -> None:
    of._autoclose.enabled = True
    of._autoclose.armed = True
    of._autoclose.target_usd = 100.0
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_positions_msg(profit=150.0))  # whole-account P&L over target
        cmd = ws.receive_json()
    assert cmd["type"] == "close_all"
    assert of._autoclose.armed is False  # one-shot


def test_autoclose_does_not_fire_under_target(client: TestClient) -> None:
    of._autoclose.enabled = True
    of._autoclose.armed = True
    of._autoclose.target_usd = 100.0
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_positions_msg(profit=40.0))
    assert of._autoclose.armed is True  # still armed, never fired


def test_manual_close_symbol_sends_command(client: TestClient) -> None:
    of._autoclose.enabled = True
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        resp = client.post("/api/orderflow/close/USTEC")
        cmd = ws.receive_json()
    assert resp.status_code == 200
    assert cmd["type"] == "close_symbol" and cmd["symbol"] == "USTEC"


def test_manual_close_refused_when_not_enabled(client: TestClient) -> None:
    of._autoclose.enabled = False
    assert client.post("/api/orderflow/close/USTEC").status_code == 409


def test_manual_close_unknown_symbol(client: TestClient) -> None:
    of._autoclose.enabled = True
    assert client.post("/api/orderflow/close/DOGE").status_code == 404


def test_manual_close_without_collector_connected(client: TestClient) -> None:
    of._autoclose.enabled = True  # capable, but no live socket
    assert client.post("/api/orderflow/close/USTEC").status_code == 503


def test_autoclose_result_recorded(client: TestClient) -> None:
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json({"type": "autoclose_result", "ok": True, "closed": 2})
    assert "2" in (client.get("/api/orderflow/autoclose").json()["last_result"] or "")


# --- scalper bot ------------------------------------------------------------


def test_bot_status_defaults(client: TestClient) -> None:
    st = client.get("/api/orderflow/bot").json()
    assert st["enabled"] is False and st["armed"] is False
    assert st["profit_target"] == 350.0 and st["loss_stop"] == 900.0


def test_bot_enabled_only_on_auto_trade_and_demo(client: TestClient) -> None:
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json({"type": "hello", "auto_trade_enabled": True, "account_is_demo": True})
    assert client.get("/api/orderflow/bot").json()["enabled"] is True
    # auto-trade on but NOT a demo account → bot stays disabled.
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json({"type": "hello", "auto_trade_enabled": True, "account_is_demo": False})
    assert client.get("/api/orderflow/bot").json()["enabled"] is False


def test_bot_arm_refused_when_disabled(client: TestClient) -> None:
    of._bot.enabled = False
    assert client.post("/api/orderflow/bot", json={"armed": True}).status_code == 409


def test_bot_arm_and_disarm(client: TestClient) -> None:
    of._bot.enabled = True
    armed = client.post(
        "/api/orderflow/bot", json={"armed": True, "profit_target": 350, "loss_stop": 900}
    ).json()
    assert armed["armed"] is True and armed["profit_target"] == 350.0
    assert client.post("/api/orderflow/bot", json={"armed": False}).json()["armed"] is False


def test_bot_opens_on_explosion(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the (separately-tested) entry decision; assert the wiring opens.
    monkeypatch.setattr(of, "decide_entry", lambda *a, **k: "buy")
    of._bot.enabled = True
    of._bot.armed = True
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json({"type": "positions", "symbol": "USTEC", "positions": []})  # touch, flat
        cmd = ws.receive_json()
    assert cmd["type"] == "open"
    assert cmd["symbol"] == "USTEC" and cmd["side"] == "buy" and cmd["lots"] == 2.0


def test_bot_banks_and_rearms_on_profit_target(client: TestClient) -> None:
    of._bot.enabled = True
    of._bot.armed = True
    of._bot.rearm = True
    of._bot.profit_target = 100.0
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_positions_msg(profit=150.0))
        cmd = ws.receive_json()
    assert cmd["type"] == "close_all"
    # 24h mode: stays armed, banks the win, and waits to settle (flattening).
    assert of._bot.armed is True
    assert of._bot.realized == 150.0
    assert of._bot.flattening is True


def test_bot_one_shot_stops_on_profit_target(client: TestClient) -> None:
    of._bot.enabled = True
    of._bot.armed = True
    of._bot.rearm = False
    of._bot.profit_target = 100.0
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_positions_msg(profit=150.0))
        cmd = ws.receive_json()
    assert cmd["type"] == "close_all"
    assert of._bot.armed is False


def test_bot_does_not_open_in_thin_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.enums import AssetSymbol
    from core.models import SessionLiquidity

    monkeypatch.setattr(of, "decide_entry", lambda *a, **k: "buy")
    of._bot.enabled = True
    of._bot.armed = True
    # Thin session for USTEC (ratio below the 0.75 floor) → no entry.
    of._liquidity_store[AssetSymbol.USTEC] = SessionLiquidity(
        symbol=AssetSymbol.USTEC,
        asof="2026-06-09T14:00:00Z",
        realized_volume=10.0,
        baseline_volume=100.0,
        ratio=0.3,
        sample_days=20,
    )
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json({"type": "positions", "symbol": "USTEC", "positions": []})
        # No open command should arrive; a follow-up book does (stream alive).
        ws.send_json(_book_msg())
    # The bot left no "abriu" trace and opened nothing.
    assert "abriu" not in (client.get("/api/orderflow/bot").json()["last_result"] or "")


def test_bot_loss_stop_closes_all(client: TestClient) -> None:
    of._bot.enabled = True
    of._bot.armed = True
    of._bot.loss_stop = 900.0
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_positions_msg(profit=-1000.0))
        cmd = ws.receive_json()
    assert cmd["type"] == "close_all"
    assert of._bot.armed is False


def test_bot_open_result_recorded(client: TestClient) -> None:
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(
            {"type": "open_result", "ok": True, "symbol": "USTEC", "side": "buy", "ticket": 555}
        )
    assert "555" in (client.get("/api/orderflow/bot").json()["last_result"] or "")
