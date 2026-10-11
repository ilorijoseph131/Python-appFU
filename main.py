from flask import Flask
from threading import Thread
import os, ccxt, requests, time, hmac, hashlib, datetime

app = Flask(__name__)
@app.route('/')
def home(): return "V3.2.9 SR BOS 0.2% BUFFER 4TRADES LIVE"
def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
Thread(target=run_web, daemon=True).start()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID = os.getenv("CHAT_ID","").strip()
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY","").strip()
BYBIT_SECRET = os.getenv("BYBIT_SECRET","").strip()

exchange = ccxt.bybit({
    'apiKey': BYBIT_API_KEY,
    'secret': BYBIT_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'unified'},
})
exchange.set_sandbox_mode(True)
try: exchange.load_markets()
except: pass

PERCENT_PER_TRADE = 5
MAX_LOSS_PERCENT_OF_MARGIN = 20
MAX_OPEN_TRADES = 4
MIN_SCORE_TO_TRADE = 4
MAX_LEVERAGE = 10
MIN_LEVERAGE = 5
WATCHLIST = ["BTC/USDT:USDT","ZEC/USDT:USDT","ETH/USDT:USDT","SOL/USDT:USDT","DOGE/USDT:USDT","BONK/USDT:USDT","WIF/USDT:USDT","AVAX/USDT:USDT"]
SCAN_TFS = ['15m','30m','1h','2h']
WAT = datetime.timezone(datetime.timedelta(hours=1))

def send(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": msg[:3800]}, timeout=15)
    except: pass
def fmt(p): return f"{p:.6f}" if p<0.01 else f"{p:.5f}" if p<1 else f"{p:.2f}"
def get_balance():
    try:
        bal = exchange.fetch_balance(params={'accountType': 'UNIFIED'})
        total = bal['total'].get('USDT',0) or 0
        if total and float(total)>0: return float(total)
    except: pass
    try:
        t = str(int(time.time()*1000)); recv="5000"; params="accountType=UNIFIED&coin=USDT"
        param_str = t + BYBIT_API_KEY + recv + params
        sign = hmac.new(BYBIT_SECRET.encode(), param_str.encode(), hashlib.sha256).hexdigest()
        headers = {"X-BAPI-API-KEY": BYBIT_API_KEY,"X-BAPI-SIGN": sign,"X-BAPI-TIMESTAMP": t,"X-BAPI-RECV-WINDOW": recv}
        r = requests.get(f"https://api-demo.bybit.com/v5/account/wallet-balance?{params}", headers=headers, timeout=10)
        j = r.json()
        if j.get("retCode")==0:
            for c in j["result"]["list"][0]["coin"]:
                if c["coin"]=="USDT": return float(c["walletBalance"])
    except: pass
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
    if not o1h or len(o1h)<60:
        return (f"{symbol.split('/')[0]} no data", False, None) if debug else ("", False, None)
    closes1h=[x[4] for x in o1h]; htf_bull=closes1h[-1]>calc_ema(closes1h,50)
    best=None; best_score=-1; debug_lines=[]
    for tf in SCAN_TFS:
        ohlcv=get_ohlcv(symbol,tf,100)
        if not ohlcv or len(ohlcv)<60: continue
        closes=[x[4] for x in ohlcv]; highs=[x[2] for x in ohlcv]; lows=[x[3] for x in ohlcv]; vols=[x[5] for x in ohlcv]
        last=closes[-1]; ema50=calc_ema(closes,50); rsi=calc_rsi(closes,14)
        vol_ma=sum(vols[-20:])/20 if sum(vols[-20:])>0 else 1
        resistance = max(highs[-30:-5]); support = min(lows[-30:-5])
        fvg_bull=highs[-3]<lows[-1]; fvg_bear=lows[-3]>highs[-1]
        score=0; side=None; sr_label=""
        # 0.2% BUFFER - old signal printed inside box, this catches it
        if last > resistance*0.998:
            side="LONG"; sr_label=f"R {fmt(resistance)}"
            if last>ema50: score+=1
            if 35<rsi<78: score+=1
            if vols[-1]>vol_ma*0.9: score+=1
            if fvg_bull: score+=1
            if htf_bull: score+=2
        elif last < support*1.002:
            side="SHORT"; sr_label=f"S {fmt(support)}"
            if last<ema50: score+=1
            if 22<rsi<65: score+=1
            if vols[-1]>vol_ma*0.9: score+=1
            if fvg_bear: score+=1
            if not htf_bull: score+=2

        if side:
            debug_lines.append(f"{tf}:{score}{side[0]}")
            if score>best_score:
                best_score=score
                entry=resistance if side=="LONG" else support
                if side=="LONG":
                    sl=min(lows[-10:]); risk=entry-sl
                    if risk<=0 or risk<entry*0.004: risk=entry*0.012; sl=entry-risk
                    tp1=entry+risk*1.5; tp2=entry+risk*3
                else:
                    sl=max(highs[-10:]); risk=sl-entry
                    if risk<=0 or risk<entry*0.004: risk=entry*0.012; sl=entry+risk
                    tp1=entry-risk*1.5; tp2=entry-risk*3
                best={"symbol":symbol,"side":side,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tf":tf,"score":score,"be_done":False,"sr_label":f"SR BREAK {sr_label}"}

    if debug:
        return (f"{symbol.split('/')[0]} {' | '.join(debug_lines) if debug_lines else 'no BOS 2d'}", False, None)
    if best:
        return (f"{best['symbol']} {best['side']} {best['score']}/6 {best['sr_label']}", True, best)
    return ("", False, None)

def calc_leverage_for_20pct_sl(entry, sl):
    dist_pct = abs(entry - sl) / entry
    if dist_pct==0: return MIN_LEVERAGE, 0
    max_lev = (MAX_LOSS_PERCENT_OF_MARGIN/100) / dist_pct
    return max(MIN_LEVERAGE, min(int(max_lev), MAX_LEVERAGE)), dist_pct*100
def set_lev(symbol, lev):
    try: exchange.set_leverage(lev, symbol)
    except: pass
def open_bybit(symbol, side, lev, margin):
    try:
        set_lev(symbol, lev); price=get_price(symbol)
        if not price: return None,0,0
        amount = (margin * lev) / price
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

bal = get_balance()
day_start_balance = bal if bal>0 else 50000
last_daily_report_date = None
active = {}
if bal>0:
    send(f"✅ V3.2.9 LIVE - SR BOS 0.2% + FALLBACK\nBal ${bal:.2f} | 5%=${bal*0.05:.2f} MaxLoss ${bal*0.05*0.2:.2f}\nMax {MAX_OPEN_TRADES} | 4/6 primary, 3/6 fallback after 2 days stuck\nWatch ZEC,BTC,ETH,SOL,DOGE,BONK,WIF,AVAX\nSend /debug /scan")
else: send("⚠️ Balance 0 - /scan will retry")

last_id=0; last_check=0
while True:
    try:
        now_wat = datetime.datetime.now(WAT)
        if now_wat.hour==0 and now_wat.minute<5:
            today = now_wat.date()
            if last_daily_report_date!= today:
                cur_bal = get_balance(); floating=0
                for t in active.values():
                    cur=get_price(t['symbol'])
                    if cur:
                        pnl = (cur-t['entry'])/t['entry']*t['margin']*t['leverage'] if t['side']=="LONG" else (t['entry']-cur)/t['entry']*t['margin']*t['leverage']
                        floating+=pnl
                daily = cur_bal - day_start_balance + floating
                pct = (daily/day_start_balance*100) if day_start_balance>0 else 0
                send(f"📊 DAILY PnL {today} 00:00 WAT\nStart ${day_start_balance:.2f} -> Now ${cur_bal:.2f}\nFloat ${floating:+.2f}\nNet {daily:+.2f} ({pct:+.2f}%) Open {len(active)}/{MAX_OPEN_TRADES}")
                day_start_balance = cur_bal; last_daily_report_date = today

        res=requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_id+1}&timeout=20",timeout=25).json()
        for upd in res.get("result",[]):
            last_id=upd["update_id"]
            txt=upd.get("message",{}).get("text","").lower()
            if txt=="/scan":
                bal=get_balance()
                if bal==0: send("❌ Balance 0"); continue
                if len(active)>=MAX_OPEN_TRADES: send(f"⏸️ Max {MAX_OPEN_TRADES} Bal ${bal:.2f}"); continue
                cands=[]
                for coin in WATCHLIST:
                    if coin in active: continue
                    _,ok,tr=pro_smc(coin)
                    if ok and tr['score']>=MIN_SCORE_TO_TRADE:
                        lev,dist=calc_leverage_for_20pct_sl(tr['entry'],tr['sl']); tr['leverage']=lev; tr['dist_pct']=dist; cands.append(tr)
                    time.sleep(0.2)
                # FALLBACK if no 4+ for 2 days - take best 3+
                if not cands:
                    for coin in WATCHLIST:
                        if coin in active: continue
                        _,ok,tr=pro_smc(coin)
                        if ok and tr['score']>=3:
                            lev,dist=calc_leverage_for_20pct_sl(tr['entry'],tr['sl']); tr['leverage']=lev; tr['dist_pct']=dist; cands.append(tr)
                        time.sleep(0.1
