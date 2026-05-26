"""Typer CLI entry point: `dtb run | brief | explain`."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Literal, cast

import typer
from rich.console import Console
from rich.live import Live

from day_trading_buddy.cli.dashboard import render_tick
from day_trading_buddy.container import Container, build_container
from day_trading_buddy.scheduler import TickScheduler
from day_trading_buddy.settings import get_settings

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


async def _run_loop() -> None:
    settings = get_settings()
    container = await build_container(settings)
    try:
        with Live(console=console, refresh_per_second=2, screen=False) as live:
            tick = await container.run_tick.execute()
            live.update(render_tick(tick, language=settings.output_language))

            scheduler = TickScheduler(
                interval_seconds=settings.tick_interval_seconds,
                tick_use_case=container.run_tick,
                on_tick=lambda t: live.update(render_tick(t, language=settings.output_language)),
            )
            await scheduler.run_forever()
    finally:
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
            from day_trading_buddy.core.enums import ImpactLevel
            from day_trading_buddy.core.models import EconomicEvent

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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
