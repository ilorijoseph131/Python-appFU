from flask import Flask
from threading import Thread
import os, ccxt, requests, time, datetime
app = Flask(__name__)
@app.route('/')
def home(): return "V3.2.13 DEMO 92K LIVE"
def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
Thread(target=run_web, daemon=True).start()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID = os.getenv("CHAT_ID","").strip()
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY","").strip()
BYBIT_SECRET = os.getenv("BYBIT_SECRET","").strip()

# === DEMO FIX - this works with your 92k ===
exchange = ccxt.bybit({
    'apiKey': BYBIT_API_KEY,
    'secret': BYBIT_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'unified'},
    'urls': {
        'api': {
            'public': 'https://api.bybit.com',        # mainnet for candles = fixes no data
            'private': 'https://api-demo.bybit.com',  # demo for trading = uses your 92k
        }
    }
})
# DO NOT use set_sandbox_mode for Demo - only for Testnet
try:
    exchange.load_markets()
    print("load_markets DEMO OK")
except Exception as e:
    print(f"load_markets fail: {e}")

PERCENT_PER_TRADE = 5
MAX_OPEN_TRADES = 4
MIN_SCORE_TO_TRADE = 4
WATCHLIST = ["BTC/USDT:USDT","ETH/USDT:USDT","SOL/USDT:USDT","ZEC/USDT:USDT","DOGE/USDT:USDT","BONK/USDT:USDT","WIF/USDT:USDT","AVAX/USDT:USDT"]
SCAN_TFS = ['15m','30m','1h','2h']
WAT = datetime.timezone(datetime.timedelta(hours=1))

def send(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg[:3800]}, timeout=15)
    except: pass

def get_balance():
    try:
        bal = exchange.fetch_balance(params={'accountType': 'UNIFIED'})
        total = bal['total'].get('USDT',0) or bal['USDT']['total'] or 0
        print(f"balance raw: {total}")
        return float(total)
    except Exception as e:
        print(f"bal error: {e}")
        return 0

def get_ohlcv(s,tf,lim=100):
    try:
        o=exchange.fetch_ohlcv(s,tf,limit=lim)
        if o and len(o)>50: return o
    except: pass
    try:
        sym=s.split("/")[0]+"USDT"
        tf_map={"15m":"15","30m":"30","1h":"60","2h":"120"}
        url=f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}&interval={tf_map.get(tf,'60')}&limit={lim}"
        r=requests.get(url,timeout=10).json()
        if r.get("retCode")==0 and r["result"]["list"]:
            data=list(reversed(r["result"]["list"]))
            return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in data]
    except: pass
    return None

def get_price(s):
    try: return float(exchange.fetch_ticker(s)['last'])
    except:
        try:
            sym=s.split("/")[0]+"USDT"
            url=f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={sym}"
            return float(requests.get(url,timeout=10).json()["result"]["list"][0]["lastPrice"])
        except: return None

def calc_rsi(c,p=14):
    if len(c)<p+1: return 50
    g,l=[],[]
    for i in range(1,len(c)): d=c[i]-c[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag=sum(g[-p:])/p; al=sum(l[-p:])/p
    return 70 if al==0 else 100-(100/(1+ag/al))
def calc_ema(c,p=50):
    if len(c)<p: return c[-1]
    k=2/(p+1); ema=sum(c[:p])/p
    for pr in c[p:]: ema=pr*k+ema*(1-k)
    return ema

def pro_smc(symbol, debug=False):
    o1h=get_ohlcv(symbol,'1h',100)
    if not o1h: return (f"{symbol.split('/')[0]} no data", False, None) if debug else ("", False, None)
    closes1h=[x[4] for x in o1h]; htf_bull=closes1h[-1]>calc_ema(closes1h,50)
    best=None; best_score=-1; dl=[]
    for tf in SCAN_TFS:
        ohlcv=get_ohlcv(symbol,tf,100)
        if not ohlcv or len(ohlcv)<60: continue
        closes=[x[4] for x in ohlcv]; highs=[x[2] for x in ohlcv]; lows=[x[3] for x in ohlcv]
        last=closes[-1]; ema50=calc_ema(closes,50); rsi=calc_rsi(closes,14)
        resistance = max(highs[-30:-5]); support = min(lows[-30:-5])
        score=0; side=None
        if last > resistance*0.998: side="LONG"; 
        elif last < support*1.002: side="SHORT"
        if side:
            if (side=="LONG" and last>ema50) or (side=="SHORT" and last<ema50): score+=1
            if 22<rsi<78: score+=1
            if htf_bull if side=="LONG" else not htf_bull: score+=2
            dl.append(f"{tf}:{score}{side[0]}")
            if score>best_score:
                best_score=score; entry=resistance if side=="LONG" else support
                sl=min(lows[-10:]) if side=="LONG" else max(highs[-10:])
                risk=abs(entry-sl); 
                if risk<entry*0.004: risk=entry*0.012; sl=entry-risk if side=="LONG" else entry+risk
                tp1=entry+risk*1.5 if side=="LONG" else entry-risk*1.5
                tp2=entry+risk*3 if side=="LONG" else entry-risk*3
                best={"symbol":symbol,"side":side,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tf":tf,"score":score,"be_done":False}
    if debug: return (f"{symbol.split('/')[0]} {' | '.join(dl) if dl else 'no BOS'}", False, None)
    if best: return (f"{best['symbol']} {best['side']} {best['score']}/6", True, best)
    return ("", False, None)

def calc_lev(entry, sl):
    dist=abs(entry-sl)/entry
    max_lev=0.2/dist if dist>0 else 5
    return max(5, min(int(max_lev),10)), dist*100

def open_bybit(symbol, side, lev, margin):
    try:
        try: exchange.set_leverage(lev, symbol, params={'marginMode':'cross'})
        except: pass
        price=get_price(symbol)
        amount = (margin * lev) / price
        amount = float(exchange.amount_to_precision(symbol, amount))
        if amount*price < 5: return None,0,0
        order_side='buy' if side=='LONG' else 'sell'
        order=exchange.create_market_order(symbol, order_side, amount, params={'positionIdx':0})
        return order, amount, price
    except Exception as e:
        send(f"❌ OPEN FAIL {symbol}: {e}"); print(e); return None,0,0

def close_bybit(symbol, side, amount, perc=100):
    try:
        close_side='sell' if side=='LONG' else 'buy'
        amt=float(exchange.amount_to_precision(symbol, amount*perc/100))
        exchange.create_market_order(symbol, close_side, amt, params={'reduceOnly':True, 'positionIdx':0})
    except Exception as e: send(f"❌ CLOSE FAIL {symbol}: {e}")

bal = get_balance()
active = {}
if bal>0: send(f"✅ V3.2.13 DEMO LIVE\nBal ${bal:.2f} = your 92k\nSend /test /debug /scan /bal")
else: send("⚠️ Balance 0 - API key not Demo or no Unified permission")

last_id=0; last_check=0
while True:
    try:
        res=requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_id+1}&timeout=20",timeout=25).json()
        for upd in res.get("result",[]):
            last_id=upd["update_id"]
            txt=upd.get("message",{}).get("text","").lower()
            if txt=="/test":
                try:
                    bal=get_balance()
                    if bal==0: send("❌ Bal 0 - key is not Demo"); continue
                    price=get_price("BTC/USDT:USDT")
                    amount=float(exchange.amount_to_precision("BTC/USDT:USDT", (20*5)/price))
                    o=exchange.create_market_order("BTC/USDT:USDT","buy",amount, params={'positionIdx':0})
                    send(f"✅ TEST ORDER OK {o.get('id')} Bal ${bal:.2f}")
                    time.sleep(2)
                    exchange.create_market_order("BTC/USDT:USDT","sell",amount, params={'reduceOnly':True, 'positionIdx':0})
                    send("✅ TEST CLOSE OK - DEMO 92k WORKS!")
                except Exception as e: send(f"❌ TEST FAIL: {e}")
            elif txt in ["/bal","/pnl"]:
                bal=get_balance(); send(f"💰 Demo Bal ${bal:.2f} Active {len(active)}/{MAX_OPEN_TRADES}")
            elif txt=="/debug":
                bal=get_balance(); msg=f"DEBUG Bal ${bal:.2f}\n"
                for coin in WATCHLIST:
                    d,_,_=pro_smc(coin, debug=True); msg+=d+"\n"
                send(msg)
            elif txt=="/scan":
                bal=get_balance()
                if bal==0: send("❌ Balance 0 - use Demo key"); continue
                if len(active)>=MAX_OPEN_TRADES: send(f"⏸️ Max {MAX_OPEN_TRADES}"); continue
                cands=[]
                for coin in WATCHLIST:
                    if coin in active: continue
                    _,ok,tr=pro_smc(coin)
                    if ok and tr['score']>=3:
                        lev,_=calc_lev(tr['entry'],tr['sl']); tr['leverage']=lev; cands.append(tr)
                cands.sort(key=lambda x: x['score'], reverse=True)
                if not cands: send(f"🔍 No setup Bal ${bal:.2f}")
                for tr in cands[:MAX_OPEN_TRADES-len(active)]:
                    bal=get_balance(); margin=bal*0.05
                    o,a,p=open_bybit(tr['symbol'],tr['side'],tr['leverage'],margin)
                    if o:
                        tr['amount']=a; tr['entry']=p; tr['margin']=margin; active[tr['symbol']]=tr
                        send(f"🟢 OPENED {tr['symbol']} {tr['side']} {tr['leverage']}x Score {tr['score']}/6")
        if time.time()-last_check>120:
            last_check=time.time()
            if len(active)<MAX_OPEN_TRADES:
                cands=[]
                for coin in WATCHLIST:
                    if coin in active: continue
                    _,ok,tr=pro_smc(coin)
                    if ok and tr['score']>=4:
                        lev,_=calc_lev(tr['entry'],tr['sl']); tr['leverage']=lev; cands.append(tr)
                cands.sort(key=lambda x: x['score'], reverse=True)
                for tr in cands[:MAX_OPEN_TRADES-len(active)]:
                    bal=get_balance(); margin=bal*0.05
                    o,a,p=open_bybit(tr['symbol'],tr['side'],tr['leverage'],margin)
                    if o:
                        tr['amount']=a; tr['entry']=p; tr['margin']=margin; active[tr['symbol']]=tr
                        send(f"🚨 AUTO {tr['symbol']} {tr['side']}")
            for coin,t in list(active.items()):
                cur=get_price(coin)
                if not cur: continue
                if t['side']=="LONG":
                    if not t['be_done'] and cur>=t['tp1']: close_bybit(coin,t['side'],t['amount'],50); t['be_done']=True; t['amount']*=0.5; send(f"🔒 {coin} TP1")
                    elif cur>=t['tp2']: close_bybit(coin,t['side'],t['amount'],100); send(f"🎯 {coin} TP2"); del active[coin]
                    elif cur<=t['sl']: close_bybit(coin,t['side'],t['amount'],100); send(f"❌ {coin} SL"); del active[coin]
                else:
                    if not t['be_done'] and cur<=t['tp1']: close_bybit(coin,t['side'],t['amount'],50); t['be_done']=True; t['amount']*=0.5; send(f"🔒 {coin} TP1")
                    elif cur<=t['tp2']: close_bybit(coin,t['side'],t['amount'],100); send(f"🎯 {coin} TP2"); del active[coin]
                    elif cur>=t['sl']: close_bybit(coin,t['side'],t['amount'],100); send(f"❌ {coin} SL"); del active[coin]
    except Exception as e:
        print(f"Loop error: {e}"); time.sleep(3)
