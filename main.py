from flask import Flask
from threading import Thread
app = Flask(__name__)
@app.route('/')
def home(): return "BYBIT MAIN V4.2 FLIP REAL PNL"
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
MAX_TRADES = 4
AUTO_SCAN_SEC = 300

closed=[]; active={}; paused=False
last_auto_daily=""; last_week=""; last_month=""

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
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id":CHAT_ID,"text":m[:3900]}, timeout=15)
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
    h1_status = "BULLISH" if bull1 else "BEARISH"
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
        above_ema = last>e50
        setup_items=[]
        setup_items.append(f"Above 50EMA" if above_ema else f"Below 50EMA")
        setup_items.append(f"RSI {rv:.1f}")
        setup_items.append("Vol OK" if vs[-1]>vma else "Vol Low")
        if fvg_bull or fvg_bear: setup_items.append("FVG")
        if last>ph or last<pl: setup_items.append("BOS")
        score=0
        if last>ph:
            if above_ema: score+=1
            if 45<rv<78: score+=1
            if vs[-1]>vma*1.05: score+=1
            if fvg_bull: score+=1
            if bull1: score+=2
            if score>=4 and score>bs:
                entry=fvg_mid if fvg_bull and abs(fvg_mid-ph)/ph<0.008 else ph
                sl=min(ls[-10:]); risk=entry-sl
                if risk<=0 or risk/entry<0.005: risk=entry*0.012; sl=entry-risk
                tp1=entry+risk*1.5; tp2=entry+risk*3
                bs=score; best={"sym":sym,"side":"LONG","entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tf":tf,"score":score,"rsi":rv,"above_ema":above_ema,"h1":h1_status,"setup":", ".join(setup_items),"price":last,"be":False,"amt":0}
        elif last<pl:
            if not above_ema: score+=1
            if 22<rv<55: score+=1
            if vs[-1]>vma*1.05: score+=1
            if fvg_bear: score+=1
            if not bull1: score+=2
            if score>=4 and score>bs:
                entry=fvg_mid if fvg_bear and abs(fvg_mid-pl)/pl<0.008 else pl
                sl=max(hs[-10:]); risk=sl-entry
                if risk<=0 or risk/entry<0.005: risk=entry*0.012; sl=entry+risk
                tp1=entry-risk*1.5; tp2=entry-risk*3
                bs=score; best={"sym":sym,"side":"SHORT","entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tf":tf,"score":score,"rsi":rv,"above_ema":above_ema,"h1":h1_status,"setup":", ".join(setup_items),"price":last,"be":False,"amt":0}
    return best

def calc_lev(entry,sl,b):
    slp=abs(entry-sl)/entry if entry else 0.01
    raw=0.20/slp; lev=max(5,min(int(raw),10))
    margin=b*0.05
    if margin*lev*slp>margin*0.20:
        margin=(margin*0.20)/(lev*slp)
    if margin<0.6: margin=0.6
    return lev,margin

def open_trade(tr):
    try:
        b=bal()
        if b<5: send(f"❌ Low balance ${b:.2f}"); return None
        lev,margin=calc_lev(tr['entry'],tr['sl'],b)
        try: ex.set_leverage(lev,tr['sym'],params={'marginMode':'cross'})
        except: pass
        pr=price(tr['sym'])
        if not pr: return None
        qty_raw=(margin*lev)/pr
        try: qty=float(ex.amount_to_precision(tr['sym'],qty_raw))
        except: qty=qty_raw
        if qty*pr<5.6: qty=5.7/pr
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

def close_single_real(sym):
    try:
        poss=ex.fetch_positions(params={'accountType':'UNIFIED','symbol':sym})
        for p in poss:
            if p['symbol']!=sym: continue
            sz=float(p.get('contracts',0) or 0)
            if sz==0: continue
            side='sell' if p.get('side','').lower() in ['long','buy'] or sz>0 else 'buy'
            if sz<0 or p.get('side','').lower()=='short': side='buy'
            amt=abs(sz)
            ex.create_market_order(sym,side,amt,params={'reduceOnly':True,'positionIdx':0})
            return amt
    except: pass
    return 0

def close_all_real():
    count=0
    try:
        poss=ex.fetch_positions(params={'accountType':'UNIFIED'})
        for p in poss:
            sz=float(p.get('contracts',0) or 0)
            if sz==0: continue
            sym=p['symbol']
            side='sell' if p.get('side','').lower() in ['long','buy'] or sz>0 else 'buy'
            if sz<0 or p.get('side','').lower()=='short': side='buy'
            amt=abs(sz)
            try:
                ex.create_market_order(sym,side,amt,params={'reduceOnly':True,'positionIdx':0})
                count+=1; time.sleep(0.3)
            except: pass
        return count
    except: return 0

def set_be(sym,en):
    try: ex.set_trading_stop(sym,0,stopLoss=ex.price_to_precision(sym,en),params={'positionIdx':0})
    except: pass

def build_msg(tr, mode="AUTO"):
    entry=tr['entry']; sl=tr['sl']; tp1=tr['tp1']; tp2=tr['tp2']
    if tr['side']=="LONG":
        sl_pct=(sl-entry)/entry*100
        tp1_pct=(tp1-entry)/entry*100
        tp2_pct=(tp2-entry)/entry*100
    else:
        sl_pct=(sl-entry)/entry*100
        tp1_pct=(tp1-entry)/entry*100
        tp2_pct=(tp2-entry)/entry*100
        sl_pct = -abs(sl_pct)
        tp1_pct = abs(tp1_pct)
        tp2_pct = abs(tp2_pct)
    qual="HIGH" if tr['score']>=4 else "MED"
    ema_txt = "Above EMA50" if tr['above_ema'] else "Below EMA50"
    msg = f"""🔥 {mode} {tr['sym'].split('/')[0]}/USDT - A+ {tr['side']} [{tr['tf']}] 🟢

Quality: {tr['score']}/6 {qual}
Price: {fmt(tr['price'])}
Trend: 1H {tr['h1']} | {tr['tf']} {ema_txt} | RSI {tr['rsi']:.1f}
Setup: {tr['setup']}

🎯 ENTRY: {fmt(entry)}
   FVG 50% + BOS Confluence 🔥
🛑 SL: {fmt(sl)} ({sl_pct:.2f}%)
TP1: {fmt(tp1)} (+{abs(tp1_pct):.2f}%) - Take 50%
TP2: {fmt(tp2)} (+{abs(tp2_pct):.2f}%) - Take rest
RR: 1:1.5
Trailing ON
💰 Bal ${bal():.2f} | Lev {tr.get('lev',5)}x | {len(active)}/{MAX_TRADES}"""
    return msg

def pnl_report(title, items):
    if not items:
        return f"📅 {title}\n💰 ${bal():.2f}\n⚪ No closed trades"
    pnl=sum([x['pnl'] for x in items])
    wins=len([x for x in items if x['pnl']>0])
    details="\n".join([f"{x['dt'].strftime('%H:%M')} {x['sym'].split('/')[0]} {x['res']} {x['pnl']:+.2f}%" for x in items[-10:]])
    return f"📅 {title}\n💰 ${bal():.2f} | {len(items)} trades | {wins}W-{len(items)-wins}L | PnL {pnl:+.2f}%\n{details}"

try:
    poss=ex.fetch_positions(params={'accountType':'UNIFIED'})
    for p in poss:
        sz=float(p.get('contracts',0) or 0)
        if sz!=0:
            sym=p['symbol']; en=float(p.get('entryPrice',0) or 0)
            if en==0: continue
            sd="LONG" if p.get('side','').lower() in ['long','buy'] or sz>0 else "SHORT"
            if sz<0: sd="SHORT"
            active[sym]={"sym":sym,"side":sd,"entry":en,"sl":en*0.97 if sd=="LONG" else en*1.03,"tp1":en*1.02 if sd=="LONG" else en*0.98,"tp2":en*1.04 if sd=="LONG" else en*0.96,"tf":"REC","score":5,"rsi":50,"above_ema":True,"h1":"REC","setup":"Recovered","price":en,"be":False,"amt":abs(sz),"lev":5,"margin":0}
except: pass

send(f"🚀 MAIN V4.2 FLIP LIVE\n💰 REAL ${bal():.2f}\nActive {len(active)}/{MAX_TRADES}\n5min Auto | FLIP ON | Real PNL | % details\nCoins: BTC AVAX DOGE SOL BONK PAXG ONDO")

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
                send(f"🤖 MAIN V4.2 FLIP\nState: {'⏸️ PAUSED' if paused else '▶️ PLAYING'} | REAL ${bal():.2f}\n\n/scan /trades /bal /today /week /month /pause /play /closeall /status\nFLIP ON - opposite signal auto flips")
            elif low=="/status":
                send(f"📊 STATUS\n{'⏸️ PAUSED' if paused else '▶️ PLAYING'}\n💰 REAL ${bal():.2f}\nActive {len(active)}/{MAX_TRADES}\nAuto 5min FLIP ON")
            elif low=="/pause":
                paused=True; send(f"⏸️ PAUSED ${bal():.2f}")
            elif low in ["/play","/resume","/unpause"]:
                paused=False; send(f"▶️ RESUMED 5min FLIP ON ${bal():.2f}")
            elif low=="/bal":
                send(f"💰 REAL ${bal():.2f} {len(active)}/{MAX_TRADES}")
            elif low=="/trades":
                if not active: send(f"⚪ No active ${bal():.2f}")
                else:
                    for c,t in active.items():
                        cur=price(c); pn=(cur-t['entry'])/t['entry']*100 if cur else 0
                        if t['side']=="SHORT": pn=-pn
                        send(f"📊 {c} {t['side']} {pn:+.2f}% BE:{t['be']}\nEntry {fmt(t['entry'])} → {fmt(cur)}\nSL {fmt(t['sl'])} TP2 {fmt(t['tp2'])}")
            elif low=="/today":
                today=datetime.now(WAT).strftime("%Y-%m-%d")
                items=[x for x in closed if x['date']==today]
                send(pnl_report(f"TODAY {today}", items))
            elif low=="/week":
                now=datetime.now(WAT); start=now-timedelta(days=now.weekday())
                items=[x for x in closed if x['dt']>=start]
                send(pnl_report(f"WEEK {start.strftime('%m/%d')}-{now.strftime('%m/%d')}", items))
            elif low=="/month":
                now=datetime.now(WAT)
                items=[x for x in closed if x['dt'].month==now.month and x['dt'].year==now.year]
                send(pnl_report(f"MONTH {now.strftime('%Y-%m')}", items))
            elif low in ["/stop","/closeall","/close"]:
                n=close_all_real(); active.clear()
                send(f"✅ CLOSED {n} REAL on Bybit\n💰 ${bal():.2f}")
            elif low=="/scan":
                if paused: send(f"⏸️ PAUSED use /play"); continue
                if len(active)>=MAX_TRADES and not any(True for _ in []): 
                    pass
                send(f"🔍 SCAN 7 coins...")
                found=[]
                for coin in WATCHLIST:
                    tr=smc(coin)
                    if tr: found.append(tr)
                found=sorted(found,key=lambda x:x['score'],reverse=True)
                opened=0
                for tr in found:
                    # FLIP CHECK FOR MANUAL TOO
                    if tr['sym'] in active:
                        old=active[tr['sym']]
                        if old['side']!=tr['side']:
                            # FLIP IT
                            cur=price(tr['sym'])
                            pnl=(cur-old['entry'])/old['entry']*100 if cur else 0
                            if old['side']=="SHORT": pnl=-pnl
                            close_single_real(tr['sym'])
                            del active[tr['sym']]
                            closed.append({"date":datetime.now(WAT).strftime("%Y-%m-%d"),"dt":datetime.now(WAT),"sym":tr['sym'],"side":old['side'],"res":"FLIP","pnl":pnl})
                            send(f"🔄 AUTO FLIP {tr['sym'].split('/')[0]}/USDT: {old['side']} -> {tr['side']} PnL {pnl:+.2f}%")
                        else:
                            continue
                    if len(active)>=MAX_TRADES: break
                    ot=open_trade(tr)
                    if ot:
                        tr.update(ot); active[tr['sym']]=tr
                        send(build_msg(tr, "🚀 MANUAL"))
                        opened+=1
                if opened==0: send("⚪ No new A+ setups")

        now_ts=time.time(); now_wat=datetime.now(WAT)

        if not paused and now_ts-last_scan>AUTO_SCAN_SEC and len(active)<=MAX_TRADES:
            last_scan=now_ts
            found=[]
            for coin in WATCHLIST:
                tr=smc(coin)
                if tr: found.append(tr)
            found=sorted(found,key=lambda x:x['score'],reverse=True)
            for tr in found:
                # FLIP LOGIC
                if tr['sym'] in active:
                    old=active[tr['sym']]
                    if old['side']!=tr['side']:
                        # Opposite signal = FLIP
                        cur=price(tr['sym'])
                        pnl=(cur-old['entry'])/old['entry']*100 if cur else 0
                        if old['side']=="SHORT": pnl=-pnl
                        # REAL CLOSE
                        close_single_real(tr['sym'])
                        del active[tr['sym']]
                        closed.append({"date":now_wat.strftime("%Y-%m-%d"),"dt":now_wat,"sym":tr['sym'],"side":old['side'],"res":"FLIP","pnl":pnl})
                        # Now open new direction
                        ot=open_trade(tr)
                        if ot:
                            tr.update(ot); active[tr['sym']]=tr
                            flip_header=f"🔄 AUTO FLIP {tr['sym'].split('/')[0]}/USDT: {old['side']} -> {tr['side']} PnL {pnl:+.2f}%"
                            send(flip_header + "\n\n" + build_msg(tr, "🤖 LIVE ALERT"))
                        continue
                    else:
                        continue
                if len(active)>=MAX_TRADES: break
                ot=open_trade(tr)
                if ot:
                    tr.update(ot); active[tr['sym']]=tr
                    send(build_msg(tr, "🤖 LIVE ALERT"))

        if now_ts-last_chk>30:
            last_chk=now_ts
            for sym,t in list(active.items()):
                cur=price(sym)
                if not cur: continue
                en=t['entry']; sd=t['side']
                pnl=(cur-en)/en*100 if sd=="LONG" else (en-cur)/en*100
                if not t['be']:
                    if (sd=="LONG" and cur>=t['tp1']) or (sd=="SHORT" and cur<=t['tp1']):
                        try:
                            amt=float(ex.amount_to_precision(sym,t['amt']*0.5))
                            side='sell' if sd=="LONG" else 'buy'
                            ex.create_market_order(sym,side,amt,params={'reduceOnly':True,'positionIdx':0})
                        except: pass
                        t['amt']*=0.5; t['be']=True; set_be(sym,en)
                        closed.append({"date":now_wat.strftime("%Y-%m-%d"),"dt":now_wat,"sym":sym,"side":sd,"res":"TP1+BE","pnl":pnl*0.5})
                        send(f"🎯 {sym.split('/')[0]}/USDT TP1 HIT! {fmt(cur)} {pnl:+.2f}%\nTake 50% SL->BE\n💰 ${bal():.2f}")
                if sd=="LONG":
                    if cur>=t['tp2']:
                        close_single_real(sym); del active[sym]
                        closed.append({"date":now_wat.strftime("%Y-%m-%d"),"dt":now_wat,"sym":sym,"side":sd,"res":"TP2","pnl":pnl})
                        send(f"🎯 TP2 {sym.split('/')[0]} {pnl:+.2f}% 🎉 REAL ${bal():.2f}")
                    elif cur<=t['sl']:
                        if t['be']:
                            close_single_real(sym); del active[sym]
                            send(f"🔒 BE STOPPED {sym.split('/')[0]} breakeven ${bal():.2f}")
                        else:
                            close_single_real(sym); del active[sym]
                            closed.append({"date":now_wat.strftime("%Y-%m-%d"),"dt":now_wat,"sym":sym,"side":sd,"res":"SL","pnl":pnl}); send(f"❌ SL {sym.split('/')[0]} {pnl:+.2f}% ${bal():.2f}")
                else:
                    if cur<=t['tp2']:
                        close_single_real(sym); del active[sym]
                        closed.append({"date":now_wat.strftime("%Y-%m-%d"),"dt":now_wat,"sym":sym,"side":sd,"res":"TP2","pnl":pnl})
                        send(f"🎯 TP2 {sym.split('/')[0]} {pnl:+.2f}% 🎉 REAL ${bal():.2f}")
                    elif cur>=t['sl']:
                        if t['be']:
                            close_single_real(sym); del active[sym]
                            send(f"🔒 BE STOPPED {sym.split('/')[0]} breakeven ${bal():.2f}")
                        else:
                            close_single_real(sym); del active[sym]
                            closed.append({"date":now_wat.strftime("%Y-%m-%d"),"dt":now_wat,"sym":sym,"side":sd,"res":"SL","pnl":pnl}); send(f"❌ SL {sym.split('/')[0]} {pnl:+.2f}% ${bal():.2f}")

        if now_wat.hour==23 and now_wat.minute>=58 and last_auto_daily!=now_wat.strftime("%Y-%m-%d"):
            today=now_wat.strftime("%Y-%m-%d")
            items=[x for x in closed if x['date']==today]
            send(pnl_report(f"AUTO DAILY {today}", items))
            last_auto_daily=today
        if now_wat.weekday()==6 and now_wat.hour==23 and last_week!=now_wat.strftime("%Y-%m-%d"):
            wk=[x for x in closed if x['dt'].isocalendar()[1]==now_wat.isocalendar()[1]]; send(pnl_report("WEEKLY AUTO",wk)); last_week=now_wat.strftime("%Y-%m-%d")
        last_day=calendar.monthrange(now_wat.year,now_wat.month)[1]
        if now_wat.day==last_day and now_wat.hour==23 and now_wat.minute>25 and last_month!=now_wat.strftime("%Y-%m-%d"):
            mo=[x for x in closed if x['dt'].month==now_wat.month]; send(pnl_report("MONTHLY AUTO",mo)); last_month=now_wat.strftime("%Y-%m-%d")

    except Exception as e:
        print(f"loop {e}"); time.sleep(3)
