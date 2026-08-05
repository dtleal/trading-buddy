"""Typer CLI entry point: `dtb run | brief | explain`."""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

import typer
import uvicorn
from rich.console import Console

from api.app import app as fastapi_app
from api.broadcaster import broadcaster
from cli.dashboard import render_tick
from cli.signal_render import render_signal
from container import Container, build_container
from core.enums import TRACKED_ASSETS, AssetSymbol
from settings import get_settings
from use_cases.compute_intraday_levels import ComputeIntradayLevelsUseCase
from use_cases.generate_briefing import (
    SYSTEM_PROMPT_EN,
    SYSTEM_PROMPT_PT,
    format_tick_payload,
)
from use_cases.replay_scalper import ReplayParams, iter_tape
from use_cases.replay_scalper import replay as replay_tape_files
from use_cases.sweep_scalper import DEFAULT_GRID, axis_summary
from use_cases.sweep_scalper import sweep as sweep_grid

# $ per point per contract. Used for position sizing in `dtb signal`.
# Pass --multiplier to override if you trade a different instrument.
DEFAULT_CONTRACT_MULTIPLIER: dict[str, float] = {
    "USTEC": 20.0,  # NQ E-mini = $20/pt
    "SPX": 50.0,  # ES E-mini = $50/pt
    "GOLD": 100.0,  # GC full = $100/pt; MGC mini = $10
    "US30": 5.0,  # YM E-mini = $5/pt
    "USOIL": 1000.0,  # CL = 1000 barrels, so $1000 per $1.00 move
    "US2000": 50.0,  # RTY E-mini = $50/pt
}

app = typer.Typer(add_completion=False, help="day-trading-buddy CLI")
console = Console()


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@app.command()
def run() -> None:
    """Start the live dashboard loop."""
    settings = get_settings()
    _configure_logging(settings.log_level)
    asyncio.run(_run_loop())


def _format_countdown(remaining_s: int) -> str:
    if remaining_s <= 0:
        return "agora"
    m, s = divmod(remaining_s, 60)
    return f"{m:d}m {s:02d}s" if m else f"{s}s"


def _render_dashboard(
    language: Literal["pt", "en"],
    tick: Any,
    next_tick_in_s: int,
) -> None:
    """Clear the screen, print the dashboard, append a countdown footer.

    Works in every output mode we care about:
    - TTY (terminal local): ANSI clear redraws in-place each cycle.
    - `docker logs -f`: the streaming viewer renders the escape, so the
      previous frame is wiped before the new one prints (no scrollback wall).
    - `docker attach`: same as TTY — the periodic redraw means a freshly
      attached terminal sees the dashboard within display_refresh_seconds.
    """
    # \x1b[2J = clear entire screen; \x1b[H = move cursor to home (top-left).
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.flush()
    console.print(render_tick(tick, language=language))
    console.print(
        f"[dim]Próximo refresh de dados em [bold]{_format_countdown(next_tick_in_s)}[/bold]"
        f"  ·  display redraws a cada {get_settings().display_refresh_seconds}s[/dim]"
    )


async def _run_loop() -> None:
    settings = get_settings()
    container = await build_container(settings)

    # Start the HTTP + WebSocket API in the same event loop. The tick loop
    # publishes to `broadcaster`; the API streams from it.
    api_server = uvicorn.Server(
        uvicorn.Config(
            fastapi_app,
            host="0.0.0.0",
            port=8000,
            log_level=settings.log_level.lower(),
            lifespan="on",
        )
    )
    api_task = asyncio.create_task(api_server.serve(), name="fastapi-server")

    try:
        while True:
            tick = await container.run_tick.execute()
            await broadcaster.publish(tick)
            elapsed = 0
            # Re-render the SAME tick every display_refresh_seconds so the
            # screen stays alive (countdown ticks down) without burning yfinance/
            # FRED calls. New data is only fetched on the next outer iteration.
            while elapsed < settings.tick_interval_seconds:
                remaining = settings.tick_interval_seconds - elapsed
                _render_dashboard(settings.output_language, tick, remaining)
                sleep_for = min(settings.display_refresh_seconds, remaining)
                await asyncio.sleep(sleep_for)
                elapsed += sleep_for
    finally:
        api_server.should_exit = True
        await asyncio.shield(asyncio.wait_for(api_task, timeout=5.0))
        await container.aclose()


@app.command()
def brief() -> None:
    """Generate a macro briefing via Claude and print it to the terminal."""
    settings = get_settings()
    _configure_logging(settings.log_level)
    asyncio.run(_brief())


async def _brief() -> None:
    settings = get_settings()
    container = await build_container(settings)
    try:
        tick = await container.run_tick.execute()
        output = await container.generate_briefing.execute(tick)
        console.print()
        console.rule(f"[bold]Briefing — {tick.timestamp.strftime('%Y-%m-%d %H:%M UTC')}")
        console.print(output.content)
        console.rule()
    finally:
        await container.aclose()


@app.command()
def explain(
    event: str = typer.Option(..., "--event", "-e", help="Event name (e.g. CPI, FOMC, NFP)"),
    mode: str = typer.Option("pre", "--mode", "-m", help="pre | post"),
) -> None:
    """Generate a pre- or post-event explainer for a given event name."""
    settings = get_settings()
    _configure_logging(settings.log_level)
    if mode not in ("pre", "post"):
        raise typer.BadParameter("mode must be 'pre' or 'post'")
    asyncio.run(_explain(event, cast(Literal["pre", "post"], mode)))


async def _explain(event_name: str, mode: Literal["pre", "post"]) -> None:
    settings = get_settings()
    container = await build_container(settings)
    try:
        events = await container.fetch_calendar.execute()
        match = next(
            (e for e in events if event_name.lower() in e.name.lower()),
            None,
        )
        if match is None:
            console.print(
                f"[yellow]No upcoming '{event_name}' event found in today's calendar.[/yellow]"
            )
            console.print("Falling back to a synthetic placeholder so the explainer can still run.")
            from core.enums import ImpactLevel
            from core.models import EconomicEvent

            match = EconomicEvent(
                name=event_name.upper(),
                currency="USD",
                impact=ImpactLevel.HIGH,
                scheduled_at=datetime.now(timezone.utc),
            )
        output = await container.explain_event.execute(match, mode)
        console.print()
        console.rule(f"[bold]{match.name} — {mode}")
        console.print(output.content)
        console.rule()
    finally:
        await container.aclose()


@app.command()
def snapshot(
    include_prompt: bool = typer.Option(
        True,
        "--with-prompt/--no-prompt",
        help="Prepend the system prompt so an external LLM can run the briefing.",
    ),
) -> None:
    """Dump the current tick payload as markdown, without calling the LLM.

    Use this to hand the payload to an external Claude session (or any LLM)
    and produce a briefing without spending Anthropic API credits.
    """
    settings = get_settings()
    _configure_logging(settings.log_level)
    asyncio.run(_snapshot(include_prompt))


async def _snapshot(include_prompt: bool) -> None:
    settings = get_settings()
    container = await build_container(settings)
    try:
        tick = await container.run_tick.execute()
        if include_prompt:
            system_prompt = (
                SYSTEM_PROMPT_PT if settings.output_language == "pt" else SYSTEM_PROMPT_EN
            )
            print("=== SYSTEM PROMPT ===")
            print(system_prompt)
            print("=== USER PROMPT (TICK DATA) ===")
        print(format_tick_payload(tick))
    finally:
        await container.aclose()


@app.command()
def signal(
    asset: str = typer.Option(
        ..., "--asset", "-a", help="Asset: USTEC | SPX | GOLD | US30 | USOIL | US2000"
    ),
    interval: str = typer.Option("5m", "--interval", "-i", help="Bar interval (5m default)"),
    lookback_days: int = typer.Option(
        5,
        "--lookback",
        help="Lookback in days. Need ≥3 for the 200-period MAs on 5m. yfinance cap: 60d.",
    ),
    risk_pct: float | None = typer.Option(
        None, "--risk-pct", help="Override RISK_PER_TRADE_PCT for this run."
    ),
    account_size: float | None = typer.Option(
        None, "--account-size", help="Override ACCOUNT_SIZE_USD for this run."
    ),
    multiplier: float | None = typer.Option(
        None, "--multiplier", help="$/point per contract (default per asset: NQ=20, ES=50, GC=100)."
    ),
) -> None:
    """Print intraday levels + structure-based stop candidates (no LLM, no trade idea).

    Deterministic technical reference for day-trade decisions on a 5m chart.
    """
    settings = get_settings()
    _configure_logging(settings.log_level)
    asset_upper = asset.upper()
    if asset_upper not in {a.value for a in TRACKED_ASSETS}:
        raise typer.BadParameter(f"asset must be one of: {[a.value for a in TRACKED_ASSETS]}")
    asyncio.run(
        _signal(
            asset_upper,
            interval,
            lookback_days,
            risk_pct,
            account_size,
            multiplier,
        )
    )


async def _signal(
    asset: str,
    interval: str,
    lookback_days: int,
    risk_pct_override: float | None,
    account_override: float | None,
    multiplier_override: float | None,
) -> None:
    settings = get_settings()
    container = await build_container(settings)
    try:
        bars = await container.prices.get_intraday_bars(asset, interval, lookback_days)
        if not bars:
            console.print(
                f"[red]No bars returned for {asset}. Market closed or API throttled.[/red]"
            )
            return
        uc = ComputeIntradayLevelsUseCase(opening_range_minutes=settings.opening_range_minutes)
        levels = uc.execute(asset, bars)
        if levels is None:
            console.print(f"[red]Not enough bars to compute levels for {asset}.[/red]")
            return
        console.print(
            render_signal(
                levels,
                account_size_usd=(
                    account_override if account_override is not None else settings.account_size_usd
                ),
                risk_pct=(
                    risk_pct_override
                    if risk_pct_override is not None
                    else settings.risk_per_trade_pct
                ),
                stop_buffer_atr=settings.stop_buffer_atr_multiple,
                contract_multiplier=(
                    multiplier_override
                    if multiplier_override is not None
                    else DEFAULT_CONTRACT_MULTIPLIER.get(asset, 1.0)
                ),
            )
        )
    finally:
        await container.aclose()


@app.command()
def replay(
    files: list[Path] = typer.Argument(
        ..., help="Tape JSONL files (data/orderflow_tape/tape-YYYY-MM-DD.jsonl), in order."
    ),
    target: float = typer.Option(350.0, "--target", help="Profit target USD (bank + re-arm)."),
    stop: float = typer.Option(900.0, "--stop", help="Daily loss stop USD (session)."),
    cooldown: float = typer.Option(2.0, "--cooldown", help="Seconds between entries per symbol."),
    one_shot: bool = typer.Option(
        False, "--one-shot", help="Stop after the first banked target (no 24h re-arm)."
    ),
    lot: list[str] = typer.Option(
        [], "--lot", help="Override lots per symbol, e.g. --lot USTEC=1.0 (repeatable)."
    ),
    usd_per_point: list[str] = typer.Option(
        [],
        "--usd-per-point",
        help="USD per 1.0 point per lot, e.g. --usd-per-point GOLD=100 (repeatable). "
        "Defaults assume FTMO .cash (indices 1.0, gold 100).",
    ),
    detail: bool = typer.Option(False, "--detail", help="Also list every close event."),
) -> None:
    """Backtest the explosion scalper by replaying a recorded ingest tape.

    Runs the recorded session through the SAME aggregator/signal/policy code as
    the live bot; only order execution is simulated (see use_cases/replay_scalper).
    """
    _configure_logging("WARNING")
    params = ReplayParams(
        profit_target=target, loss_stop=stop, cooldown_s=cooldown, rearm=not one_shot
    )
    for raw, table in ((lot, params.lots), (usd_per_point, params.usd_per_point)):
        for item in raw:
            sym_name, _, value = item.partition("=")
            try:
                table[AssetSymbol(sym_name.upper())] = float(value)
            except ValueError as exc:
                raise typer.BadParameter(f"expected SYMBOL=NUMBER, got {item!r}") from exc
    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        raise typer.BadParameter(f"tape file(s) not found: {', '.join(missing)}")
    report = replay_tape_files(files, params)
    if detail:
        for c in report.closes:
            console.print(f"{c.at}  {c.scope:<8} {c.reason:<8} {c.pnl:+10.2f}")
    console.print(f"[bold]{report.events}[/bold] eventos replayed")
    console.print(report.summary())


@app.command()
def sweep(
    files: list[Path] = typer.Argument(
        ..., help="Tape JSONL files (data/orderflow_tape/tape-YYYY-MM-DD.jsonl), in order."
    ),
    set_axis: list[str] = typer.Option(
        [],
        "--set",
        help="Sweep axis NAME=v1,v2,... (repeatable). UPPERCASE = scalper constant "
        "(STRONG_FRACTION=0.6,0.7); lowercase = replay param (symbol_stop_usd=0,150). "
        "Without --set, a curated 4-axis default grid runs (81 replays).",
    ),
    top: int = typer.Option(10, "--top", help="How many best runs to print."),
) -> None:
    """Sweep scalper parameters over a recorded tape, ranking robust regions.

    Each grid point replays the whole tape. Read the per-axis means at the end:
    pick values whose whole row is healthy, not a single lucky combo.
    """
    _configure_logging("WARNING")
    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        raise typer.BadParameter(f"tape file(s) not found: {', '.join(missing)}")
    grid: dict[str, list[float]] = {}
    for item in set_axis:
        name, _, raw_values = item.partition("=")
        try:
            grid[name.strip()] = [float(v) for v in raw_values.split(",") if v.strip()]
        except ValueError as exc:
            raise typer.BadParameter(f"expected NAME=v1,v2,..., got {item!r}") from exc
        if not grid[name.strip()]:
            raise typer.BadParameter(f"axis {name!r} has no values")
    if not grid:
        grid = dict(DEFAULT_GRID)
    # GRID_LEVELS is consumed by range() — keep integral axes as ints.
    if "GRID_LEVELS" in grid:
        grid["GRID_LEVELS"] = [int(v) for v in grid["GRID_LEVELS"]]

    records = list(iter_tape(files))
    combos = 1
    for values in grid.values():
        combos *= len(values)
    console.print(f"{len(records)} eventos × {combos} combinações…")
    runs = sweep_grid(records, grid)

    names = list(grid)
    console.print("\n[bold]Melhores combinações[/bold]")
    for run in runs[:top]:
        knobs = "  ".join(f"{n}={run.overrides[n]:g}" for n in names)
        rep = run.report
        pf = f"{rep.profit_factor:.2f}" if rep.profit_factor is not None else "n/a"
        console.print(
            f"P&L {rep.total_pnl:+9.2f}  DD {rep.max_drawdown:8.2f}  PF {pf:>5}  "
            f"{rep.wins}W/{rep.losses}L  ent {rep.entries:3d}   {knobs}"
        )
    console.print("\n[bold]Média de P&L por valor (leitura de robustez)[/bold]")
    for name, values in axis_summary(runs).items():
        row = "  ".join(f"{value:g}: {pnl:+.2f}" for value, pnl in sorted(values.items()))
        console.print(f"{name}:  {row}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
