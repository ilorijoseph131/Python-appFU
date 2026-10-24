from flask import Flask
from threading import Thread
app=Flask(__name__)
@app.route('/')
def home():return "V3.2.31 EARLY FLIP"
def run_flask():app.run(host='0.0.0.0',port=10000)
Thread(target=run_flask,daemon=True).start()
import os,ccxt,requests,time,calendar
from datetime import datetime,timezone,timedelta
BOT=os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
CHAT=os.getenv("CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
KEY=os.getenv("BYBIT_API_KEY","").strip()
SEC=os.getenv("BYBIT_SECRET","").strip()
ex=ccxt.bybit({'apiKey':KEY,'secret':SEC,'enableRateLimit':True,'options':{'defaultType':'unified'}})
try:ex.load_markets()
except:pass
WAT=timezone(timedelta(hours=1))
WL=["SOL/USDT:USDT","DOGE/USDT:USDT","BONK/USDT:USDT","WIF/USDT:USDT","DOT/USDT:USDT","AVAX/USDT:USDT"]
TFS=['15m','30m','1h','2h']
closed=[]
def add_c(sym,side,tf,en,sl,tp1,tp2,res,pnl):
 now=datetime.now(WAT)
 closed.append({"d":now.strftime("%Y-%m-%d"),"dt":now,"sym":sym,"side":side,"tf":tf,"res":res,"pnl":pnl})
def send(m):
 try:requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage",data={"chat_id":CHAT,"text":m[:4000]},timeout=10)
 except:pass
def fp(p):
 if not p:return "N/A"
 return f"${p:.6f}" if p<0.01 else f"${p:.5f}" if p<1 else f"${p:.4f}" if p<100 else f"${p:.2f}"
def ohlc(s,tf,l=100):
 try:return ex.fetch_ohlcv(s,tf,limit=l)
 except:return None
def price(s):
 try:return float(ex.fetch_ticker(s)['last'])
 except:
  o=ohlc(s,'1h',5);return float(o[-1][4]) if o else None
def bal():
 try:b=ex.fetch_balance(params={'accountType':'UNIFIED'});return float(b['total'].get('USDT',0) or 0)
 except:return 0
def rsi(cs,p=14):
 if len(cs)<p+1:return 50
 g=[];l=[]
 for i in range(1,len(cs)):d=cs[i]-cs[i-1];g.append(max(d,0));l.append(max(-d,0))
 ag=sum(g[-p:])/p;al=sum(l[-p:])/p
 return 70 if al==0 else 100-(100/(1+ag/al))
def ema(cs,p=50):
 if len(cs)<p:return cs[-1]
 k=2/(p+1);e=sum(cs[:p])/p
 for x in cs[p:]:e=x*k+e*(1-k)
 return e
def smc(sym,force_side=None,min_score=4):
 o1=ohlc(sym,'1h',100)
 if not o1 or len(o1)<60:return f"⚪ {sym} Ranging",False,None
 c1=[x[4] for x in o1];e1=ema(c1,50);bull=c1[-1]>e1
 best=0;msg="";tr=None
 for tf in TFS:
  o=ohlc(sym,tf,100)
  if not o or len(o)<60:continue
  cs=[x[4] for x in o];hs=[x[2] for x in o];ls=[x[3] for x in o];vs=[x[5] for x in o]
  last=cs[-1];em=ema(cs,50);rs=rsi(cs,14);vm=sum(vs[-20:])/20
  ph=max(hs[-30:-5]);pl=min(ls[-30:-5]);fb=hs[-3]<ls[-1];fs=ls[-3]>hs[-1]
  if (force_side is None or force_side=="LONG") and last>ph and bull:
   sc=0
   if last>em:sc+=1
   if 50<rs<75:sc+=1
   if vs[-1]>vm*1.1:sc+=1
   if fb:sc+=1
   if bull:sc+=2
   if sc>=min_score and sc>best:
    best=sc;sl=min(ls[-10:]);rk=last-sl
    if rk<=0:rk=last*0.015;sl=last-rk
    tp1=last+rk*1.5;tp2=last+rk*3
    tr={"sym":sym,"side":"LONG","entry":last,"sl":sl,"tp1":tp1,"tp2":tp2,"tf":tf,"be":False,"sc":sc,"amt":0}
    msg=f"🟢 {sym} LONG [{tf}] {sc}/6"
  if (force_side is None or force_side=="SHORT") and last<pl and not bull:
   sc=0
   if last<em:sc+=1
   if 25<rs<50:sc+=1
   if vs[-1]>vm*1.1:sc+=1
   if fs:sc+=1
   if not bull:sc+=2
   if sc>=min_score and sc>best:
    best=sc;sl=max(hs[-10:]);rk=sl-last
    if rk<=0:rk=last*0.015;sl=last+rk
    tp1=last-rk*1.5;tp2=last-rk*3
    tr={"sym":sym,"side":"SHORT","entry":last,"sl":sl,"tp1":tp1,"tp2":tp2,"tf":tf,"be":False,"sc":sc,"amt":0}
    msg=f"🔴 {sym} SHORT [{tf}] {sc}/6"
 if msg:return msg,True,tr
 return f"⚪ {sym} Ranging",False,None
def lev(en,sl):
 d=abs(en-sl)/en if en else 0.01
 ml=0.2/d if d>0 else 5
 return max(5,min(int(ml),6))
def open_p(sym,side,lv,mg,sl,tp2):
 try:
  try:ex.set_leverage(lv,sym,params={'marginMode':'cross'})
  except:pass
  pr=price(sym)
  if not pr:return None,0,0
  raw=(mg*lv)/pr
  try:am=float(ex.amount_to_precision(sym,raw))
  except:am=raw
  if am*pr<5.5:am=5.6/pr
  try:am=float(ex.amount_to_precision(sym,am))
  except:pass
  sd='buy' if side=='LONG' else 'sell'
  o=ex.create_market_order(sym,sd,am,params={'positionIdx':0})
  try:ex.set_trading_stop(sym,0,stopLoss=ex.price_to_precision(sym,sl),takeProfit=ex.price_to_precision(sym,tp2),params={'positionIdx':0,'tpslMode':'Full'})
  except:pass
  return o,am,pr
 except Exception as e:send(f"❌ OPEN FAIL {sym}:{e}");return None,0,0
def close_p(sym,side,am,p=100):
 try:
  sd='sell' if side=='LONG' else 'buy';amt=float(ex.amount_to_precision(sym,am*p/100))
  ex.create_market_order(sym,sd,amt,params={'reduceOnly':True,'positionIdx':0})
 except:pass
def set_be(sym,en):
 try:ex.set_trading_stop(sym,0,stopLoss=ex.price_to_precision(sym,en),params={'positionIdx':0})
 except:pass
def report(period,items):
 if not items:return f"📅 {period.upper()} {datetime.now(WAT).strftime('%Y-%m-%d')}\n💰 ${bal():.2f} No trades"
 tp1=len([x for x in items if x['res']=='TP1']);tp2=len([x for x in items if x['res']=='TP2']);sl=len([x for x in items if x['res']=='SL']);pnl=sum([x['pnl'] for x in items])
 return f"📅 {period.upper()} {datetime.now(WAT).strftime('%Y-%m-%d')}\n💰 ${bal():.2f}\n📊 {len(items)} TP1 {tp1} TP2 {tp2} SL {sl}\n💹 {pnl:+.2f}% {'🟢' if pnl>=0 else '🔴'}"
active={}
try:
 ps=ex.fetch_positions(params={'accountType':'UNIFIED'})
 for po in ps:
  co=float(po.get('contracts',0) or 0)
  if co!=0:
   sy=po['symbol'];sd="LONG" if po['side']=='long' or co>0 else "SHORT";en=float(po.get('entryPrice',0) or 0)
   if en==0:continue
   active[sy]={"sym":sy,"side":sd,"entry":en,"sl":en*0.95 if sd=="LONG" else en*1.05,"tp1":en*1.02 if sd=="LONG" else en*0.98,"tp2":en*1.04 if sd=="LONG" else en*0.96,"tf":"REC","be":False,"sc":5,"amt":abs(co)}
except:pass
send(f"🚀 V3.2.31 EARLY FLIP LIVE {len(active)} rec 💰 ${bal():.2f}")
last_id=0;last_chk=0;last_scan=0;last_day="";last_week="";last_month=""
while True:
 try:
  r=requests.get(f"https://api.telegram.org/bot{BOT}/getUpdates?offset={last_id+1}&timeout=20",timeout=25).json()
  for u in r.get("result",[]):
   last_id=u["update_id"];txt=u.get("message",{}).get("text","")
   if not txt:continue
   low=txt.lower().strip()
   if low in ["/start","/help"]:send("📋 /scan /trades /today /week /month /bal /stop EARLY FLIP")
   elif low=="/bal":send(f"💰 Bal ${bal():.2f} Active {len(active)}/1")
   elif low=="/trades":
    if not active:send("⚪ No active - auto 10m")
    else:
     m="📊 ACTIVE 🛡️\n"
     for c,t in active.items():
      cur=price(c);pn=(cur-t['entry'])/t['entry']*100 if cur else 0
      if t['side']=="SHORT":pn=-pn
      m+=f"{c} {t['side']} {fp(t['entry'])} {pn:+.1f}% BE:{t['be']}\n"
     send(m)
   elif low=="/today":
    td=datetime.now(WAT).strftime("%Y-%m-%d");ts=[x for x in closed if x['d']==td];send(report("TODAY",ts))
   elif low=="/week":
    now=datetime.now(WAT);ts=[x for x in closed if x['dt'].isocalendar()[1]==now.isocalendar()[1] and x['dt'].year==now.year];send(report("WEEKLY",ts))
   elif low=="/month":
    now=datetime.now(WAT);ts=[x for x in closed if x['dt'].month==now.month and x['dt'].year==now.year];send(report("MONTHLY",ts))
   elif low=="/scan":
    if len(active)>=1:send(f"⚠️ Already {len(active)}/1 active");continue
    send("🔍 MANUAL SCAN...")
    rep="📊 SCAN:\n";op=False
    for coin in WL:
     a,ok,tr=smc(coin);rep+=a+"\n"
     if ok and not op:
      b=bal();lv=lev(tr['entry'],tr['sl']);mg=max(1.0,b*0.33);o,am,pr=open_p(coin,tr['side'],lv,mg,tr['sl'],tr['tp2'])
      if o:tr['amt']=am;tr['entry']=pr;active[coin]=tr;rep+=f"✅ OPENED {coin}\n";op=True
     time.sleep(0.2)
    if not op:rep+="\n⚪ No setup"
    send(rep)
   elif low=="/stop":
    for c,t in list(active.items()):close_p(c,t['side'],t['amt'],100)
    active.clear();send("🛑 All closed")
  nt=time.time();now=datetime.now(WAT)
  if nt-last_scan>600 and len(active)<1:
   last_scan=nt;send("🤖 AUTO SCAN...")
   arep="🤖 AUTO:\n";opened=False
   for coin in WL:
    a,ok,tr=smc(coin);arep+=a+"\n"
    if ok and not opened:
     b=bal();lv=lev(tr['entry'],tr['sl']);mg=max(1.0,b*0.33);o,am,pr=open_p(coin,tr['side'],lv,mg,tr['sl'],tr['tp2'])
     if o:tr['amt']=am;tr['entry']=pr;active[coin]=tr;arep+=f"🚀 AUTO OPENED {coin} {tr['side']}\n";opened=True
    time.sleep(0.2)
   send(arep if opened else arep+"\n💤 No setup")
  if now.hour==23 and now.minute>=59 and now.strftime("%Y-%m-%d")!=last_day:
   td=now.strftime("%Y-%m-%d");ts=[x for x in closed if x['d']==td];send(report("DAILY AUTO",ts));last_day=td
  if now.weekday()==6 and now.hour==23 and now.minute>=59 and str(now.isocalendar()[1])!=last_week:
   ts=[x for x in closed if x['dt'].isocalendar()[1]==now.isocalendar()[1] and x['dt'].year==now.year];send(report("WEEKLY AUTO",ts));last_week=str(now.isocalendar()[1])
  ld=calendar.monthrange(now.year,now.month)[1]
  if now.day==ld and now.hour==23 and now.minute>=59 and f"{now.year}-{now.month}"!=last_month:
   ts=[x for x in closed if x['dt'].month==now.month and x['dt'].year==now.year];send(report("MONTHLY AUTO",ts));last_month=f"{now.year}-{now.month}"
  if nt-last_chk>120:
   last_chk=nt
   for c,t in list(active.items()):
    pr=price(c)
    if not pr:continue
    en=t['entry'];sd=t['side'];pn=(pr-en)/en*100 if sd=="LONG" else (en-pr)/en*100
    # EARLY FLIP CHECK - strong opposite signal 5/6
    opp="SHORT" if sd=="LONG" else "LONG"
    a_opp,ok_opp,tr_opp=smc(c,force_side=opp,min_score=5)
    if ok_opp and tr_opp and tr_opp['sc']>=5:
     close_p(c,sd,t['amt'],100);add_c(c,sd,t['tf'],en,t['sl'],t['tp1'],t['tp2'],"EARLY_FLIP",pn);del active[c]
     send(f"🔄 EARLY FLIP {c} {sd} {pn:+.1f}% closed → {opp} {tr_opp['sc']}/6 strong reversal")
     b=bal();lv=lev(tr_opp['entry'],tr_opp['sl']);mg=max(1.0,b*0.33);o,am,pr2=open_p(c,opp,lv,mg,tr_opp['sl'],tr_opp['tp2'])
     if o:tr_opp['amt']=am;tr_opp['entry']=pr2;active[c]=tr_opp;send(f"🚀 FLIPPED TO {opp} {c} 💰{fp(pr2)} 🛑{fp(tr_opp['sl'])}")
     continue
    if not t['be']:
     if (sd=="LONG" and pr>=t['tp1']) or (sd=="SHORT" and pr<=t['tp1']):
      close_p(c,sd,t['amt'],50);t['amt']*=0.5;add_c(c,sd,t['tf'],en,t['sl'],t['tp1'],t['tp2'],"TP1",pn*0.5);t['be']=True;set_be(c,en);send(f"🎯 TP1 {c} {pn:+.1f}% BE {fp(en)}")
    if sd=="LONG":
     if pr<=t['sl']:
      close_p(c,sd,t['amt'],100);add_c(c,sd,t['tf'],en,t['sl'],t['tp1'],t['tp2'],"SL",pn);del active[c];send(f"🛑 SL {c} {pn:+.1f}% → flip check")
      time.sleep(0.5);a2,ok2,tr2=smc(c,force_side="SHORT",min_score=4)
      if ok2:
       b=bal();lv=lev(tr2['entry'],tr2['sl']);mg=max(1.0,b*0.33);o,am,pr2=open_p(c,"SHORT",lv,mg,tr2['sl'],tr2['tp2'])
       if o:tr2['amt']=am;tr2['entry']=pr2;active[c]=tr2;send(f"🔄 AUTO FLIP SHORT {c} {tr2['sc']}/6")
     elif pr>=t['tp2']:close_p(c,sd,t['amt'],100);add_c(c,sd,t['tf'],en,t['sl'],t['tp1'],t['tp2'],"TP2",pn);del active[c];send(f"💰 TP2 {c} {pn:+.1f}%")
    else:
     if pr>=t['sl']:
      close_p(c,sd,t['amt'],100);add_c(c,sd,t['tf'],en,t['sl'],t['tp1'],t['tp2'],"SL",pn);del active[c];send(f"🛑 SL {c} {pn:+.1f}% → flip check")
      time.sleep(0.5);a2,ok2,tr2=smc(c,force_side="LONG",min_score=4)
      if ok2:
       b=bal();lv=lev(tr2['entry'],tr2['sl']);mg=max(1.0,b*0.33);o,am,pr2=open_p(c,"LONG",lv,mg,tr2['sl'],tr2['tp2'])
       if o:tr2['amt']=am;tr2['entry']=pr2;active[c]=tr2;send(f"🔄 AUTO FLIP LONG {c} {tr2['sc']}/6")
     elif pr<=t['tp2']:close_p(c,sd,t['amt'],100);add_c(c,sd,t['tf'],en,t['sl'],t['tp1'],t['tp2'],"TP2",pn);del active[c];send(f"💰 TP2 {c} {pn:+.1f}%")
 except Exception as e:print(f"err {e}");time.sleep(3)
