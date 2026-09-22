"""Lista as baleias (e os bancos) do projeto e quanto cada uma girou.

Uso:  python3 .claude/skills/aba-players/baleias.py data/b3_tape/WIN*.trd

Sem arquivo nenhum ele ainda lista o mapa, só sem os números do pregão.
A fonte da verdade dos códigos é BALEIA_CODES/BANCO_CODES em
backend/use_cases/aggregate_players.py — este script só lê de lá.
"""

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np  # noqa: E402

from adapters.profit_tape import load_agents  # noqa: E402
from use_cases.aggregate_players import BALEIA_CODES, BANCO_CODES  # noqa: E402

PROFIT = Path("/mnt/c/Users/diego/AppData/Roaming/Nelogica/Profit")
RECORD = np.dtype([
    ("t", "<f8"), ("seq", "<u4"), ("px", "<f8"), ("qty", "<u4"), ("z", "<u4"),
    ("fin", "<f8"), ("buy", "<u4"), ("sell", "<u4"), ("kind", "u1"),
])

agents = load_agents(PROFIT)
volume: dict[int, int] = defaultdict(int)
total = 0
for path in sys.argv[1:]:
    tape = np.fromfile(path, dtype=RECORD)
    tape = tape[(tape["kind"] == 2) | (tape["kind"] == 3)]  # só agressão
    total += int(tape["qty"].sum()) * 2  # dois lados por negócio
    for side in ("buy", "sell"):
        for code, qty in zip(tape[side], tape["qty"]):
            volume[int(code)] += int(qty)

for label, codes in (("BALEIA", BALEIA_CODES), ("BANCO", BANCO_CODES)):
    rows = sorted(((volume.get(c, 0), c) for c in codes), reverse=True)
    group = sum(v for v, _ in rows)
    print(f"\n== {label} — {len(codes)} códigos", end="")
    print(f", {100 * group / total:.1f}% da fita" if total else "")
    for qty, code in rows:
        name = agents.get(code, "??")
        share = f"{qty:>10,} contratos  {100 * qty / group:5.1f}% do grupo" if qty else "sem negócio"
        print(f"   {code:>5}  {name:<24} {share}")
