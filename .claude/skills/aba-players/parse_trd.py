import struct,sys,collections,datetime
agents={}
for line in open("/mnt/c/Users/diego/AppData/Roaming/Nelogica/Profit/newagents.dat",encoding="latin-1"):
    p=line.strip().split(":")
    if len(p)>2 and p[0].isdigit(): agents[int(p[0])]=p[2]
b=open(sys.argv[1],'rb').read(); REC=45; n=len(b)//REC
print(sys.argv[1].split('/')[-1],"trades",n,"resto",len(b)%REC)
net=collections.Counter(); typ=collections.Counter(); vol=collections.Counter()
first=last=None
for i in range(n):
    d,ms,price,qty,f1,v,a1,a2=struct.unpack("<dIdIIdII",b[i*REC:i*REC+44])
    t=b[i*REC+44]; typ[t]+=1
    if first is None: first=d
    last=d
    if t==2: net[a1]+=qty; net[a2]-=qty      # agressao compradora
    elif t==3: net[a1]+=qty; net[a2]-=qty    # mesma conta: a1 comprou, a2 vendeu
    vol[a1]+=qty; vol[a2]+=qty
ep=datetime.datetime(1899,12,30)
print("janela",(ep+datetime.timedelta(days=first)).strftime("%d/%m %H:%M"),"->",(ep+datetime.timedelta(days=last)).strftime("%H:%M"))
print("tipos",dict(typ))
print("NET COMPRADO:",[(agents.get(k,k),v) for k,v in net.most_common(8)])
print("NET VENDIDO :",[(agents.get(k,k),v) for k,v in net.most_common()[:-9:-1]])
print("MAIS GIRO   :",[(agents.get(k,k),v) for k,v in vol.most_common(12)])
