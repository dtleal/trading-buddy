import struct,sys,collections
ag={}
for l in open("/mnt/c/Users/diego/AppData/Roaming/Nelogica/Profit/newagents.dat",encoding="latin-1"):
    p=l.strip().split(":")
    if len(p)>2 and p[0].isdigit(): ag[int(p[0])]=p[2]
b=open(sys.argv[1],'rb').read(); REC=45; n=len(b)//REC
same=collections.Counter(); tot=collections.Counter(); lots=collections.defaultdict(collections.Counter)
par13=collections.Counter()
for i in range(n):
    d,ms,pr,qty,_,v,a1,a2=struct.unpack("<dIdIIdII",b[i*REC:i*REC+44]); t=b[i*REC+44]
    tot[t]+=1
    if a1==a2: same[t]+=1
    lots[t][qty]+=1
    if t==13: par13[(ag.get(a1,a1),ag.get(a2,a2))]+=qty
for t in sorted(tot):
    L=lots[t]; N=sum(L.values()); V=sum(q*c for q,c in L.items())
    p12=100*sum(c for q,c in L.items() if q<=2)/N
    print(f"tipo {t:>2}: {tot[t]:>7,} neg | mesma corretora dos 2 lados: {100*same[t]/tot[t]:>5.1f}% | lote medio {V/N:>5.1f} | {p12:>4.0f}% sao 1-2 lotes")
print("\ntop pares no tipo 13 (contratos):")
for (a,c),v in par13.most_common(12): print(f"  {a:<22} x {c:<22} {v:>8,}")
