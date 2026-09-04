"""Rich-based terminal dashboard renderer."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cli.i18n import t
from core.enums import BiasLevel, TermStructure, VixRegime
from core.formatting import fmt_price, price_digits
from core.models import DashboardTick, TradeSetup

BRT = ZoneInfo("America/Sao_Paulo")


def _utc_and_brt(ts: datetime) -> str:
    """Format a UTC timestamp alongside Brazilian time."""
    brt = ts.astimezone(BRT)
    return f"{ts.strftime('%Y-%m-%d %H:%M:%S UTC')}  ·  {brt.strftime('%H:%M:%S BRT')}"


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
        table.add_row(asset.value, fmt_price(quote.price, grouped=True), change, ma_text)
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
    table.add_column("UTC", style="cyan")
    table.add_column("BRT", style="cyan")
    table.add_column("Status / Impact")
    table.add_column("Event")
    table.add_column("Forecast / Previous", justify="right")

    if not tick.events_today:
        table.add_row("", "", "", t("no_events", language), "")
        return table

    now_utc = datetime.now(timezone.utc)
    for e in tick.events_today:
        already_happened = e.scheduled_at < now_utc
        brt_str = e.scheduled_at.astimezone(BRT).strftime("%H:%M")
        utc_str = e.scheduled_at.strftime("%H:%M")
        if already_happened:
            actual_part = f" → {e.actual}" if e.actual else ""
            status = Text(f"✓ ENCERRADO{actual_part}", style="dim italic")
            time_utc = Text(utc_str, style="dim strike")
            time_brt = Text(brt_str, style="dim strike")
            name = Text(e.name, style="dim strike")
            forecast_prev = Text(f"{e.forecast or '-'} / {e.previous or '-'}", style="dim")
            table.add_row(time_utc, time_brt, status, name, forecast_prev)
        else:
            impact_style = {
                "high": "bold red",
                "medium": "yellow",
                "low": "dim",
            }.get(e.impact.value, "white")
            table.add_row(
                utc_str,
                brt_str,
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


def _setup_card(setup: TradeSetup) -> Text:
    """One setup formatted as a multi-line Text block."""
    direction = setup.direction
    arrow = "🟢 COMPRA" if direction == "LONG" else "🔴 VENDA"
    style = "bold green" if direction == "LONG" else "bold red"

    body = Text()
    body.append(f"{setup.asset.value}  ", style="bold cyan")
    body.append(f"{arrow}\n", style=style)
    body.append(f"  Tendência: {setup.trend_label}\n")
    body.append(f"  Continuação: {setup.continuation_label}\n")
    d = price_digits(setup.entry_zone_low)
    body.append(
        f"  Região de entrada: {fmt_price(setup.entry_zone_low, digits=d)} – "
        f"{fmt_price(setup.entry_zone_high, digits=d)}\n",
        style="bold",
    )
    body.append(f"  Stop: {fmt_price(setup.stop_level, digits=d)}\n", style="red")
    body.append(
        f"  Alvo: {fmt_price(setup.target_level, digits=d)}   |   "
        f"R:R = {setup.risk_reward:.2f}\n",
        style="green",
    )
    body.append("  Razões:\n", style="dim")
    for r in setup.rationale:
        body.append(f"    • {r}\n", style="dim")
    return body


def _setups_panel(tick: DashboardTick) -> Panel:
    """Panel with detected setups; silent message when none."""
    if not tick.setups:
        return Panel(
            Text(
                "Sem setup com vantagem clara agora — mercado em LATERAL ou sem confluência.",
                style="dim italic",
            ),
            title="🎯 Setup com vantagem",
            border_style="yellow",
        )
    blocks: list[Text] = []
    for i, setup in enumerate(tick.setups):
        if i > 0:
            blocks.append(Text("─" * 60, style="dim"))
        blocks.append(_setup_card(setup))
    combined = Text()
    for b in blocks:
        combined.append_text(b)
        combined.append("\n")
    return Panel(combined, title="🎯 Setup com vantagem", border_style="yellow")


def render_tick(tick: DashboardTick, language: Language) -> Group:
    return Group(
        Panel(
            f"[bold]{t('title', language)}[/bold]   {_utc_and_brt(tick.timestamp)}",
            border_style="white",
        ),
        _prices_table(tick, language),
        _vix_panel(tick, language),
        _bias_table(tick, language),
        _setups_panel(tick),
        _events_table(tick, language),
        _news_panel(tick, language),
    )
