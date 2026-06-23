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
        # Lifespan wired a real (lazy) bot-trade repo; disable DB writes by
        # default so tests don't touch Postgres. Recording tests inject a fake.
        of._bot_trade_repo = None
        yield test_client


class _FakeBotTradeRepo:
    """Captures bot trade records in memory for assertions."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def record(self, **fields) -> None:
        self.events.append(fields)

    async def list_recent(self, limit: int = 200) -> list:
        return []


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
    assert of._autoclose.armed is False  # one-shot (auto_arm off)


def test_autoclose_auto_arms_on_collector_connect(client: TestClient) -> None:
    of._autoclose.auto_arm = True
    of._autoclose.target_usd = 500.0
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json({"type": "hello", "auto_close_enabled": True})
    st = client.get("/api/orderflow/autoclose").json()
    assert st["armed"] is True and st["target_usd"] == 500.0


def test_autoclose_no_auto_arm_when_pref_off(client: TestClient) -> None:
    of._autoclose.auto_arm = False
    of._autoclose.target_usd = 500.0
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json({"type": "hello", "auto_close_enabled": True})
    assert client.get("/api/orderflow/autoclose").json()["armed"] is False


def test_manual_disarm_disables_auto_arm(client: TestClient) -> None:
    of._autoclose.enabled = True
    of._autoclose.auto_arm = True
    of._autoclose.target_usd = 500.0
    of._autoclose.armed = True
    client.post("/api/orderflow/autoclose", json={"armed": False})
    assert of._autoclose.auto_arm is False
    # A later reconnect must NOT silently re-arm after a manual disarm.
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json({"type": "hello", "auto_close_enabled": True})
    assert client.get("/api/orderflow/autoclose").json()["armed"] is False


def test_autoclose_rearms_after_fire_in_auto_arm(client: TestClient) -> None:
    of._autoclose.enabled = True
    of._autoclose.auto_arm = True
    of._autoclose.armed = True
    of._autoclose.target_usd = 100.0
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_positions_msg(profit=150.0))
        cmd = ws.receive_json()
    assert cmd["type"] == "close_all"
    assert of._autoclose.armed is True  # stays armed (re-arm)
    assert of._autoclose.cooling is True


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


def test_bot_enabled_requires_trade_close_and_demo(client: TestClient) -> None:
    def hello(**flags) -> None:
        with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
            ws.send_json({"type": "hello", **flags})

    # All three → enabled.
    hello(auto_trade_enabled=True, auto_close_enabled=True, account_is_demo=True)
    assert client.get("/api/orderflow/bot").json()["enabled"] is True
    # Missing auto-close → can open but never close → must stay DISABLED.
    hello(auto_trade_enabled=True, auto_close_enabled=False, account_is_demo=True)
    assert client.get("/api/orderflow/bot").json()["enabled"] is False
    # Not a demo account → disabled.
    hello(auto_trade_enabled=True, auto_close_enabled=True, account_is_demo=False)
    assert client.get("/api/orderflow/bot").json()["enabled"] is False
    # No auto-trade → disabled.
    hello(auto_trade_enabled=False, auto_close_enabled=True, account_is_demo=True)
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


def test_bot_opens_market_plus_grid_on_explosion(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force a flat-entry explosion + a quote + range; assert it opens 1 market
    # order WITH a grid of limit levels attached.
    monkeypatch.setattr(of, "detect_explosion", lambda snap: "buy")
    monkeypatch.setattr(of, "_book_bid_ask", lambda snap: (100.0, 100.5))
    monkeypatch.setattr(of, "_range_per_bar", lambda snap: 10.0)
    of._bot.enabled = True
    of._bot.armed = True
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json({"type": "positions", "symbol": "USTEC", "positions": []})  # touch, flat
        cmd = ws.receive_json()
    assert cmd["type"] == "open"
    assert cmd["symbol"] == "USTEC" and cmd["side"] == "buy" and cmd["lots"] == 2.0
    # entry 100.5, step 0.5*10=5 → limits below
    assert cmd["grid"] == [95.5, 90.5, 85.5]
    assert "USTEC" in of._bot.grid  # region recorded for the break-reverse


def test_bot_reverses_on_flow_flip(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Holding a buy on USTEC; force a reversal signal → closes that symbol and
    # stays armed (it re-enters the new side via the normal path once flat).
    monkeypatch.setattr(of, "should_reverse", lambda snap, side: True)
    of._bot.enabled = True
    of._bot.armed = True
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_positions_msg(side="buy"))  # held long on USTEC
        cmd = ws.receive_json()
    assert cmd["type"] == "close_symbol" and cmd["symbol"] == "USTEC"
    assert of._bot.armed is True


def test_bot_reverses_when_region_breaks(client: TestClient) -> None:
    # Holding a long with a grid region whose breach is 99; a book whose mid
    # falls below 99 means the whole region failed → close (collector also
    # cancels the limits).
    from core.enums import AssetSymbol

    of._bot.enabled = True
    of._bot.armed = True
    of._bot.grid[AssetSymbol.USTEC] = {"side": "buy", "breach": 99.0}
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_positions_msg(side="buy", profit=5.0))  # in the trade
        ws.send_json(
            {
                "type": "book",
                "symbol": "USTEC",
                "asof": "2026-06-09T14:00:00Z",
                "bids": [[98.0, 1.0]],
                "asks": [[98.2, 1.0]],
            }
        )
        cmd = ws.receive_json()
    assert cmd["type"] == "close_symbol" and cmd["symbol"] == "USTEC"


def test_bot_profit_lock_closes_on_giveback(client: TestClient) -> None:
    # Peak +100, then gives back to +50 (≤ 60% of peak) while still positive →
    # the trailing lock banks it instead of letting it round-trip.
    of._bot.enabled = True
    of._bot.armed = True
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_positions_msg(profit=100.0))  # sets the peak
        ws.send_json(_positions_msg(profit=50.0))  # gave back enough → lock
        cmd = ws.receive_json()
    assert cmd["type"] == "close_symbol" and cmd["symbol"] == "USTEC"


def test_bot_profit_lock_ignores_small_peaks(client: TestClient) -> None:
    # Peak only +35 (< _BOT_LOCK_MIN_USD) → no trailing lock.
    of._bot.enabled = True
    of._bot.armed = True
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_positions_msg(profit=35.0))
        ws.send_json(_positions_msg(profit=10.0))
    assert not of._bot.closing  # nothing locked


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

    monkeypatch.setattr(of, "detect_explosion", lambda snap: "buy")
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


def test_bot_open_persisted_to_history(client: TestClient) -> None:
    repo = _FakeBotTradeRepo()
    of._bot_trade_repo = repo
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(
            {
                "type": "open_result",
                "ok": True,
                "symbol": "USTEC",
                "side": "sell",
                "lots": 2.0,
                "price": 30000.0,
                "ticket": 777,
            }
        )
    assert len(repo.events) == 1
    ev = repo.events[0]
    assert ev["kind"] == "open" and ev["symbol"] == "USTEC" and ev["side"] == "sell"
    assert ev["lots"] == 2.0 and ev["ticket"] == 777 and ev["price"] == 30000.0


def test_bot_failed_open_not_persisted(client: TestClient) -> None:
    repo = _FakeBotTradeRepo()
    of._bot_trade_repo = repo
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(
            {"type": "open_result", "ok": False, "symbol": "USTEC", "error": "retcode=10027"}
        )
    assert repo.events == []


def test_bot_close_persisted_to_history(client: TestClient) -> None:
    repo = _FakeBotTradeRepo()
    of._bot_trade_repo = repo
    of._bot.enabled = True
    of._bot.armed = True
    of._bot.profit_target = 100.0
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        ws.send_json(_positions_msg(profit=150.0))  # hits target → bot closes all
        ws.receive_json()  # the close_all command
    assert any(e["kind"] == "close" and e["reason"] == "target" for e in repo.events)


def test_manual_close_not_persisted(client: TestClient) -> None:
    # The per-asset manual close must NOT land in bot history.
    repo = _FakeBotTradeRepo()
    of._bot_trade_repo = repo
    of._autoclose.enabled = True
    with client.websocket_connect(f"/ws/ingest/orderflow?token={TOKEN}") as ws:
        resp = client.post("/api/orderflow/close/USTEC")
        ws.receive_json()  # close_symbol command
    assert resp.status_code == 200
    assert repo.events == []  # manual close recorded nothing
