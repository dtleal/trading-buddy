"""Profit RTD → trading-buddy B3 tape collector (Windows only).

Streams the B3 times & trades of WIN and WDO — with the broker on both sides
and who aggressed — from a running Nelogica Profit to the backend, live.

WHY THIS EXISTS: the `.trd` file the Players tab reads is a history cache, not
a log. Measured on 16/09/2026, Profit wrote it once when the window opened and
then stayed 33 minutes without touching it. Good for replay, useless as a
trigger. Profit's RTD server hands out the same prints as they happen, and it
comes with the licence we already pay for (ProfitDLL is a separate contract).

HOW IT WORKS: Profit exposes each open window as an RTD "tool". A Times &
Trades window linked with "Linkar Janela com Excel (RTD)" answers on topics
``(tool, field, line)``, line 0 being the newest print. It is a *sliding
window*, not a stream: every new print pushes the rows down, so there are no
sequence numbers and nothing tells us how many prints we missed. We recover
that by overlap — find where the top of the previous read sits inside the new
one, and everything above it is new. Validated live on 20/09/2026: 41 prints
captured against 41 of delta on the asset's own trade counter, zero loss.

TIMING, and where the prints go when they go: the window holds 500 lines (a
hard cap in Profit, checked). Measured on a replay of 18/09/2026, a burst put
all 500 lines inside 65ms — ~7.700 prints/s, matching that session's 8.924/s
peak. So the whole game is keeping a read cycle well under that.

The RTD call itself is not the problem: profiled at 10ms average and 22ms
worst for 3.000 topics, with the Python side under 1ms. What did hurt was the
sender thread taking the GIL away — reads were landing at 90ms and 14% of the
tape was being lost. Sending in fatter, rarer batches and giving the reader
priority brought passes back to ~22ms and the loss to 1,7-3,9%.

Losses are still possible in the worst bursts, so they are always reported:
every pass logs how much of Profit's own trade counter was captured, and each
overflow prints the span of tape still on screen.

USAGE (PowerShell / cmd, on the machine running Profit):
    pip install comtypes websocket-client
    python profit_rtd_collector.py --config config.json

ONE PROGRAM AT A TIME: Profit and BlackArrow register the same RTD CLSID, so
whichever answers `CoCreateInstance` is the one we talk to. Keep BlackArrow
closed, or the WIN/WDO windows will not be found.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import queue
import select
import subprocess
import sys
import threading
import time
from ctypes import POINTER, c_long
from datetime import datetime, timezone
from typing import Any

try:
    import comtypes
    import comtypes.client
    from comtypes import COMMETHOD, GUID, HRESULT, COMObject
    from comtypes.automation import IDispatch
except ImportError:  # pragma: no cover - only importable on Windows
    comtypes = None  # type: ignore

try:
    from websocket import ABNF, create_connection
except ImportError:  # pragma: no cover
    ABNF = None  # type: ignore
    create_connection = None  # type: ignore

logger = logging.getLogger("profit_rtd")

PROG_ID = "RTDTrading.RtdServer"

# Columns of a Times & Trades window, in the order the row tuples carry them.
# Names are Profit's own (from the export dialog): date, buying broker, price,
# quantity, selling broker, aggressor.
COLUMNS = ("DAT", "ACP", "PRE", "QUL", "AVD", "AGR")

# Profit refuses line 500 and above, whatever the dialog was told to link.
MAX_LINES = 500

# How many rows of the previous read have to line up before we believe we found
# the overlap. Prints repeat (same price, same size, same broker) often enough
# that a short match would land on the wrong row; 20 in a row does not happen
# by chance.
OVERLAP_MATCH = 20

# The contracts the Players tab is about. A linked window on anything else is
# read anyway (the backend ignores it), but a run with none of these is a
# misconfiguration worth stopping on.
WANTED = frozenset({"WIN", "WDO"})

# CME futures for the CME tab (needs the Nelogica "Sinal CME Level 2" plugin):
# gold, Nasdaq and S&P, mini and micro. Their windows have no broker columns.
CME_ROOTS = ("MGC", "MNQ", "MES", "GC", "NQ", "ES")

# Tools are named after the window type plus an index. Only Times & Trades
# windows are of interest here, and Profit has never handed out more than a
# handful, so probing a few is enough to find every linked one.
MAX_TOOLS = 8

_IID_RTD_UPDATE_EVENT = "{A43788C1-D91B-11D3-8F39-00C04F3651B8}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_config(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        cfg = json.load(handle)
    if not cfg.get("b3_ws_url"):
        raise SystemExit("config: 'b3_ws_url' is required")
    if not cfg.get("token"):
        raise SystemExit("config: 'token' is required")
    return cfg


def _build_update_event() -> Any:
    """The callback Profit needs before it will serve any topic.

    We never act on `UpdateNotify` — reading on a fixed 20ms beat is both
    simpler and what the timing budget above is built on — but `ServerStart`
    returns 0 (refused) without a valid one.

    pywin32 cannot implement this interface (it does not know
    `IRTDUpdateEvent` and rejects the wrapper); comtypes can, as long as the
    methods are declared as a vtable and the object is handed over as plain
    IDispatch for Profit to query back.
    """

    class IRTDUpdateEvent(IDispatch):
        _iid_ = GUID(_IID_RTD_UPDATE_EVENT)
        _methods_ = [
            COMMETHOD([comtypes.dispid(10)], HRESULT, "UpdateNotify"),
            COMMETHOD(
                [comtypes.dispid(11), "propget"], HRESULT, "HeartbeatInterval",
                (["retval", "out"], POINTER(c_long), "value"),
            ),
            COMMETHOD(
                [comtypes.dispid(11), "propput"], HRESULT, "HeartbeatInterval",
                (["in"], c_long, "value"),
            ),
            COMMETHOD([comtypes.dispid(12)], HRESULT, "Disconnect"),
        ]

    class UpdateEvent(COMObject):
        _com_interfaces_ = [IRTDUpdateEvent]

        def IRTDUpdateEvent_UpdateNotify(self, this):  # noqa: N802
            return 0

        def IRTDUpdateEvent__get_HeartbeatInterval(self, this, value):  # noqa: N802
            value[0] = -1  # no heartbeat: we drive the reads ourselves
            return 0

        def IRTDUpdateEvent__set_HeartbeatInterval(self, this, value):  # noqa: N802
            return 0

        def IRTDUpdateEvent_Disconnect(self, this):  # noqa: N802
            return 0

    return UpdateEvent().QueryInterface(IDispatch)


def new_rows(
    current: list[tuple], previous: list[tuple] | None, match: int = OVERLAP_MATCH
) -> tuple[list[tuple], bool]:
    """Rows of `current` that are not in `previous`, plus whether we overflowed.

    The window slides: a new print goes in at line 0 and pushes everything
    down. So the previous read still sits inside the new one, just lower —
    finding where its top landed gives exactly how many prints arrived.

    Returns `(rows, True)` when the previous top is nowhere to be found, which
    means more prints arrived than the window holds and the ones in between
    are gone for good. The whole window comes back so the loss is bounded and
    counted instead of silent.
    """
    if previous is None or current == previous:
        return [], False
    head = previous[:match]
    # `- match + 1` and not `- match`: the last offset worth trying is the one
    # where the old top still has `match` rows left to compare against. Without
    # the +1, a read that brought exactly `lines - match` prints is called an
    # overflow and the whole window is replayed.
    for offset in range(len(current) - match + 1):
        if current[offset : offset + match] == head:
            return current[:offset], False
    return current, True


class TapeWindow:
    """One linked Times & Trades window, read as a sliding window.

    Holds the full grid because `RefreshData` only hands back the topics that
    changed, and a partial grid cannot be diffed against the previous read.
    """

    def __init__(self, server: Any, tool: str, asset: str, lines: int, first_id: int) -> None:
        self.tool = tool
        self.asset = asset
        self.lines = lines
        self.slots: dict[int, tuple[int, int]] = {}
        self.grid: list[list[Any]] = [[None] * len(COLUMNS) for _ in range(lines)]
        self.previous: list[tuple] | None = None
        self.overflows = 0
        self.captured = 0
        self._first_neg: int | None = None
        topic_id = first_id
        for line in range(lines):
            for index, column in enumerate(COLUMNS):
                self.slots[topic_id] = (line, index)
                server.ConnectData(topic_id, [tool, column, line], True)
                topic_id += 1
        self.next_id = topic_id

    def apply(self, topic_id: int, value: Any) -> None:
        slot = self.slots.get(topic_id)
        if slot is not None:
            self.grid[slot[0]][slot[1]] = value

    def is_complete(self) -> bool:
        """True once every topic has delivered at least one value.

        The first diff has to be taken against a grid that is entirely filled.
        A cell still unset reads as different on the next pass, and with enough
        of them the overlap is not found — which would replay the whole window
        as if it were new. On a restart mid-session that is 500 prints counted
        twice, so it is worth waiting for.
        """
        return all(cell is not None for row in self.grid for cell in row)

    def fidelity(self, traded: int) -> str:
        """How much of the tape we actually saw, against Profit's own counter.

        `NEG` is the session trade count the quote feed publishes for the
        asset, so the difference between its delta and what we captured is
        exactly what the 500-line window dropped in a burst. Without this the
        only signal is "janela estourou", which says a hole exists but not how
        big.
        """
        if self._first_neg is None:
            self._first_neg = traded
            return "n/d"
        expected = traded - self._first_neg
        if expected <= 0:
            return "n/d"
        return f"{100.0 * self.captured / expected:.2f}% ({self.captured}/{expected})"

    def asset_changed(self, asset: str) -> None:
        """Called when the window is switched to another contract.

        Everything on screen is from a different asset now, so the previous
        snapshot cannot be diffed against the new one. Dropping it means the
        next pass only sets a fresh baseline and publishes nothing, which is
        the only safe answer.
        """
        if asset and asset != self.asset:
            logger.info("%s trocou de ativo: %s -> %s", self.tool, self.asset, asset)
            self.asset = asset
            self.previous = None

    def take_new_rows(self) -> list[tuple]:
        """Rows that appeared since the previous call, newest first."""
        current = [tuple(row) for row in self.grid]
        rows, overflowed = new_rows(current, self.previous)
        self.captured += len(rows)
        previous = self.previous
        self.previous = current
        if overflowed:
            self.overflows += 1
            # The clock of the oldest row we can still see against the newest
            # the previous read had: that gap IS the hole, in seconds of tape.
            logger.warning(
                "%s: janela estourou — fita pulou de %s para %s (mais antiga agora %s)",
                self.tool,
                previous[0][0] if previous else "?",
                current[0][0],
                current[-1][0],
            )
        return rows


def _row_to_trade(row: tuple) -> dict[str, Any] | None:
    """One grid row to the wire shape, or None when the row is not a print.

    Empty rows read back as `'-'` / `0` — a session that has not filled the
    window yet, not an error.

    Every column is type-checked before it is used. Seen once in 8.503 rows of
    a replay: a row came back with a broker name sitting in the quantity
    column. One bad row must not be worth a dead collector, so it is dropped
    and counted like any other unreadable row.
    """
    if len(row) != len(COLUMNS):
        return None
    at, buyer, price, qty, seller, aggressor = row
    if not isinstance(at, str) or ":" not in at:
        return None
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return None
    if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
        return None
    # The CME tape is anonymous, so its broker columns come back empty or as
    # something that is not a name. Sent as "" and the backend decides: a B3
    # print without both brokers is dropped there, a CME one does not need them.
    buyer = buyer if isinstance(buyer, str) else ""
    seller = seller if isinstance(seller, str) else ""
    if not isinstance(aggressor, str):
        return None
    return {
        "at": at,
        "buyer": buyer.strip(),
        "price": float(price),
        "qty": qty,
        "seller": seller.strip(),
        "aggressor": aggressor.strip(),
    }


def _discover(server: Any) -> list[tuple[str, str, int]]:
    """Linked Times & Trades windows, as (tool, asset, asset topic id).

    Profit answers "Ferramenta Inválida" for a tool that is not linked, which
    is the only way to tell which windows exist. The asset topic stays
    connected on purpose: the window can be switched to another contract while
    we run, and that topic is how we hear about it.
    """
    found: list[tuple[str, str, int]] = []
    topic_id = 1
    for index in range(MAX_TOOLS):
        tool = f"T&T{index}"
        asset_id = topic_id
        try:
            asset = server.ConnectData(asset_id, [tool, "INFO", "ATV"], True)
            tab = server.ConnectData(topic_id + 1, [tool, "INFO", "TAB"], True)
        except Exception:
            continue
        finally:
            topic_id += 2
        if not isinstance(asset, str) or "nv" in str(tab):
            continue
        found.append((tool, asset, asset_id))
        logger.info("janela %s = %s (aba %s)", tool, asset, tab)
    return found


def _connect_backend(url: str, token: str) -> Any:
    """Connect to the backend, waiting for it if it is not up yet.

    Started unattended by the watchdog, this can easily run before the backend
    (or the whole machine's network) is ready. Giving up would mean a minute of
    tape lost for nothing, so it keeps trying.
    """
    while True:
        try:
            ws = create_connection(f"{url}?token={token}", timeout=10)
        except Exception as exc:
            logger.warning("backend fora do ar (%s), tentando de novo em 5s", exc)
            time.sleep(5.0)
            continue
        ws.send(json.dumps({"type": "hello", "source": "profit-rtd", "at": _now_iso()}))
        logger.info("backend conectado: %s", url)
        return ws


class Sender(threading.Thread):
    """Ships batches to the backend, off the read loop.

    Sending inline looked simpler and was wrong. The socket carries a 10s
    timeout, so one slow or half-dead backend freezes the reader for 10s — and
    at WIN's pace that is thousands of prints past a 500-line window, which is
    real tape lost. Measured on the replay: every "janela estourou" warning was
    a blocked send, never the tape actually moving that fast.

    The queue is bounded on purpose. If the backend stays down, dropping the
    oldest batches and saying so beats growing until the process dies.
    """

    def __init__(self, url: str, token: str, maxsize: int = 20_000) -> None:
        super().__init__(daemon=True)
        self._url = url
        self._token = token
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=maxsize)
        self.dropped = 0
        self.sent = 0

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def submit(self, message: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(message)
        except queue.Full:
            self.dropped += len(message.get("trades", ()))
            logger.warning("fila cheia: %d negocios descartados no total", self.dropped)

    def _drain(self, first: dict[str, Any]) -> list[dict[str, Any]]:
        """`first` plus everything already queued, merged per window.

        One send per read was the wrong shape. Every wake-up of this thread
        takes the GIL away from the reader, and the reader is the one on a
        clock: profiled against the replay, the RTD call itself never passes
        22ms, yet the reader was seeing 90ms passes — long enough for a burst
        to outrun the 500-line window. Fewer, fatter sends give the reader its
        cadence back.
        """
        merged: dict[str, dict[str, Any]] = {first["tool"]: first}
        while True:
            try:
                message = self._queue.get_nowait()
            except queue.Empty:
                return list(merged.values())
            held = merged.get(message["tool"])
            if held is None or held["asset"] != message["asset"]:
                merged[message["tool"]] = message
            else:
                held["trades"].extend(message["trades"])

    def run(self) -> None:
        ws = _connect_backend(self._url, self._token)
        while True:
            messages = self._drain(self._queue.get())
            for message in messages:
                while True:
                    try:
                        if _peer_gone(ws):
                            raise ConnectionError("backend fechou a conexao")
                        ws.send(json.dumps(message))
                        break
                    except Exception as exc:
                        # Same batch again after reconnecting: it is already out
                        # of the reader's window, so dropping it would lose
                        # prints with nothing to show for it.
                        logger.warning("backend caiu (%s), reconectando", exc)
                        ws = _connect_backend(self._url, self._token)
                self.sent += len(message["trades"])


def _peer_gone(ws: Any) -> bool:
    """True when the backend already closed and we have not noticed.

    A half-open socket keeps accepting writes into the OS buffer, so the send
    itself only fails much later — 52 seconds of prints went into the void that
    way on the first replay run. A close frame, on the other hand, makes the
    socket readable straight away.

    Readable is not the same as closed, though: uvicorn pings every 20 seconds,
    and treating that as a death caused a pointless reconnect on the dot every
    20s. So the frame is actually read, and only a close counts.
    """
    try:
        sock = ws.sock
        if not sock or not select.select([sock], [], [], 0)[0]:
            return False
        frame = ws.recv_frame()
    except Exception:
        return True
    if frame.opcode == ABNF.OPCODE_CLOSE:
        return True
    if frame.opcode == ABNF.OPCODE_PING:
        ws.pong(frame.data)
    return False


def _prioritise_reader() -> None:
    """Give the read loop the edge over the sender thread.

    The reader is the one on a deadline — miss its beat and prints fall off the
    window for good, while the sender only has to keep up on average. Both
    knobs aim at the same thing: a shorter wait for the GIL after each RTD
    call, which is where the 90ms passes were coming from.
    """
    sys.setswitchinterval(0.001)  # default 5ms: too long to wait on a 20ms beat
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), 1)  # ABOVE_NORMAL
    except Exception:  # pragma: no cover - not Windows, or no permission
        logger.debug("nao deu pra subir a prioridade da thread de leitura")


def _profit_is_running() -> bool:
    """Whether Profit is already open.

    This has to be checked BEFORE touching the RTD server. The CLSID is
    registered as a LocalServer32 pointing at `profitchart.exe`, so asking COM
    for it while Profit is closed does not fail — it *launches Profit*. Under a
    watchdog that retries every minute, that would quietly pile up instances.
    """
    try:
        output = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq profitchart.exe", "/NH"],
            capture_output=True, text=True, timeout=15, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "profitchart.exe" in output.lower()


def run(cfg: dict[str, Any]) -> None:
    if comtypes is None:
        raise SystemExit("comtypes nao instalado: pip install comtypes")
    if create_connection is None:
        raise SystemExit("websocket-client nao instalado: pip install websocket-client")
    if not _profit_is_running():
        raise SystemExit("Profit fechado. Abra o ProfitChart e linke a janela de T&T.")
    _prioritise_reader()

    lines = min(int(cfg.get("lines", MAX_LINES)), MAX_LINES)
    interval = float(cfg.get("read_interval_ms", 20)) / 1000.0

    server = comtypes.client.CreateObject(PROG_ID, dynamic=True)
    update_event = _build_update_event()
    if not server.ServerStart(update_event):
        raise SystemExit(
            "Profit recusou o RTD. Se o BlackArrow estiver aberto, feche: os dois "
            "registram o mesmo servidor e so um atende."
        )

    found = _discover(server)
    if not found:
        raise SystemExit(
            "Nenhuma janela de Times & Trades linkada. No Profit, botao direito na "
            "janela de T&T > 'Linkar Janela com Excel (RTD)'."
        )
    covered = {asset[:3].upper() for _, asset, _ in found}
    has_cme = any(asset.upper().lstrip("@").startswith(CME_ROOTS) for _, asset, _ in found)
    if not covered & WANTED and not has_cme:
        # Every window is on something else, which in practice means the RTD
        # call landed on BlackArrow: it registers the same CLSID as Profit and
        # whichever opened first is the one COM hands out. Saying it plainly
        # beats streaming GOLD nobody asked for while the tab stays empty.
        raise SystemExit(
            f"Nenhuma janela de {'/'.join(sorted(WANTED))} — as janelas achadas sao "
            f"{sorted(a for _, a, _ in found)}. Se o BlackArrow estiver aberto, feche "
            "e abra o Profit primeiro: quem abre antes fica com o servidor RTD."
        )
    for missing in sorted(WANTED - covered):
        logger.warning(
            "sem janela de %s: a aba Players nao vai ter esse ativo. Abra o Times & "
            "Trades do %s no Profit e linke com 'Linkar Janela com Excel (RTD)'.",
            missing, missing,
        )

    windows: list[TapeWindow] = []
    assets: dict[int, TapeWindow] = {}
    next_id = 1000
    for tool, asset, asset_id in found:
        window = TapeWindow(server, tool, asset, lines, next_id)
        next_id = window.next_id
        windows.append(window)
        assets[asset_id] = window
    # Ground truth per window: Profit's own session trade counter for the
    # asset, so the report can say what share of the tape we actually saw.
    counters: dict[int, TapeWindow] = {}
    for index, window in enumerate(windows):
        counter_id = 900 + index
        try:
            server.ConnectData(counter_id, [window.asset, "NEG"], True)
            counters[counter_id] = window
        except Exception:
            logger.warning("sem contador NEG para %s", window.asset)
    neg: dict[str, int] = {}

    by_topic = {topic: window for window in windows for topic in window.slots}
    total_topics = sum(len(window.slots) for window in windows)
    logger.info("%d janela(s), %d topicos", len(windows), total_topics)

    def pump() -> None:
        data = server.RefreshData(total_topics + 8)
        if not data or not data[0]:
            return
        for topic, value in zip(data[0], data[1]):
            key = int(topic)
            window = by_topic.get(key)
            if window is not None:
                window.apply(key, value)
                continue
            switched = assets.get(key)
            if switched is not None and isinstance(value, str):
                switched.asset_changed(value)
                continue
            counted = counters.get(key)
            if counted is not None and isinstance(value, int):
                neg[counted.tool] = value

    # Fill the grid before the first diff. `ConnectData` hands back a value per
    # topic but over ~350ms, so a grid built from those returns mixes two
    # states of a moving window; a `RefreshData` pass is one consistent read.
    deadline = time.time() + 10
    while time.time() < deadline:
        pump()
        if all(window.is_complete() for window in windows):
            break
        time.sleep(0.05)
    else:
        logger.warning("grade nao encheu em 10s; comecando assim mesmo")
    for window in windows:
        window.take_new_rows()  # sets the baseline, publishes nothing

    sender = Sender(cfg["b3_ws_url"], cfg["token"])
    sender.start()
    dropped = 0
    last_report = time.time()
    # A stalled reader is how tape is lost: the window only holds `lines`
    # prints, so any pause longer than that many prints take is a hole. This
    # says out loud when the loop misses its beat instead of leaving it to be
    # inferred from an overflow warning.
    slowest = 0.0
    while True:
        started = time.perf_counter()
        pump()
        for window in windows:
            rows = window.take_new_rows()
            if not rows:
                continue
            # Oldest first, so the backend's accumulator sees the session in
            # the order it happened.
            trades = [t for t in (_row_to_trade(row) for row in reversed(rows)) if t]
            dropped += len(rows) - len(trades)
            if not trades:
                continue
            message = {
                "type": "b3_trades",
                "tool": window.tool,
                "asset": window.asset,
                "at": _now_iso(),
                "trades": trades,
            }
            sender.submit(message)

        if time.time() - last_report >= 60:
            overflows = sum(window.overflows for window in windows)
            for window in windows:
                logger.info(
                    "%s %s: capturado %s",
                    window.tool, window.asset, window.fidelity(neg.get(window.tool, 0)),
                )
            logger.info(
                "%d enviados | %d na fila | %d ilegiveis | %d descartados | "
                "%d estouros | leitura mais lenta %.0f ms",
                sender.sent, sender.pending, dropped, sender.dropped, overflows,
                slowest * 1000,
            )
            slowest = 0.0
            last_report = time.time()

        elapsed = time.perf_counter() - started
        slowest = max(slowest, elapsed)
        if elapsed > 0.2:
            logger.warning("leitura demorou %.0f ms", elapsed * 1000)
        if elapsed < interval:
            time.sleep(interval - elapsed)


def main() -> int:
    parser = argparse.ArgumentParser(description="Profit RTD → trading-buddy B3 tape")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        run(_load_config(args.config))
    except KeyboardInterrupt:
        logger.info("encerrado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
