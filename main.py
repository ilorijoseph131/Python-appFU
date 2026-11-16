import os,ccxt,requests,time as tm
from datetime import datetime,timezone,timedelta
from flask import Flask
from threading import Thread
app=Flask(__name__)
@app.route('/')
def _():return "V3.3.3 PERFECTED WIF FIX"
def _r():app.run(host='0.0.0.0',port=10000)
Thread(target=_r,daemon=True).start()
TT=os.getenv("TELEGRAM_TOKEN")or os.getenv("BOT_TOKEN")or"";CID=os.getenv("CHAT_ID")or os.getenv("TELEGRAM_CHAT_ID")or""
AK=os.getenv("BYBIT_API_KEY","").strip();AS=os.getenv("BYBIT_SECRET","").strip()or os.getenv("BYBIT_API_SECRET","").strip()
ex=ccxt.bybit({'apiKey':AK,'secret':AS,'enableRateLimit':True,'options':{'defaultType':'unified'}})
try:ex.load_markets()
except:0
sp=ccxt.okx({'enableRateLimit':True})
try:sp.load_markets()
except:0
W=timezone(timedelta(hours=1));WL=["BCH/USDT:USDT","ETH/USDT:USDT","SOL/USDT:USDT","BNB/USDT:USDT","DOGE/USDT:USDT","BONK/USDT:USDT","WIF/USDT:USDT","ZEC/USDT:USDT","AVAX/USDT:USDT","DOT/USDT:USDT","ONDO/USDT:USDT","PAXG/USDT:USDT"];TFS=['15m','30m','1h','2h'];MAXT=4;SEC=900;PCT=0.05;MINN=1.0
act={};cl=[];ps=False;lft={};lta={};lid=0;ls=0;ld=lw=lm=None
def snd(m):
 try:requests.post(f"https://api.telegram.org/bot{TT}/sendMessage",data={"chat_id":CID,"text":m[:3900],"parse_mode":"Markdown"},timeout=12)
 except:0
def fp(x):
 if x is None:return "N/A"
 return f"${x:.8f}" if x<0.0001 else f"${x:.6f}" if x<0.01 else f"${x:.5f}" if x<1 else f"${x:.4f}" if x<100 else f"${x:.2f}"
def ohlc(s,t,l=100):
 try:return sp.fetch_ohlcv(s,t,limit=l)
 except:
  try:return sp.fetch_ohlcv(s,t.lower(),limit=l)
  except:return None
def prc(s):
 try:return float(ex.fetch_ticker(s)['last'])
 except:return None
def rsi(c,p=14):
 if len(c)<p+1:return 50
 g=[];l=[]
 for i in range(1,len(c)):d=c[i]-c[i-1];g.append(max(d,0));l.append(max(-d,0))
 ag=sum(g[-p:])/p;al=sum(l[-p:])/p;return 70 if al==0 else 100-(100/(1+ag/al))
def ema(c,p=50):
 if len(c)<p:return c[-1]
 k=2/(p+1);e=sum(c[:p])/p
 for x in c[p:]:e=x*k+e*(1-k)
 return e
def be(last,bos,f,fm,em):
 pc=lambda a,b:abs(a-b)/b*100 if b else 999
 if f and pc(fm,bos)<0.8:return fm,"FVG + BOS"
 if pc(em,bos)<1.0:return em,"EMA + BOS"
 return (fm,"FVG") if f else (bos,"BOS")
def bal():
 try:
  b=ex.fetch_balance(params={'accountType':'UNIFIED'})
  for acc in b.get('info',{}).get('result',{}).get('list',[]):
   for co in acc.get('coin',[]):
    if co.get('coin')=='USDT':
     v=co.get('equity')or co.get('walletBalance')
     if v:return float(v)
  return float(b.get('total',{}).get('USDT',0)or 0)
 except:return 0.0
def set_sl(sy,sl,tp):
 for idx in [0,1]:
  for _ in range(2):
   try:m=ex.market(sy);ex.private_post_v5_position_trading_stop({'category':'linear','symbol':m['id'],'stopLoss':str(ex.price_to_precision(sy,sl)),'takeProfit':str(ex.price_to_precision(sy,tp)),'tpslMode':'Full','positionIdx':idx});return True
   except:tm.sleep(0.5)
 return False
def set_be(sy,en):
 for idx in [0,1]:
  try:m=ex.market(sy);ex.private_post_v5_position_trading_stop({'category':'linear','symbol':m['id'],'stopLoss':str(ex.price_to_precision(sy,en)),'tpslMode':'Full','positionIdx':idx});return True
  except:0
 return False
def lev(en,sl,b):
 slp=abs(en-sl)/en if en else 0.01;lv=max(5,min(int(0.20/slp),10));mg=b*PCT
 if mg*lv*slp>mg*0.20:mg=(mg*0.20)/(lv*slp)
 return lv,max(0.6,min(mg,b*PCT))
def add(sy,sd,en,ex_,pn,rs):cl.append({"dt":datetime.now(W),"date":datetime.now(W).strftime("%Y-%m-%d"),"sym":sy,"side":sd,"entry":en,"exit":ex_,"pnl":pn,"res":rs});cl.pop(0) if len(cl)>200 else 0
def rep(p="daily"):
 now=datetime.now(W)
 if p=="daily":f=[c for c in cl if c["date"]==now.strftime("%Y-%m-%d")]
 elif p=="weekly":f=[c for c in cl if c["dt"]>=now-timedelta(days=now.weekday())]
 else:f=[c for c in cl if c["dt"].month==now.month]
 if not f:return f"📊 {p.upper()} - No closed ${bal():.2f}"
 tp=sum(c["pnl"] for c in f);w=len([c for c in f if c["pnl"]>0]);wr=w/len(f)*100 if f else 0;d="\n".join([f"{'🟢' if c['pnl']>0 else '🔴'} {c['sym']} {c['side']} {c['pnl']:+.2f}% {c['res']}" for c in f[-15:]]);return f"📊 {p.upper()} {now.strftime('%Y-%m-%d')} ${bal():.2f} T{len(f)} W{w} L{len(f)-w} WR{wr:.1f}% Tot{tp:+.2f}%\n\n{d}\nA{len(act)}/{MAXT}"
def smc(sym):
 raw=sym.replace(":USDT","");o1=ohlc(raw,'1h',100)
 if not o1 or len(o1)<60:return f"{sym}: No 1H",0,None
 ch=[c[4] for c in o1];e1=ema(ch,50);hb=ch[-1]>e1;ht="BULL" if hb else "BEAR";bs=0;bm="";bt=None
 for tf in TFS:
  o=ohlc(raw,tf,100)
  if not o or len(o)<60:continue
  cc=[c[4] for c in o];hh=[c[2] for c in o];ll=[c[3] for c in o];vv=[c[5] for c in o];last=cc[-1];em=ema(cc,50);rs=rsi(cc,14);vm=sum(vv[-20:])/20 if len(vv)>=20 else vv[-1];ph=max(hh[-30:-5]);pl=min(ll[-30:-5]);fb=hh[-3]<ll[-1];fbe=ll[-3]>hh[-1];fbm=(hh[-3]+ll[-1])/2 if fb else last;fbe_=(ll[-3]+hh[-1])/2 if fbe else last;sc=0
  if last>ph:
   if last>em:sc+=1
   if 50<rs<75:sc+=1
   if vv[-1]>vm*1.1:sc+=1
   if fb:sc+=1
   if hb:sc+=2
   if sc>=4 and sc>bs:
    bs=sc;en,re=be(last,ph,fb,fbm,em);sl=min(ll[-10:]);rk=en-sl;rk=en*0.015 if rk<=0 or rk<en*0.005 else rk;sl=en-rk;t1=en+rk*1.5;t2=en+rk*3
    bt={"symbol":sym,"side":"LONG","entry":en,"sl":sl,"tp1":t1,"tp2":t2,"risk":rk,"tf":tf,"entry_reason":re,"score":sc,"be":False,"amt":0,"last":last,"ht":ht}
    bm=f"{sym} LONG [{tf}] Q{sc}/6\n{fp(last)} {ht} {fp(en)} {re} SL{fp(sl)}\nTP1{fp(t1)} TP2{fp(t2)}"
  elif last<pl:
   if last<em:sc+=1
   if 25<rs<50:sc+=1
   if vv[-1]>vm*1.1:sc+=1
   if fbe:sc+=1
   if not hb:sc+=2
   if sc>=4 and sc>bs:
    bs=sc;en,re=be(last,pl,fbe,fbe_,em);sl=max(hh[-10:]);rk=sl-en;rk=en*0.015 if rk<=0 or rk<en*0.005 else rk;sl=en+rk;t1=en-rk*1.5;t2=en-rk*3
    bt={"symbol":sym,"side":"SHORT","entry":en,"sl":sl,"tp1":t1,"tp2":t2,"risk":rk,"tf":tf,"entry_reason":re,"score":sc,"be":False,"amt":0,"last":last,"ht":ht}
    bm=f"{sym} SHORT [{tf}] Q{sc}/6\n{fp(last)} {ht} {fp(en)} {re} SL{fp(sl)}\nTP1{fp(t1)} TP2{fp(t2)}"
 return (bm,1,bt) if bm else (f"{sym} Ranging {ht}",0,None)
def handle(c,hi,tr):
 if not hi or not tr:return 0,None
 if c in act:
  o=act[c]
  if o['side']==tr['side']:return 0,f"{c} already {o['side']}"
  cur=prc(c)or o['entry'];pn=(cur-o['entry'])/o['entry']*100 if o['side']=="LONG" else (o['entry']-cur)/o['entry']*100
  if pn>-0.8:return 0,f"FLIP {pn:+.1f}% need -0.8%"
  if tr.get('score',4)<5:return 0,f"score {tr.get('score')}/6"
  if tm.time()-lft.get(c,0)<5400:return 0,f"cooldown"
  close_one(c,"FLIP");snd(f"🔄 FLIP {c} {o['side']}->{tr['side']} {pn:+.2f}%");lft[c]=tm.time()
 act[c]=tr;return 1,None
def open_auto(tr):
 try:
  b=bal()
  if b<5 or len(act)>=MAXT:return None
  lv,mg=lev(tr['entry'],tr['sl'],b)
  try:ex.set_leverage(lv,tr['symbol'])
  except:0
  p=prc(tr['symbol'])
  if not p:return None
  qr=(mg*lv)/p;qr=(MINN*1.1)/p if qr*p<MINN else qr
  try:q=float(ex.amount_to_precision(tr['symbol'],qr))
  except:q=qr
  if q*p<0.9:return None
  sd='buy' if tr['side']=='LONG' else 'sell';ex.create_market_order(tr['symbol'],sd,q,params={'positionIdx':0});tm.sleep(1.8)
  if not set_sl(tr['symbol'],tr['sl'],tr['tp2']):
   try:ex.create_market_order(tr['symbol'],'sell' if tr['side']=='LONG' else 'buy',q,params={'reduceOnly':True,'positionIdx':0});snd(f"❌ SL FAILED - CLOSED {tr['symbol']} to protect (no SL)")
   except:0
   return None
  tr['entry']=p;tr['amt']=q;tr['lev']=lv;tr['margin']=mg;tr['qty_usd']=q*p;tr['bal']=bal();return tr
 except Exception as e: print(f"open_auto {e}"); return None
def close_one(sy,rs="MANUAL"):
 try:
  poss=ex.fetch_positions(params={'accountType':'UNIFIED','symbol':sy})
  found=False
  for po in poss:
   if po['symbol']!=sy:continue
   sz=float(po.get('contracts',0)or 0)
   if abs(sz)==0:continue
   found=True
   sz_f=float(po.get('size',sz)or sz);sd='sell' if po.get('side','').lower() in ['long','buy'] or sz_f>0 else 'buy'
   if sz_f<0 or po.get('side','').lower()=='short':sd='buy'
   amt=abs(sz_f);en=act[sy]['entry'] if sy in act else float(po.get('entryPrice',0)or 0);cur=prc(sy)or en
   try:ex.create_market_order(sy,sd,amt,params={'reduceOnly':True,'positionIdx':0})
   except:0
   if en and cur:
    s=act[sy]['side'] if sy in act else ("LONG" if sd=='sell' else "SHORT")
    pn=(cur-en)/en*100 if s=="LONG" else (en-cur)/en*100
    add(sy,s,en,cur,pn,rs)
   act.pop(sy,None);return amt
  if not found and sy in act:
   en=act[sy]['entry'];sd=act[sy]['side'];cur=prc(sy)or en;pn=(cur-en)/en*100 if sd=="LONG" else (en-cur)/en*100
   add(sy,sd,en,cur,pn,rs if rs!="MANUAL" else "EXCH_SL");act.pop(sy,None);return 1
 except Exception as e:print(f"close_one {e}")
 if sy in act:
  en=act[sy]['entry'];sd=act[sy]['side'];cur=prc(sy)or en;pn=(cur-en)/en*100 if sd=="LONG" else (en-cur)/en*100;add(sy,sd,en,cur,pn,rs);act.pop(sy,None)
 return 0
def close_all():
 c=0
 try:
  poss=ex.fetch_positions(params={'accountType':'UNIFIED'})
  real={p['symbol']:float(p.get('contracts',0)or 0) for p in poss if float(p.get('contracts',0)or 0)!=0}
  for sy in list(act.keys()):
   if sy not in real:
    en=act[sy]['entry'];sd=act[sy]['side'];cur=prc(sy)or en;pn=(cur-en)/en*100 if sd=="LONG" else (en-cur)/en*100;add(sy,sd,en,cur,pn,"CLOSEALL");c+=1;continue
  for po in poss:
   sz=float(po.get('contracts',0)or 0)
   if sz==0:continue
   sy=po['symbol'];sz_f=float(po.get('size',sz)or sz);sd='sell' if po.get('side','').lower() in ['long','buy'] or sz_f>0 else 'buy'
   if sz_f<0 or po.get('side','').lower()=='short':sd='buy';amt=abs(sz_f);en=act[sy]['entry'] if sy in act else float(po.get('entryPrice',0)or 0);cur=prc(sy)or en
   try:ex.create_market_order(sy,sd,amt,params={'reduceOnly':True,'positionIdx':0});en and cur and add(sy,act[sy]['side'] if sy in act else ("LONG" if sd=='sell' else "SHORT"),en,cur,(cur-en)/en*100 if (act[sy]['side'] if sy in act else "LONG")=="LONG" else (en-cur)/en*100,"CLOSEALL");c+=1;tm.sleep(0.3)
   except:0
  act.clear();return c
 except:act.clear();return c
def sync_exchange():
 try:
  poss=ex.fetch_positions(params={'accountType':'UNIFIED'})
  real={p['symbol']:float(p.get('contracts',0)or 0) for p in poss if abs(float(p.get('contracts',0)or 0))>0}
  for sy in list(act.keys()):
   if sy not in real:
    t=act[sy];cur=prc(sy)or t['entry'];en=t['entry'];sd=t['side'];pn=(cur-en)/en*100 if sd=="LONG" else (en-cur)/en*100
    if sd=="LONG":
     if cur>=t['tp2']:res="TP2"
     elif cur>=t['tp1']:res="TP1"
     elif cur<=t['sl']:res="SL"
     else:res="EXCH_CLOSED"
    else:
     if cur<=t['tp2']:res="TP2"
     elif cur<=t['tp1']:res="TP1"
     elif cur>=t['sl']:res="SL"
     else:res="EXCH_CLOSED"
    add(sy,sd,en,cur,pn,res)
    if "TP2" in res:snd(f"🎯 TP2 {sy} {pn:+.2f}% REAL HIT ${bal():.2f}\n\n"+rep("daily"))
    elif "SL" in res:snd(f"❌ SL {sy} {pn:+.2f}% REAL HIT ${bal():.2f}\n\n"+rep("daily"))
    elif "TP1" in res:snd(f"🎯 TP1 {sy} {pn:+.2f}% REAL HIT ${bal():.2f}")
    else:snd(f"⚠️ {sy} closed on Bybit {pn:+.2f}% {res} ${bal():.2f}\n\n"+rep("daily"))
    act.pop(sy,None)
 except Exception as e:print(f"sync {e}")

try:
 poss=ex.fetch_positions(params={'accountType':'UNIFIED'})
 for po in poss:
  sz=float(po.get('contracts',0)or 0)
  if sz!=0:
   sy=po['symbol'];en=float(po.get('entryPrice',0)or 0)
   if en==0:continue
   sd="LONG" if po.get('side','').lower() in ['long','buy'] or sz>0 else "SHORT"
   if sz<0:sd="SHORT"
   act[sy]={"symbol":sy,"side":sd,"entry":en,"sl":en*0.97 if sd=="LONG" else en*1.03,"tp1":en*1.02 if sd=="LONG" else en*0.98,"tp2":en*1.04 if sd=="LONG" else en*0.96,"tf":"REC","score":5,"be":False,"amt":abs(sz),"lev":5,"margin":0,"entry_reason":"Recovered"};set_sl(sy,act[sy]['sl'],act[sy]['tp2'])
except:0
snd(f"🚀 V3.3.3 PERFECTED WIF FIX ${bal():.2f} {len(act)}/{MAXT} SL GUARANTEED + SYNC")
while True:
 try:
  url=f"https://api.telegram.org/bot{TT}/getUpdates?offset={lid+1}&timeout=20";r=requests.get(url,timeout=25).json()
  for u in r.get("result",[]):
   lid=u["update_id"];txt=u.get("message",{}).get("text","")or""
   if not txt:continue
   low=txt.lower().strip();pts=txt.strip().split()
   if low in ["/start","/help"]:snd(f"V3.3.3 WIF FIX {'PAUSED' if ps else 'PLAYING'} ${bal():.2f} {len(act)}/{MAXT} /scan /trade /bal /pause /play /closeall /pnl /daily")
   elif low=="/status":snd(f"STATUS {'PAUSED' if ps else 'PLAYING'} ${bal():.2f} A{len(act)}/{MAXT}")
   elif low in ["/pnl","/report","/daily","/today","/weekly","/monthly","/trades","/trade","/activetrade","/active"]:
    if low in ["/trades","/trade","/activetrade","/active"]:
     if not act:
      try:poss=ex.fetch_positions(params={'accountType':'UNIFIED'});real=[p['symbol'] for p in poss if float(p.get('contracts',0)or 0)!=0];snd(f"{'Bybit has '+str(len(real))+': '+','.join(real) if real else 'No active'} ${bal():.2f}\n"+rep("daily"))
      except:snd(f"No active ${bal():.2f}\n"+rep("daily"))
     else:
      m=""
      for c_,t in list(act.items()):
       cur=prc(c_) or t['entry'];pn=(cur-t['entry'])/t['entry']*100
       if t['side']=="SHORT":pn=-pn
       m+=f"📊 {c_} {t['side']} {pn:+.2f}% BE:{t['be']} {fp(t['entry'])}->{fp(cur)} SL{fp(t['sl'])} TP2{fp(t['tp2'])}\n"
      snd(m+"\n"+rep("daily"))
    elif low in ["/pnl","/report"]:snd(rep("daily")+"\n\n"+rep("weekly")+"\n\n"+rep("monthly"))
    elif low in ["/daily","/today"]:snd(rep("daily"))
    elif low=="/weekly":snd(rep("weekly"))
    else:snd(rep("monthly"))
   elif low=="/pause":ps=True;snd(f"⏸️ PAUSED ${bal():.2f}")
   elif low in ["/play","/resume","/unpause"]:ps=False;snd(f"▶️ RESUMED ${bal():.2f}")
   elif low=="/bal":snd(f"💰 ${bal():.2f} {len(act)}/{MAXT}")
   elif low in ["/stop","/closeall","/close"]:n=close_all();snd(f"✅ CLOSED {n} ${bal():.2f}\n\n"+rep("daily"))
   elif low.startswith("/price"):
    if len(pts)<2:snd("Use /price ZEC")
    else:co=pts[1].upper()+"/USDT:USDT";p=prc(co);snd(f"💰 {pts[1].upper()} = {fp(p)}" if p else "No data")
   elif low.startswith("/coin"):
    if len(pts)<2:snd("Use /coin ZEC")
    else:
     co=pts[1].upper()+"/USDT:USDT";snd(f"🔍 {co}...");a,ok,tr=smc(co);snd(f"🔴 LIVE\n\n{a}");al,msg=handle(co,ok,tr) if ok else (0,None)
     if al:
      ot=open_auto(tr)
      if ot:act[ot['symbol']]=ot;snd(f"⚪ {ot['symbol']} {ot['side']} {ot['lev']}x {ot['amt']} {fp(ot['qty_usd'])}\nbal {fp(ot['bal'])}")
      else:snd("❌ OPEN FAIL or SL FAIL - protected")
     elif msg:snd(msg)
   elif low=="/scan":
    if ps:snd("⏸️ PAUSED use /play");continue
    snd("🔍 SCAN 12 coins...");hq=[]
    for co in WL:
     if lta.get(co,0)>tm.time()-5400:continue
     an,hi,tr=smc(co)
     if hi and tr:
      if co in act and act[co]['side']==tr['side']:continue
      al,msg=handle(co,hi,tr)
      if al:
       ot=open_auto(tr)
       if ot:
        act[ot['symbol']]=ot
        snd(f"🔴 LIVE\n\n{ot['symbol']} {ot['side']} [{ot['tf']}] Q{ot['score']}/6\n{fp(tr['last'])} {ht} {fp(ot['entry'])} {ot['entry_reason']} SL{fp(ot['sl'])}\nTP1{fp(ot['tp1'])} TP2{fp(ot['tp2'])}\n\n⚪ {ot['symbol']} {ot['side']} {ot['lev']}x {round(ot['amt'],4)} {fp(ot['qty_usd'])}\nbal {fp(ot['bal'])}")
        hq.append(f"{co}({tr['tf']})");lta[co]=tm.time()
       else:snd(f"🔴 LIVE\n\n{an}\n\n⚪ {co} FAILED SL - protected")
      elif msg:continue
     tm.sleep(0.4)
    if not hq:snd("⚪ No A+")
  now=datetime.now(W);today=now.strftime("%Y-%m-%d");now_ts=tm.time()
  if ld!=today and now.hour==23 and now.minute>=59:snd("⏰ DAILY\n\n"+rep("daily"));ld=today
  if now.weekday()==6 and now.hour==23 and now.minute>=59 and lw!=today:snd("⏰ WEEKLY\n\n"+rep("weekly"));lw=today
  if (now+timedelta(days=1)).month!=now.month and now.hour==23 and now.minute>=59 and lm!=today:snd("⏰ MONTHLY\n\n"+rep("monthly"));lm=today
  if not ps and now_ts-ls>SEC:
   ls=now_ts
   sync_exchange()
   for co in WL:
    if lta.get(co,0)>now_ts-5400:continue
    an,hi,tr=smc(co)
    if hi and tr:
     if co in act and act[co]['side']==tr['side']:continue
     o=act.get(co)
     if o and o['side']!=tr['side']:
      cur=prc(co)or o['entry'];pn=(cur-o['entry'])/o['entry']*100 if o['side']=="LONG" else (o['entry']-cur)/o['entry']*100
      if pn<=-0.8 and tr.get('score',4)>=5 and tm.time()-lft.get(co,0)>=5400:close_one(co,"FLIP");lft[co]=tm.time();ot=open_auto(tr)
      if ot:act[ot['symbol']]=ot;snd(f"🔴 LIVE\n\n{ot['symbol']} {ot['side']} [{ot['tf']}] Q{ot['score']}/6\n{fp(tr['last'])} {tr['ht']} {fp(ot['entry'])} {ot['entry_reason']} SL{fp(ot['sl'])}\nTP1{fp(ot['tp1'])} TP2{fp(ot['tp2'])}\n\n⚪ {ot['symbol']} {ot['side']} {ot['lev']}x {round(ot['amt'],4)} {fp(ot['qty_usd'])}\nbal {fp(ot['bal'])}");lta[co]=now_ts
     else:lta[co]=now_ts;ot=open_auto(tr)
     if ot:act[ot['symbol']]=ot;snd(f"🔴 LIVE\n\n{ot['symbol']} {ot['side']} [{ot['tf']}] Q{ot['score']}/6\n{fp(tr['last'])} {tr['ht']} {fp(ot['entry'])} {ot['entry_reason']} SL{fp(ot['sl'])}\nTP1{fp(ot['tp1'])} TP2{fp(ot['tp2'])}\n\n⚪ {ot['symbol']} {ot['side']} {ot['lev']}x {round(ot['amt'],4)} {fp(ot['qty_usd'])}\nbal {fp(ot['bal'])}")
    tm.sleep(0.4)
   sync_exchange()
   for sy,t in list(act.items()):
    cur=prc(sy)
    if not cur:continue
    en=t['entry'];sd=t['side'];pn=(cur-en)/en*100 if sd=="LONG" else (en-cur)/en*100
    if not t['be'] and ((sd=="LONG" and cur>=t['tp1']) or (sd=="SHORT" and cur<=t['tp1'])):
     try:amt=float(ex.amount_to_precision(sy,t['amt']*0.5));side='sell' if sd=="LONG" else 'buy';ex.create_market_order(sy,side,amt,params={'reduceOnly':True,'positionIdx':0});t['amt']*=0.5;t['be']=True;set_be(sy,en);snd(f"🎯 {sy} TP1 {fp(cur)} {pn:+.2f}% 50% BE ${bal():.2f}")
     except:0
    if sd=="LONG":
     if cur>=t['tp2']:close_one(sy,"TP2");snd(f"🎯 TP2 {sy} {pn:+.2f}% 🎉 ${bal():.2f}\n\n"+rep("daily"))
     elif cur<=t['sl']:
      if t['be']:close_one(sy,"BE");snd(f"🔒 BE {sy} ${bal():.2f}")
      else:close_one(sy,"SL");snd(f"❌ SL {sy} {pn:+.2f}% ${bal():.2f}\n\n"+rep("daily"))
    else:
     if cur<=t['tp2']:close_one(sy,"TP2");snd(f"🎯 TP2 {sy} {pn:+.2f}% 🎉 ${bal():.2f}\n\n"+rep("daily"))
     elif cur>=t['sl']:
      if t['be']:close_one(sy,"BE");snd(f"🔒 BE {sy} ${bal():.2f}")
      else:close_one(sy,"SL");snd(f"❌ SL {sy} {pn:+.2f}% ${bal():.2f}\n\n"+rep("daily"))
 except Exception as e:print(f"loop {e}");tm.sleep(3)
