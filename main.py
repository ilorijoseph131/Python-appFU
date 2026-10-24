from flask import Flask
from threading import Thread
app=Flask(__name__)
@app.route('/')
def home():return "V3.2.28 AUTO REPORTS"
def run_flask():app.run(host='0.0.0.0',port=10000)
Thread(target=run_flask,daemon=True).start()
import os,ccxt,requests,time
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
def smc(sym):
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
  sc=0
  if last>ph:
   if last>em:sc+=1
   if 50<rs<75:sc+=1
   if vs[-1]>vm*1.1:sc+=1
   if fb:sc+=1
   if bull:sc+=2
   if sc>=4 and sc>best:
    best=sc;sl=min(ls[-10:]);rk=last-sl
    if rk<=0:rk=last*0.015;sl=last-rk
    tp1=last+rk*1.5;tp2=last+rk*3
    tr={"sym":sym,"side":"LONG","entry":last,"sl":sl,"tp1":tp1,"tp2":tp2,"tf":tf,"be":False,"sc":sc,"amt":0}
    msg=f"🟢 {sym} LONG [{tf}] {sc}/6 💰{fp(last)}"
  elif last<pl:
   if last<em:sc+=1
   if 25<rs<50:sc+=1
   if vs[-1]>vm*1.1:sc+=1
   if fs:sc+=1
   if not bull:sc+=2
   if sc>=4 and sc>best:
    best=sc;sl=max(hs[-10:]);rk=sl-last
    if rk<=0:rk=last*0.015;sl=last+rk
    tp1=last-rk*1.5;tp2=last-rk*3
    tr={"sym":sym,"side":"SHORT","entry":last,"sl":sl,"tp1":tp1,"tp2":tp2,"tf":tf,"be":False,"sc":sc,"amt":0}
    msg=f"🔴 {sym} SHORT [{tf}] {sc}/6 💰{fp(last)}"
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
 if not items:return f"📅 {period.upper()} REPORT\n💰 Bal ${bal():.2f}\n📊 No trades"
 tp1=len([x for x in items if x['res']=='TP1']);tp2=len([x for x in items if x['res']=='TP2']);sl=len([x for x in items if x['res']=='SL']);pnl=sum([x['pnl'] for x in items])
 return f"📅 {period.upper()} REPORT {datetime.now(WAT).strftime('%Y-%m-%d')}\n💰 Bal ${bal():.2f}\n📊 Trades {len(items)} | TP1 {tp1} TP2 {tp2} SL {sl}\n💹 PnL {pnl:+.2f}% {'🟢' if pnl>=0 else '🔴'}"
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
send(f"🚀 V3.2.28 LIVE 📊 AUTO REPORTS D/W/M {len(active)} rec 💰 ${bal():.2f}")
last_id=0;last_chk=0;last_day="";last_week="";last_month=""
while True:
 try:
  r=requests.get(f"https://api.telegram.org/bot{BOT}/getUpdates?offset={last_id+1}&timeout=20",timeout=25).json()
  for u in r.get("result",[]):
   last_id=u["update_id"];txt=u.get("message",{}).get("text","")
   if not txt:continue
   low=txt.lower().strip()
   if low in ["/start","/help"]:send("📋 /scan /trades /today /week /month /bal /stop V3.2.28")
   elif low=="/bal":send(f"💰 Bal ${bal():.2f} 📊 Active {len(active)}/1")
   elif low=="/trades":
    if not active:send("⚪ No active")
    else:
     m="📊 ACTIVE 🛡️\n"
     for c,t in active.items():
      cur=price(c);pn=(cur-t['entry'])/t['entry']*100 if cur else 0
      if t['side']=="SHORT":pn=-pn
      m+=f"{c} {t['side']} {fp(t['entry'])} {pn:+.1f}%\n"
     send(m)
   elif low=="/today":
    td=datetime.now(WAT).strftime("%Y-%m-%d");ts=[x for x in closed if x['d']==td];send(report("today",ts))
   elif low=="/week":
    now=datetime.now(WAT);ts=[x for x in closed if x['dt'].isocalendar()[1]==now.isocalendar()[1] and x['dt'].year==now.year];send(report("weekly",ts))
   elif low=="/month":
    now=datetime.now(WAT);ts=[x for x in closed if x['dt'].month==now.month and x['dt'].year==now.year];send(report("monthly",ts))
   elif low=="/scan":
    if len(active)>=1:send(f"⚠️ Already {len(active)}/1 active");continue
    send("🔍 SCAN 6 coins...")
    rep="📊 SCAN:\n";opened=False
    for coin in WL:
     a,ok,tr=smc(coin);rep+=a+"\n"
     if ok and not opened:
      b=bal();lv=lev(tr['entry'],tr['sl']);mg=max(1.0,b*0.33);o,am,pr=open_p(coin,tr['side'],lv,mg,tr['sl'],tr['tp2'])
      if o:tr['amt']=am;tr['entry']=pr;active[coin]=tr;rep+=f"✅ OPENED {coin}\n";opened=True
     time.sleep(0.2)
    if not opened:rep+="\n⚪ No setup 4/6"
    send(rep)
   elif low=="/stop":
    for c,t in list(active.items()):close_p(c,t['side'],t['amt'],100)
    active.clear();send("🛑 Cleared")
   elif low=="/status":send(f"✅ V3.2.28 Auto D/W/M Active {len(active)} 💰 ${bal():.2f}")
  nt=time.time();now=datetime.now(WAT)
  # DAILY AUTO 23:59 WAT
  if now.hour==23 and now.minute>=59 and now.strftime("%Y-%m-%d")!=last_day:
   td=now.strftime("%Y-%m-%d");ts=[x for x in closed if x['d']==td];send(report("daily auto",ts));last_day=td
  # WEEKLY AUTO SUNDAY 23:59
  if now.weekday()==6 and now.hour==23 and now.minute>=59 and str(now.isocalendar()[1])!=last_week:
   ts=[x for x in closed if x['dt'].isocalendar()[1]==now.isocalendar()[1] and x['dt'].year==now.year];send(report("weekly auto",ts));last_week=str(now.isocalendar()[1])
  # MONTHLY AUTO LAST DAY 23:59
  import calendar
  ld=calendar.monthrange(now.year,now.month)[1]
  if now.day==ld and now.hour==23 and now.minute>=59 and f"{now.year}-{now.month}"!=last_month:
   ts=[x for x in closed if x['dt'].month==now.month and x['dt'].year==now.year];send(report("monthly auto",ts));last_month=f"{now.year}-{now.month}"
  if nt-last_chk>120:
   last_chk=nt
   for c,t in list(active.items()):
    pr=price(c)
    if not pr:continue
    en=t['entry'];sd=t['side'];pn=(pr-en)/en*100 if sd=="LONG" else (en-pr)/en*100
    if not t['be']:
     if (sd=="LONG" and pr>=t['tp1']) or (sd=="SHORT" and pr<=t['tp1']):
      close_p(c,sd,t['amt'],50);t['amt']*=0.5;add_c(c,sd,t['tf'],en,t['sl'],t['tp1'],t['tp2'],"TP1",pn*0.5);t['be']=True;set_be(c,en);send(f"🎯 TP1 {c} {pn:+.1f}% BE {fp(en)} 🛡️")
    if sd=="LONG":
     if pr<=t['sl']:close_p(c,sd,t['amt'],100);add_c(c,sd,t['tf'],en,t['sl'],t['tp1'],t['tp2'],"SL",pn);del active[c];send(f"🛑 SL {c} {pn:+.1f}%")
     elif pr>=t['tp2']:close_p(c,sd,t['amt'],100);add_c(c,sd,t['tf'],en,t['sl'],t['tp1'],t['tp2'],"TP2",pn);del active[c];send(f"💰 TP2 {c} {pn:+.1f}%")
    else:
     if pr>=t['sl']:close_p(c,sd,t['amt'],100);add_c(c,sd,t['tf'],en,t['sl'],t['tp1'],t['tp2'],"SL",pn);del active[c];send(f"🛑 SL {c} {pn:+.1f}%")
     elif pr<=t['tp2']:close_p(c,sd,t['amt'],100);add_c(c,sd,t['tf'],en,t['sl'],t['tp1'],t['tp2'],"TP2",pn);del active[c];send(f"💰 TP2 {c} {pn:+.1f}%")
 except Exception as e:print(f"err {e}");time.sleep(3)
