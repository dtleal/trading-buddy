"""Rich-based terminal dashboard renderer."""

from __future__ import annotations

from typing import Literal

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from day_trading_buddy.cli.i18n import t
from day_trading_buddy.core.enums import BiasLevel, TermStructure, VixRegime
from day_trading_buddy.core.models import DashboardTick

Language = Literal["pt", "en"]


def _bias_label(level: BiasLevel, language: Language) -> Text:
    if level == BiasLevel.BULLISH:
        return Text(t("bias_bullish", language), style="bold green")
    if level == BiasLevel.BEARISH:
        return Text(t("bias_bearish", language), style="bold red")
    return Text(t("bias_neutral", language), style="bold yellow")


def _regime_label(regime: VixRegime, language: Language) -> str:
    if regime == VixRegime.LOW:
        return t("regime_low", language)
    if regime == VixRegime.HIGH:
        return t("regime_high", language)
    return t("regime_mid", language)


def _term_label(term: TermStructure, language: Language) -> str:
    if term == TermStructure.CONTANGO:
        return t("term_contango", language)
    if term == TermStructure.BACKWARDATION:
        return t("term_backwardation", language)
    return t("term_flat", language)


def _prices_table(tick: DashboardTick, language: Language) -> Table:
    table = Table(title=t("prices_header", language), expand=True)
    table.add_column("Asset", style="cyan bold")
    table.add_column("Price", justify="right")
    table.add_column("Change", justify="right")
    table.add_column("vs MA200d", justify="right")
    for asset, quote in tick.market.assets.items():
        change = (
            f"{quote.change_pct:+.2f}%" if quote.change_pct is not None else t("no_data", language)
        )
        if quote.ma200_d:
            distance = (quote.price - quote.ma200_d) / quote.ma200_d * 100.0
            ma_text = f"{distance:+.2f}%"
        else:
            ma_text = t("no_data", language)
        table.add_row(asset.value, f"{quote.price:,.2f}", change, ma_text)
    return table


def _vix_panel(tick: DashboardTick, language: Language) -> Panel:
    vix = tick.market.vix
    body = (
        f"VIX: [bold]{vix.vix:.2f}[/bold]  |  "
        f"regime: {_regime_label(vix.regime, language)}  |  "
        f"term: {_term_label(vix.term_structure, language)}"
    )
    return Panel(body, title=t("vix_header", language), border_style="magenta")


def _events_table(tick: DashboardTick, language: Language) -> Table:
    table = Table(title=t("events_header", language), expand=True)
    table.add_column("Time (UTC)", style="cyan")
    table.add_column("Impact")
    table.add_column("Event")
    table.add_column("Forecast / Previous", justify="right")

    if not tick.events_today:
        table.add_row("", "", t("no_events", language), "")
        return table

    for e in tick.events_today:
        impact_style = {
            "high": "bold red",
            "medium": "yellow",
            "low": "dim",
        }.get(e.impact.value, "white")
        table.add_row(
            e.scheduled_at.strftime("%H:%M"),
            Text(e.impact.value.upper(), style=impact_style),
            e.name,
            f"{e.forecast or '-'} / {e.previous or '-'}",
        )
    return table


def _bias_table(tick: DashboardTick, language: Language) -> Table:
    table = Table(title=t("bias_header", language), expand=True)
    table.add_column("Asset", style="cyan bold")
    table.add_column("Score", justify="right")
    table.add_column("Verdict")
    table.add_column("Components (T / M / S)", justify="right")
    for asset, report in tick.bias.items():
        components = (
            f"{report.components.technical:.0f} / "
            f"{report.components.macro:.0f} / "
            f"{report.components.sentiment:.0f}"
        )
        table.add_row(
            asset.value,
            f"{report.score:.0f}",
            _bias_label(report.level, language),
            components,
        )
    return table


def _news_panel(tick: DashboardTick, language: Language) -> Panel:
    if not tick.recent_news:
        body = t("no_data", language)
    else:
        lines = [f"• [{item.source}] {item.headline}" for item in tick.recent_news[:8]]
        body = "\n".join(lines)
    return Panel(body, title=t("news_header", language), border_style="blue")


def render_tick(tick: DashboardTick, language: Language) -> Group:
    return Group(
        Panel(
            f"[bold]{t('title', language)}[/bold]   {tick.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            border_style="white",
        ),
        _prices_table(tick, language),
        _vix_panel(tick, language),
        _bias_table(tick, language),
        _events_table(tick, language),
        _news_panel(tick, language),
    )
