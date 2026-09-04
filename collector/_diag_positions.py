import MetaTrader5 as mt5, time, json, urllib.request, collections
mt5.initialize(path=r"C:\Program Files\MetaTrader 5-6 grafs ligados\terminal64.exe")
MAP = {"UsaTecSep26":"USTEC","Usa500Sep26":"SPX","GOLD":"GOLD","UsaIndSep26":"US30","Ger40Sep26":"GER40","EURUSD":"EURUSD"}
for i in range(6):
    p = mt5.positions_get() or []
    live = collections.defaultdict(float); cnt = collections.Counter()
    for x in p:
        live[MAP.get(x.symbol, x.symbol)] += x.profit; cnt[MAP.get(x.symbol,x.symbol)] += 1
    snaps = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/orderflow", timeout=5))
    row = []
    for s in snaps:
        sym = s["symbol"]
        b = sum(q["profit"] for q in s["positions"])
        row.append(f"{sym}: mt5={round(live.get(sym,0.0),2)}({cnt.get(sym,0)}) back={round(b,2)}({len(s['positions'])})")
    print(time.strftime('%H:%M:%S'), " | ".join(row))
    time.sleep(3)
mt5.shutdown()
