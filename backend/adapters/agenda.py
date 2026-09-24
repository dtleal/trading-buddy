"""Today's market agenda for WIN, WDO and GOLD: what is scheduled, and when.

Three free sources, because none of them has it all:

- TradingView's economic calendar: Brazil and US releases (IPCA, payroll,
  Copom minutes, Fed speeches...), with the time in UTC.
- The Banco Central president's public agenda: TradingView does not list his
  press conferences (e.g. the Relatório de Política Monetária one at 11h), and
  those move WIN and WDO as much as any release.
- Valor and InfoMoney RSS: the headlines, for what is not on any calendar.

ForexFactory (the old calendar) has no Brazil at all, which is how the 11h
press conference was missed.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import feedparser
import httpx

logger = logging.getLogger(__name__)

BRT = ZoneInfo("America/Sao_Paulo")

TV_URL = "https://economic-calendar.tradingview.com/events"
BCB_URL = "https://www.bcb.gov.br/api/servico/sitebcb/agendadiretoria"
# Valor's finance feed is the market desk (Ibovespa, dólar, juros); InfoMoney
# is broader but first to post. Their per-section feeds come back empty.
HEADLINE_FEEDS = {
    "Valor": "https://valor.globo.com/rss/valor/financas/",
    "InfoMoney": "https://www.infomoney.com.br/feed/",
}

# TradingView importance is -1 (low), 0 (medium), 1 (high). Low is building
# permits and bill auctions: too many to alert on, none of them move WIN.
_MIN_IMPORTANCE = 0

_HEADERS = {"User-Agent": "Mozilla/5.0", "Origin": "https://www.tradingview.com"}


@dataclass(frozen=True, slots=True)
class AgendaEvent:
    at: datetime  # UTC
    country: str  # "BR" or "US"
    title: str
    importance: int  # -1 low, 0 medium, 1 high
    source: str
    forecast: str | None = None
    previous: str | None = None
    actual: str | None = None


@dataclass(frozen=True, slots=True)
class Headline:
    at: datetime  # UTC
    title: str
    url: str
    source: str


def _num(value: object) -> str | None:
    return None if value is None else str(value)


def parse_tradingview(payload: dict) -> list[AgendaEvent]:
    events = []
    for row in payload.get("result", []):
        if row.get("importance", -1) < _MIN_IMPORTANCE:
            continue
        at = datetime.fromisoformat(row["date"].replace("Z", "+00:00"))
        # 00:00 UTC is how TradingView marks all-day items (UN assembly,
        # summits). There is no clock time to alert on, so they are left out.
        if at.time() == time(0, 0):
            continue
        events.append(
            AgendaEvent(
                at=at,
                country=row["country"],
                title=row["title"],
                importance=row["importance"],
                source="TradingView",
                forecast=_num(row.get("forecast")),
                previous=_num(row.get("previous")),
                actual=_num(row.get("actual")),
            )
        )
    return events


# "11:00 às 13:00 – Participa de coletiva ..." inside the agenda's HTML.
_BCB_ITEM = re.compile(r"(\d{2}):(\d{2})\s*(?:às\s*\d{2}:\d{2})?\s*[–-]\s*(.+)")


def parse_bcb(payload: dict, day: date) -> list[AgendaEvent]:
    """Only the president's items that are open to the press: those are the
    public talks. Closed meetings do not reach the market while they happen."""
    events = []
    for row in payload.get("conteudo", []):
        if not row.get("identificacaoAutoridade", "").startswith("01 - Presi"):
            continue
        text = html.unescape(re.sub(r"<(div|br|p)[^>]*>", "\n", row.get("descricao", "")))
        text = re.sub(r"<[^>]+>", "", text).replace("​", "")
        # The item text runs over several lines; glue each one back to its time.
        for chunk in re.split(r"\n(?=\s*\d{2}:\d{2})", text):
            match = _BCB_ITEM.search(" ".join(chunk.split()))
            if not match or "aberto à imprensa" not in match.group(3):
                continue
            hour, minute, what = int(match.group(1)), int(match.group(2)), match.group(3)
            what = what.replace("(aberto à imprensa)", "").strip()
            at = datetime.combine(day, time(hour, minute), BRT).astimezone(timezone.utc)
            events.append(
                AgendaEvent(
                    at=at,
                    country="BR",
                    title=f"Galípolo: {what[:120]}",
                    importance=1,
                    source="Banco Central",
                )
            )
    return events


async def _tradingview(client: httpx.AsyncClient, day: date) -> list[AgendaEvent]:
    # A BRT day runs 03:00 UTC to 03:00 UTC.
    start = datetime.combine(day, time(0, 0), BRT).astimezone(timezone.utc)
    params = {
        "from": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "to": (start + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "countries": "BR,US",
    }
    response = await client.get(TV_URL, params=params, headers=_HEADERS)
    response.raise_for_status()
    return parse_tradingview(response.json())


async def _bcb(client: httpx.AsyncClient, day: date) -> list[AgendaEvent]:
    params = {
        "lista": "Agenda da Diretoria",
        "inicioAgenda": f"'{day.isoformat()}'",
        "fimAgenda": f"'{(day + timedelta(days=1)).isoformat()}'",
    }
    response = await client.get(BCB_URL, params=params, headers=_HEADERS)
    response.raise_for_status()
    return parse_bcb(response.json(), day)


async def fetch_events(day: date) -> list[AgendaEvent]:
    """Both calendars, sorted by time. A source that fails is logged and left
    out, so one site down does not blank the other."""
    events: list[AgendaEvent] = []
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for name, source in (("TradingView", _tradingview), ("BCB", _bcb)):
            try:
                events.extend(await source(client, day))
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                logger.warning("agenda: %s failed: %s", name, exc)
    return sorted(events, key=lambda e: e.at)


def fetch_headlines(limit: int = 15) -> list[Headline]:
    """Newest first, both feeds mixed."""
    items = []
    for source, url in HEADLINE_FEEDS.items():
        for entry in feedparser.parse(url).entries[:limit]:
            try:
                at = parsedate_to_datetime(entry.get("published", "")).astimezone(timezone.utc)
            except (TypeError, ValueError):
                continue
            items.append(Headline(at=at, title=entry.title.strip(), url=entry.link, source=source))
    return sorted(items, key=lambda h: h.at, reverse=True)[:limit]
