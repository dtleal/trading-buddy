"""Leitura ao vivo so com dados do MT5 (collector), segunda opiniao do Jev e placar.

Uso:
    python3 scripts/leitura_ao_vivo.py                   # USTEC, SPX, GOLD
    python3 scripts/leitura_ao_vivo.py --alvo GOLD 4344.1

Cada resposta do Jev fica em ~/.trading-buddy/previsoes.jsonl. Toda rodada confere as
previsoes que ja passaram de 30 min contra os candles do MT5 e mostra o placar.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from use_cases.leitura_ao_vivo import _ts, ler_estado  # noqa: E402

BASE = os.environ.get("TB_BASE", "http://localhost:8000")
ROOT = Path(__file__).resolve().parent.parent
LOG = Path.home() / ".trading-buddy" / "previsoes.jsonl"
JEV_URL = "https://api.typesafe.ai/v1/systemone"
HORIZONTE = timedelta(minutes=30)
SIMBOLOS = ["USTEC", "SPX", "GOLD"]


def _get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=6) as r:
        return json.load(r)


def _jev_key() -> str | None:
    key = os.environ.get("JEV_API_KEY")
    if key:
        return key
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("JEV_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def _jev(state: str, questions: dict) -> dict[str, float]:
    body = json.dumps({"model": "jev-latest", "state": state, "questions": questions}).encode()
    req = urllib.request.Request(
        JEV_URL, body, {"Authorization": f"Bearer {_jev_key()}", "Content-Type": "application/json", "User-Agent": "trading-buddy"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        answers = json.load(r)["answers"]
    return {k: float(v["noul"]) for k, v in answers.items()}


def _perguntas(sym: str, px: float, alvo: float | None) -> dict:
    qs = {
        "baixo": {
            "type": "noul",
            "instructions": f"Daqui a 30 minutos o {sym} vai estar abaixo de {px:.2f}?",
            "criteria": {
                "true": "estrutura de baixa (maximas caindo, abaixo do VWAP, perto da minima do 15m) e fluxo vendedor",
                "false": "estrutura de alta (minimas subindo, acima do VWAP, perto da maxima do 15m) e fluxo comprador",
            },
        }
    }
    if alvo is not None:
        lado = "cair" if alvo < px else "subir"
        qs["alvo"] = {
            "type": "noul",
            "instructions": f"O {sym} vai {lado} ate {alvo:.2f} ({abs(px - alvo):.2f} pts) nos proximos 30 minutos?",
            "criteria": {
                "true": f"estrutura e fluxo apontam para {lado} e a distancia cabe no ritmo atual (compare com ATR e pts por minuto)",
                "false": f"estrutura ou fluxo contra {lado}, ou a distancia e grande demais para o ritmo atual",
            },
        }
    return qs


def _conferir(candles: dict) -> None:
    if not LOG.exists():
        return
    agora = datetime.now(timezone.utc)
    regs = [json.loads(line) for line in LOG.read_text().splitlines() if line.strip()]
    for r in regs:
        t0 = _ts(r["at"])
        if "certo" in r or agora - t0 < HORIZONTE:
            continue
        janela = [b for b in candles.get(r["symbol"], []) if t0 <= _ts(b["timestamp"]) < t0 + HORIZONTE]
        if not janela:
            continue
        if r["q"] == "baixo":
            r["aconteceu"] = janela[-1]["close"] < r["px"]
        else:
            r["aconteceu"] = (min(b["low"] for b in janela) <= r["alvo"]) if r["alvo"] < r["px"] \
                else (max(b["high"] for b in janela) >= r["alvo"])
        r["certo"] = (r["p"] >= 0.5) == r["aconteceu"]
    LOG.write_text("".join(json.dumps(r) + "\n" for r in regs))
    feitos = [r for r in regs if "certo" in r]
    if feitos:
        acertos = sum(r["certo"] for r in feitos)
        brier = sum((r["p"] - r["aconteceu"]) ** 2 for r in feitos) / len(feitos)
        print(f"PLACAR JEV: {acertos}/{len(feitos)} certos ({acertos / len(feitos):.0%}) | "
              f"brier {brier:.3f} (0=perfeito, 0.25=chute)\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alvo", nargs=2, metavar=("ATIVO", "PRECO"))
    args = ap.parse_args()
    alvo_sym, alvo = (args.alvo[0].upper(), float(args.alvo[1])) if args.alvo else (None, None)

    fluxos = {f["symbol"]: f for f in _get("/api/orderflow")}
    if not fluxos:
        raise SystemExit("MT5 sem fluxo (/api/orderflow vazio): o collector caiu. Ligue o watchdog.")
    candles = _get("/api/orderflow/candles?limit=600")
    _conferir(candles)

    agora = datetime.now(timezone.utc).isoformat()
    novos = []
    for sym in [alvo_sym] if alvo_sym else SIMBOLOS:
        if sym not in fluxos or not candles.get(sym):
            print(f"{sym}: sem dados do MT5\n")
            continue
        px, texto = ler_estado(sym, candles[sym], fluxos[sym])
        a = alvo if sym == alvo_sym else None
        try:
            resp = _jev(texto, _perguntas(sym, px, a))
        except Exception as e:  # sem Jev a leitura continua valendo
            resp = {}
            print(f"(Jev nao respondeu: {e})")
        print(texto)
        print(f"JEV: abaixo de {px:.2f} em 30min = {resp.get('baixo', float('nan')):.2f}"
              + (f" | toca {a:.2f} em 30min = {resp['alvo']:.2f}" if "alvo" in resp else "") + "\n")
        for q, p in resp.items():
            novos.append({"at": agora, "symbol": sym, "px": px, "q": q, "p": p, "alvo": a if q == "alvo" else None})
    if novos:
        LOG.parent.mkdir(exist_ok=True)
        with LOG.open("a") as f:
            f.writelines(json.dumps(r) + "\n" for r in novos)


if __name__ == "__main__":
    main()
