from flask import Flask
from threading import Thread
app = Flask(__name__)
@app.route('/')
def home(): return "BYBIT V4.2 TEST $2.70 5MIN LIVE"
def run_flask(): app.run(host='0.0.0.0', port=10000)
Thread(target=run_flask, daemon=True).start()

import os, ccxt, requests, time, calendar
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or ""
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or ""
API_KEY = os.getenv("BYBIT_API_KEY","").strip()
API_SECRET = os.getenv("BYBIT_SECRET","").strip()

ex = ccxt.bybit({'apiKey':API_KEY,'secret':API_SECRET,'enableRateLimit':True,'options':{'defaultType':'unified'}})
try: ex.load_markets()
except: pass

WAT = timezone(timedelta(hours=1))
WATCHLIST = ["BTC/USDT:USDT","AVAX/USDT:USDT","DOGE/USDT:USDT","SOL/USDT:USDT","BONK/USDT:USDT","PAXG/USDT:USDT","ONDO/USDT:USDT"]
SCAN_TFS = ['15m','30m','1h','2h']

MAX_TRADES = 1
TEST_MODE = True
AUTO_SCAN_SEC = 300  # 5 MINUTES

closed=[]; active={}; paused=False

def bal():
    try:
        b=ex.fetch_balance(params={'accountType':'UNIFIED'})
        info=b.get('info',{}).get('result',{}).get('list',[])
        for acc in info:
            for c in acc.get('coin',[]):
                if c.get('coin')=='USDT':
                    v=c.get('equity') or c.get('walletBalance')
                    if v: return float(v)
        return float(b.get('total',{}).get('USDT',0) or 0)
    except: return 0

def send(m):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id":CHAT_ID,"text":m[:3900],"parse_mode":"Markdown"}, timeout=15)
    except: pass

def fmt(p):
    if not p: return "N/A"
    if p<0.01: return f"${p:.6f}"
    if p<1: return f"${p:.5f}"
    if p<100: return f"${p:.4f}"
    return f"${p:.2f}"

def ohlc(s,t,l=100):
    try: return ex.fetch_ohlcv(s,t,limit=l)
    except: return None

def price(s):
    try: return float(ex.fetch_ticker(s)['last'])
    except:
        o=ohlc(s,'1h',5); return float(o[-1][4]) if o else None

def rsi(cs,p=14):
    if len(cs)<p+1: return 50
    g=[]; l=[]
    for i in range(1,len(cs)):
        d=cs[i]-cs[i-1]
        g.append(max(d,0)); l.append(max(-d,0))
    ag=sum(g[-p:])/p; al=sum(l[-p:])/p
    return 70 if al==0 else 100-(100/(1+ag/al))

def ema(cs,p=50):
    if len(cs)<p: return cs[-1]
    k=2/(p+1); e=sum(cs[:p])/p
    for x in cs[p:]: e=x*k+e*(1-k)
    return e

def smc(sym):
    o1=ohlc(sym,'1h',100)
    if not o1 or len(o1)<60: return None
    c1=[x[4] for x in o1]; e1=ema(c1,50); bull1=c1[-1]>e1
    best=None; bs=0
    for tf in SCAN_TFS:
        o=ohlc(sym,tf,100)
        if not o or len(o)<60: continue
        cs=[x[4] for x in o]; hs=[x[2] for x in o]; ls=[x[3] for x in o]; vs=[x[5] for x in o]
        last=cs[-1]; e50=ema(cs,50); rv=rsi(cs,14)
        vma=sum(vs[-20:])/20 if len(vs)>=20 else vs[-1]
        ph=max(hs[-21:-1]); pl=min(ls[-21:-1])
        fvg_bull=hs[-3]<ls[-1]; fvg_bear=ls[-3]>hs[-1]
        fvg_mid=(hs[-3]+ls[-1])/2 if fvg_bull else (ls[-3]+hs[-1])/2 if fvg_bear else last
        score=0
        if last>ph:
            if last>e50: score+=1
            if 45<rv<78: score+=1
            if vs[-1]>vma*1.05: score+=1
            if fvg_bull: score+=1
            if bull1: score+=2
            if score>=4 and score>bs:
                entry=fvg_mid if fvg_bull and abs(fvg_mid-ph)/ph<0.008 else ph
                sl=min(ls[-10:]); risk=entry-sl
                if risk<=0 or risk/entry<0.005: risk=entry*0.012; sl=entry-risk
                tp1=entry+risk*1.5; tp2=entry+risk*3
                bs=score; best={"sym":sym,"side":"LONG","entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tf":tf,"score":score,"be":False,"amt":0}
        elif last<pl:
            if last<e50: score+=1
            if 22<rv<55: score+=1
            if vs[-1]>vma*1.05: score+=1
            if fvg_bear: score+=1
            if not bull1: score+=2
            if score>=4 and score>bs:
                entry=fvg_mid if fvg_bear and abs(fvg_mid-pl)/pl<0.008 else pl
                sl=max(hs[-10:]); risk=sl-entry
                if risk<=0 or risk/entry<0.005: risk=entry*0.012; sl=entry+risk
                tp1=entry-risk*1.5; tp2=entry-risk*3
                bs=score; best={"sym":sym,"side":"SHORT","entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tf":tf,"score":score,"be":False,"amt":0}
    return best

def calc_lev(entry,sl,b):
    slp=abs(entry-sl)/entry if entry else 0.01
    raw=0.20/slp; lev=max(5,min(int(raw),10))
    pct=0.30 if (TEST_MODE or b<10) else 0.05
    margin=b*pct
    if margin*lev*slp>margin*0.20:
        margin=(margin*0.20)/(lev*slp)
    if margin<0.6: margin=0.6
    if margin>b*0.8: margin=b*0.8
    if b<1: margin=b*0.5
    return lev,margin

def open_trade(tr):
    try:
        b=bal()
        if b<1: send(f"❌ Low ${b:.2f}"); return None
        lev,margin=calc_lev(tr['entry'],tr['sl'],b)
        try: ex.set_leverage(lev,tr['sym'],params={'marginMode':'cross'})
        except: pass
        pr=price(tr['sym'])
        if not pr: return None
        qty_raw=(margin*lev)/pr
        try: qty=float(ex.amount_to_precision(tr['sym'],qty_raw))
        except: qty=qty_raw
        if qty*pr<5.5: qty=5.6/pr
        try: qty=float(ex.amount_to_precision(tr['sym'],qty))
        except: pass
        side='buy' if tr['side']=='LONG' else 'sell'
        ex.create_market_order(tr['sym'],side,qty,params={'positionIdx':0})
        try: ex.set_trading_stop(tr['sym'],0,stopLoss=ex.price_to_precision(tr['sym'],tr['sl']),takeProfit=ex.price_to_precision(tr['sym'],tr['tp2']),params={'positionIdx':0,'tpslMode':'Full'})
        except: pass
        tr['entry']=pr; tr['amt']=qty; tr['lev']=lev; tr['margin']=margin
        return tr
    except Exception as e:
        send(f"❌ OPEN FAIL {tr['sym']} {e}"); return None

def close_trade(sym,pct=100):
    try:
        t=active.get(sym)
        if not t: return False
        side='sell' if t['side']=='LONG' else 'buy'
        amt=float(ex.amount_to_precision(sym,t['amt']*pct/100))
        ex.create_market_order(sym,side,amt,params={'reduceOnly':True,'positionIdx':0})
        return True
    except: return False

def set_be(sym,en):
    try: ex.set_trading_stop(sym,0,stopLoss=ex.price_to_precision(sym,en),params={'positionIdx':0})
    except: pass

def report(title,items):
    if not items: return f"📅 {title}\n💰 ${bal():.2f} No trades"
    pnl=sum([x['pnl'] for x in items])
    det="\n".join([f"{x['sym']} {x['res']} {x['pnl']:+.2f}%" for x in items[-6:]])
    return f"📅 {title}\n💰 ${bal():.2f} {len(items)} PnL {pnl:+.2f}%\n{det}"

try:
    poss=ex.fetch_positions(params={'accountType':'UNIFIED'})
    for p in poss:
        sz=float(p.get('contracts',0) or 0)
        if sz!=0:
            sym=p['symbol']; en=float(p.get('entryPrice',0) or 0)
            if en==0: continue
            sd="LONG" if p.get('side','').lower() in ['long','buy'] else "SHORT"
            if sz<0: sd="SHORT"
            active[sym]={"sym":sym,"side":sd,"entry":en,"sl":en*0.97 if sd=="LONG" else en*1.03,"tp1":en*1.02 if sd=="LONG" else en*0.98,"tp2":en*1.04 if sd=="LONG" else en*0.96,"tf":"REC","score":5,"be":False,"amt":abs(sz),"lev":5,"margin":0}
except: pass

send(f"🧪 TEST $2.70 5MIN AUTO\n💰 ${bal():.2f}\nMax {MAX_TRADES} | Auto every 5min | No force trade\n/pause /play /closeall /status")

last_id=0; last_scan=0; last_chk=0

while True:
    try:
        url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_id+1}&timeout=20"
        r=requests.get(url,timeout=25).json()
        for u in r.get("result",[]):
            last_id=u["update_id"]
            txt=u.get("message",{}).get("text","") or ""
            if not txt: continue
            low=txt.lower().strip()
            if low in ["/start","/help"]:
                send(f"🤖 V4.2 TEST 5MIN\nState {'⏸️ PAUSED' if paused else '▶️ PLAYING'} ${bal():.2f}\nAuto every 5min if A+ setup only\n/scan /trades /bal /pause /play /closeall /status")
            elif low=="/status":
                send(f"📊 STATUS {'⏸️ PAUSED' if paused else '▶️ PLAYING'}\n💰 ${bal():.2f} {len(active)}/{MAX_TRADES}\nAuto 5min ON: {'OFF' if paused else 'ON'} No force")
            elif low=="/pause":
                paused=True; send(f"⏸️ PAUSED ${bal():.2f}")
            elif low in ["/play","/resume","/unpause"]:
                paused=False; send(f"▶️ RESUMED 5MIN AUTO ${bal():.2f}")
            elif low=="/bal":
                send(f"💰 ${bal():.2f} {len(active)}/{MAX_TRADES}")
            elif low=="/trades":
                if not active: send(f"⚪ No active ${bal():.2f}")
                else:
                    m=f"📊 ACTIVE ${bal():.2f}\n"
                    for c,t in active.items():
                        cur=price(c); pn=(cur-t['entry'])/t['entry']*100 if cur else 0
                        if t['side']=="SHORT": pn=-pn
                        m+=f"{c} {t['side']} {t['lev']}x PnL {pn:+.2f}% BE:{t['be']}\n"
                    send(m)
            elif low in ["/stop","/closeall","/close"]:
                if not active: send(f"⚪ No trades ${bal():.2f}")
                else:
                    for c in list(active.keys()): close_trade(c,100); time.sleep(0.4)
                    active.clear(); send(f"✅ CLOSED ALL ${bal():.2f}")
            elif low=="/scan":
                if paused: send(f"⏸️ PAUSED use /play"); continue
                if len(active)>=MAX_TRADES: send(f"⚠️ Full {MAX_TRADES}"); continue
                send(f"🔍 SCAN 7 coins...")
                found=[]
                for coin in WATCHLIST:
                    tr=smc(coin)
                    if tr: found.append(tr)
                found=sorted(found,key=lambda x:x['score'],reverse=True)
                opened=False
                for tr in found:
                    if tr['sym'] in active: continue
                    ot=open_trade(tr)
                    if ot:
                        active[tr['sym']]=ot
                        send(f"🚀 OPENED {tr['sym']} {ot['side']} {ot['lev']}x {fmt(ot['entry'])} REAL ${bal():.2f}")
                        opened=True; break
                if not opened: send("⚪ No A+ setups now - will keep checking every 5min")

        now_ts=time.time(); now_wat=datetime.now(WAT)

        if not paused and now_ts-last_scan>AUTO_SCAN_SEC and len(active)<MAX_TRADES:
            last_scan=now_ts
            found=[]
            for coin in WATCHLIST:
                tr=smc(coin)
                if tr and coin not in active: found.append(tr)
            found=sorted(found,key=lambda x:x['score'],reverse=True)[:MAX_TRADES-len(active)]
            for tr in found:
                ot=open_trade(tr)
                if ot:
                    active[tr['sym']]=ot
                    send(f"🤖 AUTO 5MIN {tr['sym']} {ot['side']} {ot['lev']}x {fmt(ot['entry'])} Score {tr['score']}/6 REAL ${bal():.2f}")

        if now_ts-last_chk>50:
            last_chk=now_ts
            for sym,t in list(active.items()):
                cur=price(sym)
                if not cur: continue
                en=t['entry']; sd=t['side']
                pnl=(cur-en)/en*100 if sd=="LONG" else (en-cur)/en*100
                if not t['be']:
                    if (sd=="LONG" and cur>=t['tp1']) or (sd=="SHORT" and cur<=t['tp1']):
                        close_trade(sym,50); t['amt']*=0.5; t['be']=True; set_be(sym,en)
                        closed.append({"date":now_wat.strftime("%Y-%m-%d"),"dt":now_wat,"sym":sym,"side":sd,"res":"TP1+BE","pnl":pnl*0.5})
                        send(f"🔒 TP1 {sym} {pnl:+.2f}% BE REAL ${bal():.2f}")
                if sd=="LONG":
                    if cur>=t['tp2']:
                        close_trade(sym,100); closed.append({"date":now_wat.strftime("%Y-%m-%d"),"dt":now_wat,"sym":sym,"side":sd,"res":"TP2","pnl":pnl})
                        send(f"🎯 TP2 {sym} {pnl:+.2f}% 🎉 REAL ${bal():.2f}"); del active[sym]
                    elif cur<=t['sl']:
                        if t['be']: close_trade(sym,100); send(f"🔒 BE STOPPED {sym}"); del active[sym]
                        else: close_trade(sym,100); closed.append({"date":now_wat.strftime("%Y-%m-%d"),"dt":now_wat,"sym":sym,"side":sd,"res":"SL","pnl":pnl}); send(f"❌ SL {sym} {pnl:+.2f}%"); del active[sym]
                else:
                    if cur<=t['tp2']:
                        close_trade(sym,100); closed.append({"date":now_wat.strftime("%Y-%m-%d"),"dt":now_wat,"sym":sym,"side":sd,"res":"TP2","pnl":pnl})
                        send(f"🎯 TP2 {sym} {pnl:+.2f}% 🎉 REAL ${bal():.2f}"); del active[sym]
                    elif cur>=t['sl']:
                        if t['be']: close_trade(sym,100); send(f"🔒 BE STOPPED {sym}"); del active[sym]
                        else: close_trade(sym,100); closed.append({"date":now_wat.strftime("%Y-%m-%d"),"dt":now_wat,"sym":sym,"side":sd,"res":"SL","pnl":pnl}); send(f"❌ SL {sym} {pnl:+.2f}%"); del active[sym]
    except Exception as e:
        print(f"loop {e}"); time.sleep(3)
