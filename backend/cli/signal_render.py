"""Rich rendering for `dtb signal` — intraday levels + structure stops."""

from __future__ import annotations

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from core.models import IntradayLevels


def _fmt(v: float | None, digits: int = 2) -> str:
    return f"{v:.{digits}f}" if v is not None else "n/a"


def _delta(a: float, b: float | None) -> str:
    if b is None:
        return "n/a"
    diff = a - b
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:.2f}"


def _levels_table(levels: IntradayLevels) -> Table:
    t = Table(title="Níveis (5m, sessão atual)", show_header=False, expand=False)
    t.add_column("Field", style="bold cyan")
    t.add_column("Value", justify="right")
    t.add_column("vs Last", justify="right", style="dim")

    last = levels.last_price
    t.add_row("Last", _fmt(last), "")
    t.add_row("HOD", _fmt(levels.hod), _delta(levels.hod, last))
    t.add_row("LOD", _fmt(levels.lod), _delta(levels.lod, last))
    t.add_row("VWAP", _fmt(levels.vwap), _delta(levels.vwap, last) if levels.vwap else "n/a")
    t.add_row("ORH", _fmt(levels.orh), _delta(levels.orh, last) if levels.orh else "n/a")
    t.add_row("ORL", _fmt(levels.orl), _delta(levels.orl, last) if levels.orl else "n/a")
    t.add_row("PDC", _fmt(levels.pdc), _delta(levels.pdc, last) if levels.pdc else "n/a")
    t.add_row("PDH", _fmt(levels.pdh), _delta(levels.pdh, last) if levels.pdh else "n/a")
    t.add_row("PDL", _fmt(levels.pdl), _delta(levels.pdl, last) if levels.pdl else "n/a")
    return t


def _trend_table(levels: IntradayLevels) -> Table:
    t = Table(title="Tendência intraday (5m EMAs)", show_header=False, expand=False)
    t.add_column("EMA", style="bold cyan")
    t.add_column("Value", justify="right")
    t.add_column("Side", justify="center")
    last = levels.last_price
    for label, val in (
        ("EMA 9", levels.ema_9),
        ("EMA 20", levels.ema_20),
        ("EMA 50", levels.ema_50),
    ):
        if val is None:
            t.add_row(label, "n/a", "—")
            continue
        side = "[green]acima[/green]" if last > val else "[red]abaixo[/red]"
        t.add_row(label, _fmt(val), side)
    return t


def _volatility_table(levels: IntradayLevels) -> Table:
    t = Table(title="Volatilidade", show_header=False, expand=False)
    t.add_column("Field", style="bold cyan")
    t.add_column("Value", justify="right")
    t.add_row("ATR(14, 5m)", _fmt(levels.atr_14))
    if levels.hod is not None and levels.lod is not None:
        t.add_row("Range do dia", _fmt(levels.hod - levels.lod))
    return t


def _stop_card(
    levels: IntradayLevels,
    *,
    stop_buffer: float,
    account_size_usd: float,
    risk_pct: float,
    contract_multiplier: float,
) -> Panel:
    """Build the structure-based stop card.

    For now we treat 'contract_multiplier' as $/point — user can override per
    asset. Defaults to 1.0 (i.e. position size = number of "units" arrisking
    1 dollar per point). NQ futures = 20, ES = 50, GC = 100, etc.
    """
    last = levels.last_price
    sh = levels.last_swing_high
    sl = levels.last_swing_low
    atr = levels.atr_14 or 0.0
    buffer_pts = stop_buffer * atr if atr else 0.0

    body = Text()
    body.append("Stop estrutural baseado no último swing pivot (5-bar).\n", style="dim")
    body.append(f"Buffer: {stop_buffer:.2f}x ATR = {buffer_pts:.2f} pts\n\n", style="dim")

    # LONG
    body.append("LONG  ", style="bold green")
    if sl is None:
        body.append("→ último swing low ainda não confirmado (precisa de mais barras).\n")
    else:
        stop = sl - buffer_pts
        dist = last - stop
        body.append(f"→ Stop @ {stop:.2f} ({-dist:+.2f} pts)\n")
        if account_size_usd > 0 and contract_multiplier > 0 and dist > 0:
            risk_usd = account_size_usd * risk_pct / 100.0
            size = risk_usd / (dist * contract_multiplier)
            body.append(
                f"        Position size: {size:.2f} contratos "
                f"(arrisca ${risk_usd:,.0f} = {risk_pct:.1f}% de ${account_size_usd:,.0f})\n",
                style="dim",
            )
    body.append("\n")
    # SHORT
    body.append("SHORT ", style="bold red")
    if sh is None:
        body.append("→ último swing high ainda não confirmado (precisa de mais barras).\n")
    else:
        stop = sh + buffer_pts
        dist = stop - last
        body.append(f"→ Stop @ {stop:.2f} (+{dist:.2f} pts)\n")
        if account_size_usd > 0 and contract_multiplier > 0 and dist > 0:
            risk_usd = account_size_usd * risk_pct / 100.0
            size = risk_usd / (dist * contract_multiplier)
            body.append(
                f"        Position size: {size:.2f} contratos "
                f"(arrisca ${risk_usd:,.0f} = {risk_pct:.1f}% de ${account_size_usd:,.0f})\n",
                style="dim",
            )
    return Panel(body, title="Stop candidates", border_style="yellow")


def render_signal(
    levels: IntradayLevels,
    *,
    account_size_usd: float = 0.0,
    risk_pct: float = 2.0,
    stop_buffer_atr: float = 0.5,
    contract_multiplier: float = 1.0,
) -> Group:
    header = Text()
    header.append(f"{levels.symbol}", style="bold cyan")
    header.append(f"  |  Last: {levels.last_price:.2f}")
    header.append(f"  |  asof {levels.asof.strftime('%Y-%m-%d %H:%M UTC')}", style="dim")

    return Group(
        Panel(header, border_style="cyan"),
        _levels_table(levels),
        _trend_table(levels),
        _volatility_table(levels),
        _stop_card(
            levels,
            stop_buffer=stop_buffer_atr,
            account_size_usd=account_size_usd,
            risk_pct=risk_pct,
            contract_multiplier=contract_multiplier,
        ),
    )
