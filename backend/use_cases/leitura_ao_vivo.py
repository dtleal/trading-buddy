"""Leitura do agora a partir dos dados do MT5 (candles 5m + snapshot do fluxo).

Funcoes puras sobre dicts (o mesmo JSON de /api/orderflow e /api/orderflow/candles),
usadas pelo scripts/leitura_ao_vivo.py e pelo loop do Jev trader.
"""

from __future__ import annotations

from datetime import datetime, timedelta


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _sessao(bars: list[dict]) -> tuple[list[dict], list[dict]]:
    """Sessao atual e anterior, separadas pela pausa diaria (buraco > 30 min nos candles)."""
    cortes = [
        i for i in range(1, len(bars))
        if _ts(bars[i]["timestamp"]) - _ts(bars[i - 1]["timestamp"]) > timedelta(minutes=30)
    ]
    ini = cortes[-1] if cortes else 0
    ant = cortes[-2] if len(cortes) > 1 else 0
    return bars[ini:], bars[ant:ini]


def _m15(bars: list[dict]) -> list[dict]:
    grupos: dict[datetime, list[dict]] = {}
    for b in bars:
        t = _ts(b["timestamp"])
        grupos.setdefault(t.replace(minute=t.minute - t.minute % 15), []).append(b)
    return [
        {"t": t, "o": g[0]["open"], "h": max(x["high"] for x in g),
         "l": min(x["low"] for x in g), "c": g[-1]["close"]}
        for t, g in sorted(grupos.items())
    ]


def _m2(footprint: list[dict]) -> list[dict]:
    """2-minute candles from the collector's 1-minute footprint bars. Those only
    carry the traded price levels (only the newest bar, older ones keep just
    the POC) and the delta, so a candle here is high, low and delta, no
    open/close."""
    out: dict[str, dict] = {}
    for bar in footprint:
        prices = [c["price"] for c in bar.get("cells") or []] or [p for p in [bar.get("poc_price")] if p]
        if not prices:
            continue
        t = _ts(bar["bar_open"])
        key = t.replace(minute=t.minute - t.minute % 2).isoformat()
        c = out.setdefault(key, {"h": max(prices), "l": min(prices), "d": 0.0})
        c["h"], c["l"] = max(c["h"], *prices), min(c["l"], *prices)
        c["d"] += bar.get("delta", 0.0)
    return [out[k] for k in sorted(out)]


def ler_estado(sym: str, bars: list[dict], fluxo: dict) -> tuple[float, str]:
    hoje, ontem = _sessao(bars)
    px = fluxo["book"]["bids"][0]["price"] if (fluxo.get("book") or {}).get("bids") else bars[-1]["close"]
    hod, lod = max(b["high"] for b in hoje), min(b["low"] for b in hoje)
    vol = sum(b["volume"] for b in hoje) or 1
    vwap = sum((b["high"] + b["low"] + b["close"]) / 3 * b["volume"] for b in hoje) / vol
    var = sum(((b["high"] + b["low"] + b["close"]) / 3 - vwap) ** 2 * b["volume"] for b in hoje) / vol
    sd = var**0.5
    trs = [b["high"] - b["low"] for b in bars[-14:]]
    atr = sum(trs) / len(trs)

    q = _m15(hoje)[-6:]
    atual = q[-1]
    pos15 = (px - atual["l"]) / (atual["h"] - atual["l"]) if atual["h"] > atual["l"] else 0.5
    maxs_caindo = sum(q[i]["h"] < q[i - 1]["h"] for i in range(1, len(q)))
    mins_subindo = sum(q[i]["l"] > q[i - 1]["l"] for i in range(1, len(q)))

    linhas = [
        f"{sym} px={px:.2f} | sessao max={hod:.2f} min={lod:.2f} vwap={vwap:.2f} (px {'acima' if px > vwap else 'abaixo'}) | ATR5m={atr:.2f}",
        f"bandas vwap: -2sd={vwap - 2 * sd:.2f} -1sd={vwap - sd:.2f} +1sd={vwap + sd:.2f} +2sd={vwap + 2 * sd:.2f}",
        f"15m ultimos {len(q)}: maximas caindo {maxs_caindo}/{len(q) - 1}, minimas subindo {mins_subindo}/{len(q) - 1} | "
        f"candle 15m atual o={atual['o']:.2f} h={atual['h']:.2f} l={atual['l']:.2f}, px em {pos15:.0%} do range (0%=na minima)",
    ]
    if ontem:
        pdh, pdl = max(b["high"] for b in ontem), min(b["low"] for b in ontem)
        amp = pdh - pdl
        for nome, ref in (("MAX", pdh), ("MIN", pdl)):
            dp = (px - ref) / ref * 100
            tag = "ENCOSTADO" if abs(dp) <= 0.35 else ("perto" if abs(dp) <= 0.8 else "longe")
            linhas.append(f"vs {nome} ontem {ref:.2f}: {px - ref:+.2f}pts ({dp:+.2f}%, {abs(px - ref) / amp:.0%} da amplitude) {tag}")

    fp = fluxo.get("footprint") or []
    m2 = _m2(fp)
    if len(m2) >= 2:
        n = len(m2) - 1
        andou = (m2[-1]["h"] + m2[-1]["l"]) / 2 - (m2[0]["h"] + m2[0]["l"]) / 2
        linhas.append(
            f"2m ultimos {len(m2)}: maximas caindo {sum(m2[i]['h'] < m2[i - 1]['h'] for i in range(1, len(m2)))}/{n}, "
            f"minimas subindo {sum(m2[i]['l'] > m2[i - 1]['l'] for i in range(1, len(m2)))}/{n} | "
            f"andou {andou:+.2f} pts em {2 * len(m2)} min | delta por candle: {' '.join(f'{c['d']:+.0f}' for c in m2)}"
        )
    deltas = [b["delta"] for b in fp[-10:]]
    seq = 0
    for d in reversed(deltas):
        if d == 0 or (seq and (d > 0) != (seq > 0)):
            break
        seq += 1 if d > 0 else -1
    la, lq, fs = fluxo.get("live_activity") or {}, fluxo.get("liquidity") or {}, fluxo.get("flow_signal") or {}
    linhas += [
        f"delta 1m (ultimos {len(deltas)}): {' '.join(f'{d:+.0f}' for d in deltas)} | soma 5m={sum(deltas[-5:]):+.0f} | "
        f"sequencia {abs(seq)} min {'positivos' if seq > 0 else 'negativos' if seq < 0 else '-'}",
        f"ritmo agora: {la.get('range_per_bar', 0):.1f} pts e {la.get('volume_per_bar')} ticks por min | "
        f"liquidez {lq.get('ratio', 0):.2f}x do normal | sinal do bot: {fs.get('action')} ({fs.get('reason')})",
        "obs: volume e delta sao contagem de ticks do CFD, nao contratos reais",
    ]
    return px, "\n".join(linhas)
