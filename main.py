import os, ccxt, requests, time, threading
from flask import Flask

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY")
BYBIT_SECRET = os.getenv("BYBIT_SECRET")

app = Flask(__name__)
@app.route('/')
def home(): return "Bybit Demo Live - Frankfurt EU - OK"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_web, daemon=True).start()
print("Web server started for Render")

# === FIXED FOR demo.bybit.com ===
exchange = ccxt.bybit({
    'apiKey': BYBIT_API_KEY.strip() if BYBIT_API_KEY else '',
    'secret': BYBIT_SECRET.strip() if BYBIT_SECRET else '',
    'enableRateLimit': True,
    'options': {'defaultType': 'unified'},
    'urls': {
        'api': {
            'public': 'https://api-demo.bybit.com',
            'private': 'https://api-demo.bybit.com',
        }
    }
})

try:
    exchange.load_markets()
    print("✅ Markets loaded - Render EU OK - Not blocked")
except Exception as e:
    print(f"❌ Load markets failed: {e}")
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": f"❌ Bybit Demo still blocked: {e}"})

PERCENT_PER_TRADE = 5
MAX_LOSS_PERCENT_OF_MARGIN = 20
MAX_OPEN_TRADES = 3
MAX_LEVERAGE = 10
MIN_LEVERAGE = 5
WATCHLIST = ["BTC/USDT:USDT","ETH/USDT:USDT","SOL/USDT:USDT","DOGE/USDT:USDT","BONK/USDT:USDT","AVAX/USDT:USDT"]
SCAN_TFS = ['15m','30m','1h','2h']

def send(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg[:3800]}, timeout=15)
        print(f"TG: {msg[:60]}")
    except Exception as e:
        print(f"Send fail: {e}")

def fmt(p): return f"{p:.6f}" if p<0.01 else f"{p:.5f}" if p<1 else f"{p:.2f}"

def get_balance():
    try:
        bal = exchange.fetch_balance()
        total = bal['total'].get('USDT',0) or bal['free'].get('USDT',0)
        if not total or total==0:
            raise Exception("0 balance returned")
        return float(total)
    except Exception as e:
        print(f"Balance error (will retry): {e}")
        return 0

def get_ohlcv(s,tf,lim=100):
    try: return exchange.fetch_ohlcv(s,tf,limit=lim)
    except: return None

def get_price(s):
    try: return float(exchange.fetch_ticker(s)['last'])
    except: return None

def calc_rsi(c,p=14):
    if len(c)<p+1: return 50
    g,l=[],[]
    for i in range(1,len(c)):
        d=c[i]-c[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag=sum(g[-p:])/p; al=sum(l[-p:])/p
    return 70 if al==0 else 100-(100/(1+ag/al))

def calc_ema(c,p=50):
    if len(c)<p: return c[-1]
    k=2/(p+1); ema=sum(c[:p])/p
    for pr in c[p:]: ema=pr*k+ema*(1-k)
    return ema

def pro_smc(symbol):
    o1h=get_ohlcv(symbol,'1h',100)
    if not o1h or len(o1h)<60: return "",False,None
    closes1h=[x[4] for x in o1h]; htf_bull=closes1h[-1]>calc_ema(closes1h,50)
    best=None; best_score=0
    for tf in SCAN_TFS:
        ohlcv=get_ohlcv(symbol,tf,100)
        if not ohlcv or len(ohlcv)<60: continue
        closes=[x[4] for x in ohlcv]; highs=[x[2] for x in ohlcv]; lows=[x[3] for x in ohlcv]; vols=[x[5] for x in ohlcv]
        last=closes[-1]; ema50=calc_ema(closes,50); rsi=calc_rsi(closes,14)
        vol_ma=sum(vols[-20:])/20
        ph=max(highs[-30:-5]); pl=min(lows[-30:-5])
        fvg_bull=highs[-3]<lows[-1]; fvg_bear=lows[-3]>highs[-1]
        score=0
        if last>ph:
            if last>ema50: score+=1
            if 50<rsi<75: score+=1
            if vols[-1]>vol_ma*1.1: score+=1
            if fvg_bull: score+=1
            if htf_bull: score+=2
            if score>=4 and score>best_score:
                best_score=score; entry=ph; sl=min(lows[-10:]); risk=entry-sl
                if risk<=0 or risk<entry*0.005: risk=entry*0.015; sl=entry-risk
                tp1=entry+risk*1.5; tp2=entry+risk*3
                best={"symbol":symbol,"side":"LONG","entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tf":tf,"score":score,"be_done":False}
        elif last<pl:
            if last<ema50: score+=1
            if 25<rsi<50: score+=1
            if vols[-1]>vol_ma*1.1: score+=1
            if fvg_bear: score+=1
            if not htf_bull: score+=2
            if score>=4 and score>best_score:
                best_score=score; entry=pl; sl=max(highs[-10:]); risk=sl-entry
                if risk<=0 or risk<entry*0.005: risk=entry*0.015; sl=entry+risk
                tp1=entry-risk*1.5; tp2=entry-risk*3
                best={"symbol":symbol,"side":"SHORT","entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tf":tf,"score":score,"be_done":False}
    return (f"{best['symbol']} {best['side']} {best_score}/6", True, best) if best else ("", False, None)

def calc_lev(entry, sl):
    dist = abs(entry-sl)/entry
    if dist==0: return MIN_LEVERAGE, 1.5
    lev = int((MAX_LOSS_PERCENT_OF_MARGIN/100)/dist)
    lev = max(MIN_LEVERAGE, min(lev, MAX_LEVERAGE))
    return lev, dist*100

def set_lev(symbol, lev):
    try: exchange.set_leverage(lev, symbol)
    except: pass

def open_bybit(symbol, side, lev, margin):
    try:
        set_lev(symbol, lev)
        price=get_price(symbol)
        if not price: return None,0,0
        amount = (margin*lev)/price
        amount = float(exchange.amount_to_precision(symbol, amount))
        order_side='buy' if side=='LONG' else 'sell'
        order=exchange.create_market_order(symbol, order_side, amount)
        return order, amount, price
    except Exception as e:
        send(f"❌ OPEN FAIL {symbol}: {e}"); return None,0,0

def close_bybit(symbol, side, amount, perc=100):
    try:
        close_side='sell' if side=='LONG' else 'buy'
        amt=float(exchange.amount_to_precision(symbol, amount*perc/100))
        exchange.create_market_order(symbol, close_side, amt, params={'reduceOnly':True})
    except Exception as e: send(f"❌ CLOSE FAIL {symbol}: {e}")

active={}
bal = get_balance()
if bal>0:
    send(f"✅ BYBIT DEMO LIVE (Render EU)\nReal Bal ${bal:.2f} | 5% per trade | MaxLoss 20% | {MAX_OPEN_TRADES} max\nSend /scan")
else:
    send(f"⚠️ Connected but balance 0 - check API keys")

last_id=0; last_check=0
print("Bot loop started - waiting for /scan")
while True:
    try:
        res=requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_id+1}&timeout=20",timeout=25).json()
        for upd in res.get("result",[]):
            last_id=upd["update_id"]
            txt=upd.get("message",{}).get("text","").lower()
            if txt=="/scan":
                bal=get_balance()
                if bal==0:
                    send("❌ Balance 0 - API not working, check Bybit Demo keys")
                    continue
                margin=bal*PERCENT_PER_TRADE/100
                if len(active)>=MAX_OPEN_TRADES: send(f"⏸️ Max {MAX_OPEN_TRADES} reached"); continue
                cands=[]
                for coin in WATCHLIST:
                    if coin in active: continue
                    _,ok,tr=pro_smc(coin)
                    if ok and tr['score']>=5:
                        lev,dist=calc_lev(tr['entry'],tr['sl']); tr['leverage']=lev; tr['dist_pct']=dist; cands.append(tr)
                    time.sleep(0.3)
                cands.sort(key=lambda x: x['score'], reverse=True)
                if not cands: send(f"🔍 No 5+ setup found. Bal ${bal:.2f}")
                for tr in cands[:MAX_OPEN_TRADES-len(active)]:
                    bal=get_balance(); margin=bal*PERCENT_PER_TRADE/100
                    o,a,p=open_bybit(tr['symbol'],tr['side'],tr['leverage'],margin)
                    if o:
                        tr['amount']=a; tr['entry']=p; tr['margin']=margin; active[tr['symbol']]=tr
                        send(f"🟢 OPENED {tr['symbol']} {tr['side']} {tr['leverage']}x\nEntry {fmt(p)} SL {fmt(tr['sl'])} Dist {tr['dist_pct']:.2f}%\nMargin ${margin:.2f} MaxLoss ${margin*0.2:.2f}\nScore {tr['score']}/6 TF {tr['tf']}")
            elif txt in ["/bal","/balance","/trades"]:
                bal=get_balance(); msg=f"💰 Bal ${bal:.2f} Active {len(active)}/{MAX_OPEN_TRADES}\n"
                for c,t in active.items():
                    cur=get_price(c)
                    if cur:
                        pnl=(cur-t['entry'])/t['entry']*100*t['leverage'] if t['side']=="LONG" else (t['entry']-cur)/t['entry']*100*t['leverage']
                        msg+=f"{c} {t['side']} {pnl:+.1f}%\n"
                send(msg if active else msg+"No active. Send /scan")
        if time.time()-last_check>120:
            last_check=time.time()
            for coin,t in list(active.items()):
                cur=get_price(coin)
                if not cur: continue
                if t['side']=="LONG":
                    if not t['be_done'] and cur>=t['tp1']: close_bybit(coin,t['side'],t['amount'],50); send(f"🔒 {coin} TP1"); t['be_done']=True; t['amount']*=0.5
                    elif cur>=t['tp2']: close_bybit(coin,t['side'],t['amount'],100); send(f"🎯 {coin} TP2"); del active[coin]
                    elif cur<=t['sl']: close_bybit(coin,t['side'],t['amount'],100); send(f"❌ {coin} SL 20% capped"); del active[coin]
                else:
                    if not t['be_done'] and cur<=t['tp1']: close_bybit(coin,t['side'],t['amount'],50); send(f"🔒 {coin} TP1"); t['be_done']=True; t['amount']*=0.5
                    elif cur<=t['tp2']: close_bybit(coin,t['side'],t['amount'],100); send(f"🎯 {coin} TP2"); del active[coin]
                    elif cur>=t['sl']: close_bybit(coin,t['side'],t['amount'],100); send(f"❌ {coin} SL 20% capped"); del active[coin]
    except Exception as e:
        print(f"Loop error: {e}"); time.sleep(3)
