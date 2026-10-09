import os, ccxt, requests, time, threading, hmac, hashlib, datetime
from flask import Flask

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY")
BYBIT_SECRET = os.getenv("BYBIT_SECRET")

app = Flask(__name__)
@app.route('/')
def home(): return "Bybit Demo Live - ZEC 5/6 + Daily PnL - OK"
def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
threading.Thread(target=run_web, daemon=True).start()

exchange = ccxt.bybit({
    'apiKey': BYBIT_API_KEY.strip() if BYBIT_API_KEY else '',
    'secret': BYBIT_SECRET.strip() if BYBIT_SECRET else '',
    'enableRateLimit': True,
    'options': {'defaultType': 'unified'},
})
exchange.set_sandbox_mode(True)
try: exchange.load_markets()
except Exception as e: print(f"Load markets fail: {e}")

PERCENT_PER_TRADE = 5
MAX_LOSS_PERCENT_OF_MARGIN = 20
MAX_OPEN_TRADES = 3
MAX_LEVERAGE = 10
MIN_LEVERAGE = 5
WATCHLIST = ["BTC/USDT:USDT","ZEC/USDT:USDT","SOL/USDT:USDT","DOGE/USDT:USDT","BONK/USDT:USDT","AVAX/USDT:USDT"]
SCAN_TFS = ['15m','30m','1h','2h']

def send(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg[:3800]}, timeout=15)
    except: pass
def fmt(p): return f"{p:.6f}" if p<0.01 else f"{p:.5f}" if p<1 else f"{p:.2f}"

def get_balance():
    try:
        bal = exchange.fetch_balance(params={'accountType': 'UNIFIED'})
        total = bal['total'].get('USDT',0) or 0
        if total and float(total)>0: return float(total)
    except: pass
    try:
        t = str(int(time.time()*1000)); recv = "5000"; params = "accountType=UNIFIED&coin=USDT"
        param_str = t + BYBIT_API_KEY.strip() + recv + params
        sign = hmac.new(BYBIT_SECRET.strip().encode(), param_str.encode(), hashlib.sha256).hexdigest()
        headers = {"X-BAPI-API-KEY": BYBIT_API_KEY.strip(),"X-BAPI-SIGN": sign,"X-BAPI-TIMESTAMP": t,"X-BAPI-RECV-WINDOW": recv}
        r = requests.get(f"https://api-demo.bybit.com/v5/account/wallet-balance?{params}", headers=headers, timeout=10)
        j = r.json()
        if j.get("retCode")==0:
            for c in j["result"]["list"][0]["coin"]:
                if c["coin"]=="USDT": return float(c["walletBalance"])
    except Exception as e: print(f"Balance fail {e}")
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
        vol_ma=sum(vols[-20:])/20; ph=max(highs[-30:-5]); pl=min(lows[-30:-5])
        fvg_bull=highs[-3]<lows[-1]; fvg_bear=lows[-3]>highs[-1]; score=0
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
    return max(MIN_LEVERAGE, min(lev, MAX_LEVERAGE)), dist*100
def set_lev(s,l):
    try: exchange.set_leverage(l,s)
    except: pass
def open_bybit(symbol, side, lev, margin):
    try:
        set_lev(symbol, lev); price=get_price(symbol)
        if not price: return None,0,0
        amount = (margin*lev)/price
        amount = float(exchange.amount_to_precision(symbol, amount))
        order_side='buy' if side=='LONG' else 'sell'
        order=exchange.create_market_order(symbol, order_side, amount)
        return order, amount, price
    except Exception as e: send(f"❌ OPEN FAIL {symbol}: {e}"); return None,0,0
def close_bybit(symbol, side, amount, perc=100):
    try:
        close_side='sell' if side=='LONG' else 'buy'
        amt=float(exchange.amount_to_precision(symbol, amount*perc/100))
        exchange.create_market_order(symbol, close_side, amt, params={'reduceOnly':True})
    except Exception as e: send(f"❌ CLOSE FAIL {symbol}: {e}")

active={}
bal = get_balance()
# Daily tracking
WAT = datetime.timezone(datetime.timedelta(hours=1)) # Katsina WAT
day_start_balance = bal if bal>0 else 50000
day_start_date = datetime.datetime.now(WAT).date()
last_daily_report_date = None
daily_pnl_trades_closed = [] # list of realized

if bal>0:
    send(f"✅ LIVE ZEC 5/6 + Daily PnL 00:00 WAT\nBal ${bal:.2f} | Daily report at midnight Katsina\nSend /scan | /bal")
else:
    send(f"⚠️ Balance 0 - will retry on /scan")

last_id=0; last_check=0
while True:
    try:
        # === DAILY 00:00 WAT REPORT ===
        now_wat = datetime.datetime.now(WAT)
        if now_wat.hour==0 and now_wat.minute<5: # within 00:00-00:04
            today = now_wat.date()
            if last_daily_report_date!= today:
                cur_bal = get_balance()
                # Calculate floating PnL of open trades
                floating = 0
                open_msg = ""
                for coin,t in active.items():
                    cur=get_price(coin)
                    if cur:
                        pnl_val = (cur-t['entry'])/t['entry']*t['margin']*t['leverage'] if t['side']=="LONG" else (t['entry']-cur)/t['entry']*t['margin']*t['leverage']
                        floating+=pnl_val
                        open_msg+=f"\n{coin} {t['side']} ${pnl_val:+.2f}"
                daily_change = cur_bal - day_start_balance + floating
                pct = (daily_change/day_start_balance*100) if day_start_balance>0 else 0
                send(f"📊 DAILY PnL {today} 00:00 WAT\nStart ${day_start_balance:.2f} → Now ${cur_bal:.2f}\nFloating ${floating:+.2f}\nNet Daily {daily_change:+.2f} ({pct:+.2f}%)\nOpen: {len(active)}/{MAX_OPEN_TRADES}{open_msg}\n\nNew day started.")
                day_start_balance = cur_bal
                day_start_date = today
                last_daily_report_date = today
                daily_pnl_trades_closed = []

        res=requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_id+1}&timeout=20",timeout=25).json()
        for upd in res.get("result",[]):
            last_id=upd["update_id"]
            txt=upd.get("message",{}).get("text","").lower()
            if txt=="/scan":
                bal=get_balance()
                if bal==0: send("❌ Balance 0 - check Logs"); continue
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
            elif txt in ["/bal","/balance","/trades","/pnl"]:
                bal=get_balance()
                floating=0; msg=f"💰 Bal ${bal:.2f} Active {len(active)}/{MAX_OPEN_TRADES}\nDay Start ${day_start_balance:.2f}\n"
                for c,t in active.items():
                    cur=get_price(c)
                    if cur:
                        pnl_pct=(cur-t['entry'])/t['entry']*100*t['leverage'] if t['side']=="LONG" else (t['entry']-cur)/t['entry']*100*t['leverage']
                        pnl_val = t['margin']*pnl_pct/100
                        floating+=pnl_val
                        msg+=f"{c} {t['side']} {pnl_pct:+.1f}% (${pnl_val:+.2f})\n"
                daily = bal - day_start_balance + floating
                msg+=f"Float ${floating:+.2f} | Daily Net ${daily:+.2f}\nWatch: ZEC,BTC,SOL,DOGE,BONK,AVAX"
                send(msg if active else msg+f"\nNo active. Send /scan")

        if time.time()-last_check>120:
            last_check=time.time()
            for coin,t in list(active.items()):
                cur=get_price(coin)
                if not cur: continue
                if t['side']=="LONG":
                    if not t['be_done'] and cur>=t['tp1']: close_bybit(coin,t['side'],t['amount'],50); send(f"🔒 {coin} TP1 +50%"); t['be_done']=True; t['amount']*=0.5
                    elif cur>=t['tp2']: close_bybit(coin,t['side'],t['amount'],100); send(f"🎯 {coin} TP2 closed"); del active[coin]
                    elif cur<=t['sl']: close_bybit(coin,t['side'],t['amount'],100); send(f"❌ {coin} SL 20% capped"); del active[coin]
                else:
                    if not t['be_done'] and cur<=t['tp1']: close_bybit(coin,t['side'],t['amount'],50); send(f"🔒 {coin} TP1 +50%"); t['be_done']=True; t['amount']*=0.5
                    elif cur<=t['tp2']: close_bybit(coin,t['side'],t['amount'],100); send(f"🎯 {coin} TP2 closed"); del active[coin]
                    elif cur>=t['sl']: close_bybit(coin,t['side'],t['amount'],100); send(f"❌ {coin} SL 20% capped"); del active[coin]
    except Exception as e:
        print(f"Loop error: {e}"); time.sleep(3)
