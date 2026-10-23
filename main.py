from flask import Flask
from threading import Thread
app = Flask(__name__)
@app.route('/')
def home(): return "V3.2.18 MERGED AUTO PNL $3 LIVE"
def run_flask(): app.run(host='0.0.0.0', port=10000)
Thread(target=run_flask, daemon=True).start()

import os, ccxt, requests, time
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY","").strip()
BYBIT_SECRET = os.getenv("BYBIT_SECRET","").strip()

PERCENT_PER_TRADE = 33
MAX_OPEN_TRADES = 1
MIN_LEV = 5
MAX_LEV = 6

exchange = ccxt.bybit({
    'apiKey': BYBIT_API_KEY,
    'secret': BYBIT_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'unified'},
})
try:
    exchange.load_markets()
    print(f"LIVE KEY {BYBIT_API_KEY[:6]}... markets OK {len(exchange.markets)}")
except Exception as e:
    print(f"load err {e}")

WATCHLIST_RAW = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "DOGE/USDT", "BONK/USDT", "WIF/USDT", "ZEC/USDT", "AVAX/USDT", "DOT/USDT", "ONDO/USDT", "PAXG/USDT"]
WATCHLIST = [s.replace("/USDT","/USDT:USDT") for s in WATCHLIST_RAW]
WAT = timezone(timedelta(hours=1))
SCAN_TFS = ['15m', '30m', '1h', '2h']
CONFIRM_TF = '1h'

closed_trades = []
def add_closed_trade(symbol, side, tf, entry, sl, tp1, tp2, result, pnl_pct, entry_reason):
    now = datetime.now(WAT)
    closed_trades.append({"date": now.strftime("%Y-%m-%d"),"time": now.strftime("%H:%M"),"week": now.strftime("%Y-W%W"),"month": now.strftime("%Y-%m"),"symbol": symbol, "side": side, "tf": tf,"entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2,"result": result, "pnl": pnl_pct, "reason": entry_reason})
    if len(closed_trades)>500: closed_trades.pop(0)

def send(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg[:4000], "parse_mode": "Markdown"}, timeout=15)
    except: pass

def fmt_price(p):
    if p is None: return "N/A"
    if p < 0.0001: return f"${p:.8f}"
    elif p < 0.01: return f"${p:.6f}"
    elif p < 1: return f"${p:.5f}"
    elif p < 100: return f"${p:.4f}"
    else: return f"${p:.2f}"

def get_ohlcv_raw(symbol, timeframe='1h', limit=100):
    try: return exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    except:
        try: return exchange.fetch_ohlcv(symbol, timeframe.lower(), limit=limit)
        except: return None

def get_price(symbol):
    try: return float(exchange.fetch_ticker(symbol)['last'])
    except:
        ohlcv = get_ohlcv_raw(symbol, '1h', 5)
        return float(ohlcv[-1][4]) if ohlcv else None

def get_balance():
    try:
        bal = exchange.fetch_balance(params={'accountType': 'UNIFIED'})
        return float(bal['total'].get('USDT',0) or 0)
    except: return 0

def calc_rsi_list(closes, period=14):
    if len(closes) < period+1: return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    avg_gain = sum(gains[-period:])/period
    avg_loss = sum(losses[-period:])/period
    if avg_loss == 0: return 70.0
    return 100 - (100/(1+avg_gain/avg_loss))

def calc_ema_list(closes, period=50):
    if len(closes) < period: return closes[-1]
    k = 2/(period+1)
    ema = sum(closes[:period])/period
    for price in closes[period:]: ema = price*k + ema*(1-k)
    return ema

def select_best_entry(side, last, bos_level, fvg_exists, fvg_mid, ema50):
    def pct_diff(a,b): return abs(a-b)/b*100 if b else 999
    if fvg_exists and pct_diff(fvg_mid, bos_level) < 0.8: return fvg_mid, "FVG 50% + BOS Confluence 🔥"
    if pct_diff(ema50, bos_level) < 1.0: return ema50, "EMA50 + BOS Confluence 🔥"
    if fvg_exists: return fvg_mid, "FVG 50% (Imbalance Fill)"
    return bos_level, "BOS Retest / Major S/R"

def pro_smc_analysis(symbol):
    ohlcv_1h = get_ohlcv_raw(symbol, '1h', 100)
    if not ohlcv_1h or len(ohlcv_1h) < 60: return f"{symbol}: No 1H data", False, None
    closes_1h = [c[4] for c in ohlcv_1h]
    ema50_1h = calc_ema_list(closes_1h, 50)
    htf_bull = closes_1h[-1] > ema50_1h
    htf_trend = "BULLISH 🟢" if htf_bull else "BEARISH 🔴"
    best_score = 0; best_msg = ""; best_trade = None
    for tf in SCAN_TFS:
        ohlcv = get_ohlcv_raw(symbol, tf, 100)
        if not ohlcv or len(ohlcv) < 60: continue
        closes = [c[4] for c in ohlcv]; highs = [c[2] for c in ohlcv]; lows = [c[3] for c in ohlcv]; vols = [c[5] for c in ohlcv]
        last = closes[-1]; ema50 = calc_ema_list(closes, 50); rsi = calc_rsi_list(closes, 14)
        vol_ma = sum(vols[-20:])/20 if len(vols)>=20 else vols[-1]
        ph = max(highs[-30:-5]); pl = min(lows[-30:-5])
        fvg_bull = highs[-3] < lows[-1]; fvg_bear = lows[-3] > highs[-1]
        fvg_mid_bull = (highs[-3] + lows[-1])/2 if fvg_bull else last
        fvg_mid_bear = (lows[-3] + highs[-1])/2 if fvg_bear else last
        score = 0; reasons = []
        if last > ph:
            if last > ema50: score+=1; reasons.append("Above 50EMA")
            if 50 < rsi < 75: score+=1; reasons.append(f"RSI {rsi:.1f}")
            if vols[-1] > vol_ma*1.1: score+=1; reasons.append("Vol OK")
            if fvg_bull: score+=1; reasons.append("FVG")
            if htf_bull: score+=2; reasons.append("1H Bullish ✅")
            if score >=4 and score > best_score:
                best_score = score
                best_entry, entry_reason = select_best_entry("LONG", last, ph, fvg_bull, fvg_mid_bull, ema50)
                sl = min(lows[-10:]); risk = best_entry - sl
                if risk <=0 or risk < best_entry*0.005: risk=best_entry*0.015; sl=best_entry-risk
                tp1=best_entry+risk*1.5; tp2=best_entry+risk*3
                sl_pct = (sl - best_entry) / best_entry * 100
                tp1_pct = (tp1 - best_entry) / best_entry * 100
                tp2_pct = (tp2 - best_entry) / best_entry * 100
                rr = abs(tp1 - best_entry) / abs(best_entry - sl) if best_entry!= sl else 0
                best_trade = {"symbol": symbol, "side": "LONG", "entry": best_entry, "sl": sl, "tp1": tp1, "tp2": tp2, "risk": risk, "tf": tf, "entry_reason": entry_reason, "be_done": False, "score": score}
                best_msg = f"*{symbol} - A+ LONG [{tf}]* 🟢\nQuality: {score}/6 HIGH\nPrice: {fmt_price(last)}\nTrend: 1H {htf_trend} | {tf} Above EMA50 | RSI {rsi:.1f}\nSetup: {', '.join(reasons)}\n\n🎯 ENTRY: {fmt_price(best_entry)}\n📍 {entry_reason}\nSL: {fmt_price(sl)} ({sl_pct:+.1f}%)\nTP1: {fmt_price(tp1)} ({tp1_pct:+.1f}%) - Take 50%\nTP2: {fmt_price(tp2)} ({tp2_pct:+.1f}%) - Take rest\nRR: 1:{rr:.1f}\nTrailing ON"
        elif last < pl:
            if last < ema50: score+=1; reasons.append("Below 50EMA")
            if 25 < rsi < 50: score+=1; reasons.append(f"RSI {rsi:.1f}")
            if vols[-1] > vol_ma*1.1: score+=1; reasons.append("Vol OK")
            if fvg_bear: score+=1; reasons.append("FVG")
            if not htf_bull: score+=2; reasons.append("1H Bearish ✅")
            if score >=4 and score > best_score:
                best_score = score
                best_entry, entry_reason = select_best_entry("SHORT", last, pl, fvg_bear, fvg_mid_bear, ema50)
                sl = max(highs[-10:]); risk = sl - best_entry
                if risk <=0 or risk < best_entry*0.005: risk=best_entry*0.015; sl=best_entry+risk
                tp1=best_entry-risk*1.5; tp2=best_entry-risk*3
                sl_pct = (sl - best_entry) / best_entry * 100
                tp1_pct = (tp1 - best_entry) / best_entry * 100
                tp2_pct = (tp2 - best_entry) / best_entry * 100
                rr = abs(tp1 - best_entry) / abs(best_entry - sl) if best_entry!= sl else 0
                best_trade = {"symbol": symbol, "side": "SHORT", "entry": best_entry, "sl": sl, "tp1": tp1, "tp2": tp2, "risk": risk, "tf": tf, "entry_reason": entry_reason, "be_done": False, "score": score}
                best_msg = f"*{symbol} - A+ SHORT [{tf}]* 🔴\nQuality: {score}/6 HIGH\nPrice: {fmt_price(last)}\nTrend: 1H {htf_trend} | {tf} Below EMA50 | RSI {rsi:.1f}\nSetup: {', '.join(reasons)}\n\n🎯 ENTRY: {fmt_price(best_entry)}\n📍 {entry_reason}\nSL: {fmt_price(sl)} ({sl_pct:+.1f}%)\nTP1: {fmt_price(tp1)} ({tp1_pct:+.1f}%) - Take 50%\nTP2: {fmt_price(tp2)} ({tp2_pct:+.1f}%) - Take rest\nRR: 1:{rr:.1f}\nTrailing ON"
    if best_msg: return best_msg, True, best_trade
    else: return f"*{symbol}* - Ranging ⚪ | 1H: {htf_trend}", False, None

def calc_lev(entry, sl):
    dist = abs(entry-sl)/entry if entry else 0.01
    max_lev = 0.2/dist if dist>0 else 5
    return max(MIN_LEV, min(int(max_lev), MAX_LEV))

def open_bybit(symbol, side, lev, margin):
    try:
        try: exchange.set_leverage(lev, symbol, params={'marginMode':'cross'})
        except: pass
        price=get_price(symbol)
        if not price: return None,0,0
        amount=(margin*lev)/price
        amount=float(exchange.amount_to_precision(symbol, amount))
        if amount*price < 5:
            amount=float(exchange.amount_to_precision(symbol, 5.1/price))
        order_side='buy' if side=='LONG' else 'sell'
        order=exchange.create_market_order(symbol, order_side, amount, params={'positionIdx':0})
        return order, amount, price
    except Exception as e:
        send(f"❌ OPEN FAIL {symbol}: {e}"); return None,0,0

def close_bybit(symbol, side, amount, perc=100):
    try:
        close_side='sell' if side=='LONG' else 'buy'
        amt=float(exchange.amount_to_precision(symbol, amount*perc/100))
        exchange.create_market_order(symbol, close_side, amt, params={'reduceOnly':True, 'positionIdx':0})
    except Exception as e:
        send(f"❌ CLOSE FAIL {symbol}: {e}")

def get_report(filter_type="today"):
    now = datetime.now(WAT)
    if filter_type == "today": trades = [t for t in closed_trades if t['date'] == now.strftime("%Y-%m-%d")]; title = f"📅 TODAY {now.strftime('%Y-%m-%d')}"
    elif filter_type == "week": trades = [t for t in closed_trades if t['week'] == now.strftime("%Y-W%W")]; title = f"📆 THIS WEEK {now.strftime('%Y-W%W')}"
    elif filter_type == "month": trades = [t for t in closed_trades if t['month'] == now.strftime("%Y-%m")]; title = f"📆 THIS MONTH {now.strftime('%Y-%m')}"
    else: trades = [t for t in closed_trades if t['date'] >= (now - timedelta(days=7)).strftime("%Y-%m-%d")]; title = f"📆 LAST 7 DAYS"
    if not trades: return f"{title}\n\nNo closed trades yet"
    wins = len([t for t in trades if t['pnl']>0]); losses = len([t for t in trades if t['pnl']<0])
    winrate = wins/len(trades)*100 if trades else 0
    tp2 = len([t for t in trades if t['result']=='TP2']); be = len([t for t in trades if t['result'] in ['TP1+BE','BE']]); flipped = len([t for t in trades if t['result']=='FLIPPED'])
    msg = f"{title}\n\nTotal: {len(trades)} | Wins: {wins} (TP2:{tp2} BE:{be}) | Loss: {losses} (FLIPPED:{flipped})\nWin Rate: {winrate:.1f}%\n\n"
    for t in trades[-15:]:
        e = "✅" if t['pnl']>0 else "❌"
        msg+=f"{e} {t['symbol']} {t['side']} {t['result']} {t['pnl']:+.1f}% {t['date']} {t['time']}\n"
    msg+=f"\nTotal PnL: {sum([t['pnl'] for t in trades]):+.1f}%"
    return msg

active_trades = {}
last_flip_time = {}
last_daily_sent = ""
last_weekly_sent = ""
last_monthly_sent = ""

HELP_TEXT = """*V3.2.18 AUTO PNL $3 LIVE* 🚀
/scan - Scan FVG+Vol+BOS
/trades - Active
/today - Today PnL (auto resets 23:55 WAT)
/week - Week PnL (auto Sunday 23:00)
/month - Month PnL (auto last day 23:55)
/bal - Balance
/test - Test $1×5=$5
/price BTC
/coin AVAX
/status
/stop
AUTO: Daily 23:55, Weekly Sun 23:00, Monthly last day 23:55
$3 Mode: 33%=$1×5x Max 1 trade
"""

send(f"✅ V3.2.18 AUTO PNL LIVE 🔥\nSMC FVG+Vol kept\nBal ${get_balance():.2f} $3 Mode $1×5x\nAuto: Daily 23:55 Weekly Sun 23:00 Monthly last day\n/scan /today /week /month")

last_id=0; last_trade_alert={}; last_auto_check=0

def handle_new_signal(coin, is_high, trade):
    if not is_high or not trade: return False, None
    if coin in active_trades:
        old = active_trades[coin]
        if old['side'] == trade['side']:
            return False, f"{coin} already {old['side']}"
        else:
            cur_price = get_price(coin) or old['entry']
            pnl = (cur_price - old['entry'])/old['entry']*100 if old['side']=="LONG" else (old['entry'] - cur_price)/old['entry']*100
            if pnl > -0.8: return False, f"🛡️ {coin} FLIP BLOCKED: {pnl:+.2f}% need -0.8%"
            if trade.get('score',4) < 5: return False, f"🛡️ {coin} FLIP BLOCKED: {trade.get('score')}/6 need 5/6+"
            if time.time() - last_flip_time.get(coin,0) < 5400:
                remain = int((5400 - (time.time() - last_flip_time.get(coin,0)))/60)
                return False, f"🛡️ {coin} FLIP BLOCKED: cooldown {remain}m"
            add_closed_trade(coin, old['side'], old['tf'], old['entry'], old['sl'], old['tp1'], old['tp2'], "FLIPPED", pnl, old['entry_reason'])
            send(f"🔄 FLIP {coin}: {old['side']} -> {trade['side']}\nPnL {pnl:+.2f}%\nNew: {trade['side']} {trade['tf']} {trade.get('score')}/6 🔥")
            try:
                if 'amount' in old: close_bybit(coin, old['side'], old['amount'], 100)
            except: pass
            del active_trades[coin]
            last_flip_time[coin] = time.time()
    return True, None

while True:
    try:
        now_wat = datetime.now(WAT)
        today_str = now_wat.strftime("%Y-%m-%d")
        week_str = now_wat.strftime("%Y-W%W")
        month_str = now_wat.strftime("%Y-%m")

        if now_wat.hour == 23 and now_wat.minute >= 55:
            if last_daily_sent != today_str:
                daily = get_report("today")
                daily += f"\n\n💰 Bal: ${get_balance():.2f}\nNew day starts 00:00 → PnL resets to 0%"
                send(daily)
                last_daily_sent = today_str

        if now_wat.weekday() == 6 and now_wat.hour == 23:
            if last_weekly_sent != week_str:
                weekly = get_report("week")
                weekly += f"\n\n💰 Bal: ${get_balance():.2f}\nNew week starts → PnL resets"
                send(weekly)
                last_weekly_sent = week_str

        tomorrow = now_wat + timedelta(days=1)
        is_last_day = tomorrow.month != now_wat.month
        if is_last_day and now_wat.hour == 23 and now_wat.minute >= 55:
            if last_monthly_sent != month_str:
                monthly = get_report("month")
                monthly += f"\n\n💰 Bal: ${get_balance():.2f}\nNew month starts → PnL resets"
                send(monthly)
                last_monthly_sent = month_str

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_id+1}&timeout=20"
        res = requests.get(url, timeout=25).json()
        for upd in res.get("result", []):
            last_id = upd["update_id"]
            txt = upd.get("message", {}).get("text","")
            if not txt: continue
            low = txt.lower().strip(); parts = txt.strip().split()
            if low in ["/start","/help"]: send(HELP_TEXT)
            elif low=="/bal":
                b=get_balance(); mt=b*PERCENT_PER_TRADE/100
                send(f"💰 Bal ${b:.2f}\nMargin ${mt:.2f} ×{MIN_LEV}-{MAX_LEV}x\nActive {len(active_trades)}/{MAX_OPEN_TRADES}\nToday PnL: {sum([t['pnl'] for t in closed_trades if t['date']==today_str]):+.2f}%")
            elif low=="/test":
                try:
                    b=get_balance()
                    if b<1: send(f"❌ Need $1 Bal ${b:.2f}"); continue
                    price=get_price("BTC/USDT:USDT")
                    margin_for_test = max(1.0, b*0.33)
                    lev_test=5
                    amount=float(exchange.amount_to_precision("BTC/USDT:USDT", (margin_for_test*lev_test)/price))
                    if amount*price<5: amount=float(exchange.amount_to_precision("BTC/USDT:USDT", 5.1/price))
                    o=exchange.create_market_order("BTC/USDT:USDT","buy",amount, params={'positionIdx':0})
                    send(f"✅ $3 TEST OK Bal ${b:.2f} Margin ${margin_for_test:.2f}×{lev_test} = ${amount*price:.2f}")
                    time.sleep(2)
                    exchange.create_market_order("BTC/USDT:USDT","sell",amount, params={'reduceOnly':True,'positionIdx':0})
                    send("✅ CLOSE OK - $3 LIVE WORKS /scan")
                except Exception as e: send(f"❌ TEST FAIL {e}")
            elif low=="/scan":
                send("🔍 SCAN 12 coins FVG+Vol+BOS Multi-TF...")
                full=""; hq=[]; blocked=[]
                for coin in WATCHLIST:
                    analysis, is_high, trade = pro_smc_analysis(coin)
                    full+=f"\n\n{analysis}\n---"
                    if is_high and trade:
                        allowed, skip_msg = handle_new_signal(coin, is_high, trade)
                        if allowed:
                            b=get_balance()
                            if b<1: continue
                            if len(active_trades)>=MAX_OPEN_TRADES: blocked.append(f"{coin} Max {MAX_OPEN_TRADES}"); continue
                            lev=calc_lev(trade['entry'], trade['sl'])
                            margin=max(1.0, b*PERCENT_PER_TRADE/100)
                            o,a,p=open_bybit(coin, trade['side'], lev, margin)
                            if o:
                                trade['amount']=a; trade['entry']=p; trade['margin']=margin; trade['leverage']=lev
                                active_trades[coin]=trade; last_trade_alert[coin]=time.time()
                                hq.append(f"{coin}({trade['tf']})")
                                send(f"🟢 $3 OPENED {coin} {trade['side']} {lev}x\n{trade['entry_reason']}\nMargin ${margin:.2f} Entry {fmt_price(p)}")
                            else: blocked.append(f"{coin} open fail")
                        elif skip_msg: blocked.append(skip_msg)
                    time.sleep(0.4)
                send(full + (f"\n\n🔥 OPENED: {', '.join(hq)}" if hq else "\n\n⚪ No new A+ 4/6+") + (f"\n\n🛡️ Blocked: {'; '.join(blocked[:3])}" if blocked else ""))
            elif low=="/trades":
                if not active_trades: send("No active trades - /scan")
                else:
                    msg="📊 ACTIVE + PnL\n"
                    for c,t in active_trades.items():
                        cur=get_price(c); pnl_str=""
                        if cur:
                            pnl=(cur-t['entry'])/t['entry']*100
                            if t['side']=="SHORT": pnl=-pnl
                            pnl_str=f" PnL {pnl:+.1f}% Now {fmt_price(cur)}"
                        msg+=f"\n{c} {t['side']} [{t['tf']}] {fmt_price(t['entry'])}{pnl_str} {'🔒 BE' if t['be_done'] else ''} Lev {t.get('leverage',5)}x M ${t.get('margin',0):.2f}\n"
                    send(msg)
            elif low in ["/today","/daily","/pnl","/pnl_today"]: send(get_report("today"))
            elif low in ["/week","/weekly","/pnl_week"]: send(get_report("week"))
            elif low in ["/month","/monthly","/pnl_month"]: send(get_report("month"))
            elif low=="/status": send(f"🤖 V3.2.18 AUTO PNL\nActive: {len(active_trades)}/{MAX_OPEN_TRADES}\nClosed: {len(closed_trades)}\nBal: ${get_balance():.2f}\nToday: {sum([t['pnl'] for t in closed_trades if t['date']==today_str]):+.2f}%\nWeek: {sum([t['pnl'] for t in closed_trades if t['week']==week_str]):+.2f}%\nMonth: {sum([t['pnl'] for t in closed_trades if t['month']==month_str]):+.2f}%")
            elif low=="/tf": send(f"Scan: {', '.join(SCAN_TFS)} | Conf: {CONFIRM_TF}")
            elif low=="/stop":
                for c,t in list(active_trades.items()):
                    try:
                        if 'amount' in t: close_bybit(c, t['side'], t['amount'], 100)
                    except: pass
                active_trades.clear(); send("🛑 Cleared + closed")
            elif low.startswith("/price"):
                if len(parts)<2: send("Use: /price BTC")
                else:
                    
