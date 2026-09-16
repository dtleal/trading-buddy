import struct,sys,collections,statistics
ag={}
for l in open("/mnt/c/Users/diego/AppData/Roaming/Nelogica/Profit/newagents.dat",encoding="latin-1"):
    p=l.strip().split(":")
    if len(p)>2 and p[0].isdigit(): ag[int(p[0])]=p[2]
b=open(sys.argv[1],'rb').read(); REC=45; n=len(b)//REC
st=collections.defaultdict(lambda: {"ctr":0,"vol":0,"lots":collections.Counter(),"agr":0,"pas":0,"net":0,"rlp":0})
for i in range(n):
    d,ms,pr,qty,_,v,a1,a2=struct.unpack("<dIdIIdII",b[i*REC:i*REC+44]); t=b[i*REC+44]
    if t not in (2,3,13): continue
    for a,side in ((a1,+1),(a2,-1)):
        s=st[a]; s["ctr"]+=1; s["vol"]+=qty; s["lots"][qty]+=1; s["net"]+=side*qty
        if t==13: s["rlp"]+=qty
    # t==2 agressao compradora -> comprador agrediu
    st[a1]["agr" if t==2 else "pas"]+=qty
    st[a2]["agr" if t==3 else "pas"]+=qty
tot=sum(s["vol"] for s in st.values())
rows=[]
for a,s in st.items():
    if s["vol"]<3000: continue
    lots=s["lots"]; N=sum(lots.values())
    p1=100*sum(c for q,c in lots.items() if q<=2)/N
    p50=100*sum(c*q for q,c in lots.items() if q>=50)/s["vol"]
    med=s["vol"]/N
    rows.append((s["vol"],ag.get(a,a),med,p1,p50,100*s["agr"]/s["vol"],100*s["rlp"]/s["vol"],s["net"]))
rows.sort(reverse=True)
print(f"{'corretora':<24}{'contratos':>10}{'lote med':>9}{'%neg 1-2':>9}{'%vol 50+':>9}{'%agride':>8}{'%RLP':>7}{'saldo':>9}")
for v,nm,med,p1,p50,agr,rlp,net in rows[:26]:
    print(f"{str(nm):<24}{v:>10,}{med:>9.1f}{p1:>9.0f}{p50:>9.0f}{agr:>8.0f}{rlp:>7.0f}{net:>+9,}")
