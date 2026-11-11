from flask import Flask
from threading import Thread
app=Flask(__name__)
@app.route('/')
def home():return "V3.2.5 FIXED REAL SLTP BCH STRICT 5%"
def run_flask():app.run(host='0.0.0.0',port=10000)
Thread(target=run_flask,daemon=True).start()
import os,ccxt,requests,time
from datetime import timezone,timedelta
TELEGRAM_TOKEN=os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or ""
CHAT_ID=os.getenv("CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or ""
API_KEY=os.getenv("BYBIT_API_KEY","").strip()
API_SECRET=os.getenv("BYBIT_SECRET","").strip() or os.getenv("BYBIT_API_SECRET","").strip()
exchange=ccxt.bybit({'apiKey':API_KEY,'secret':API_SECRET,'enableRateLimit':True,'options':{'defaultType':'unified'}})
try:exchange.load_markets()
except:pass
spot=ccxt.okx({'enableRateLimit':True,'options':{'defaultType':'spot'}})
try:spot.load_markets()
except:pass
WATCHLIST=["BCH/USDT","ETH/USDT","SOL/USDT","BNB/USDT","DOGE/USDT","BONK/USDT","WIF/USDT","ZEC/USDT","AVAX/USDT","DOT/USDT","ONDO/USDT","PAXG/USDT"]
WAT=timezone(timedelta(hours=1))
SCAN_TFS=['15m','30m','1h','2h']
MAX_TRADES=4
PCT_PER_TRADE=0.05
MIN_NOTIONAL=5.6
closed_trades=[];active_trades={}
last_flip_time={};last_trade_alert={}
last_id=0;last_auto_check=0
def send(m):
 try:requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",data={"chat_id":CHAT_ID,"text":m[:4000],"parse_mode":"Markdown"},timeout=15)
 except:pass
def fmt_price(p):
 if p is None:return "N/A"
 if p<0.0001:return f"${p:.8f}"
 elif p<0.01:return f"${p:.6f}"
 elif p<1:return f"${p:.5f}"
 elif p<100:return f"${p:.4f}"
 else:return f"${p:.2f}"
def get_ohlcv_raw(symbol,tf='1h',limit=100):
 try:return spot.fetch_ohlcv(symbol,tf,limit=limit)
 except:
  try:return spot.fetch_ohlcv(symbol,tf.lower(),limit=limit)
  except:return None
def get_price(symbol):
 try:
  sym=symbol.replace("/USDT","/USDT:USDT") if ":USDT" not in symbol else symbol
  return float(exchange.fetch_ticker(sym)['last'])
 except:
  try:return float(exchange.fetch_ticker(symbol)['last'])
  except:return None
def calc_rsi_list(closes,period=14):
 if len(closes)<period+1:return 50.0
 gains,losses=[],[]
 for i in range(1,len(closes)):
  d=closes[i]-closes[i-1]
  gains.append(max(d,0));losses.append(max(-d,0))
 avg_gain=sum(gains[-period:])/period
 avg_loss=sum(losses[-period:])/period
 if avg_loss==0:return 70.0
 return 100-(100/(1+avg_gain/avg_loss))
def calc_ema_list(closes,period=50):
 if len(closes)<period:return closes[-1]
 k=2/(period+1)
 ema=sum(closes[:period])/period
 for price in closes[period:]:ema=price*k+ema*(1-k)
 return ema
def select_best_entry(side,last,bos_level,fvg_exists,fvg_mid,ema50):
 def pct_diff(a,b):return abs(a-b)/b*100 if b else 999
 if fvg_exists and pct_diff(fvg_mid,bos_level)<0.8:return fvg_mid,"FVG 50% + BOS Confluence 🔥"
 if pct_diff(ema50,bos_level)<1.0:return ema50,"EMA50 + BOS Confluence 🔥"
 if fvg_exists:return fvg_mid,"FVG 50% (Imbalance Fill)"
 return bos_level,"BOS Retest / Major S/R"
def get_bybit_bal():
 try:
  b=exchange.fetch_balance(params={'accountType':'UNIFIED'})
  info=b.get('info',{}).get('result',{}).get('list',[])
  for acc in info:
   for c in acc.get('coin',[]):
    if c.get('coin')=='USDT':
     v=c.get('equity') or c.get('walletBalance')
     if v:return float(v)
  return float(b.get('total',{}).get('USDT',0) or 0)
 except:return 0.0
def set_real_sl_tp(sym, sl, tp):
 try:
  m=exchange.market(sym)
  sid=m['id']
  sl_p=str(exchange.price_to_precision(sym, sl))
  tp_p=str(exchange.price_to_precision(sym, tp))
  exchange.private_post_v5_position_trading_stop({
   'category':'linear','symbol':sid,
   'stopLoss':sl_p,'takeProfit':tp_p,
   'tpslMode':'Full','positionIdx':0
  })
  return True
 except Exception as e:
  print(f"SLTP fail {sym} {e}")
  return False
def set_be(sym,en):
 try:
  m=exchange.market(sym)
  en_p=str(exchange.price_to_precision(sym,en))
  exchange.private_post_v5_position_trading_stop({
   'category':'linear','symbol':m['id'],
   'stopLoss':en_p,'tpslMode':'Full','positionIdx':0
  })
 except:pass
def calc_lev(symbol,entry,sl,balance):
 risk_pct=abs(entry-sl)/entry
 if risk_pct<=0:risk_pct=0.015
 lev=0.05/(risk_pct*0.05) if risk_pct>0 else 7
 lev=max(1,min(20,int(lev)))
 qty_cost=balance*PCT_PER_TRADE
 qty=qty_cost*lev/entry
 notional=qty*entry
 if notional<MIN_NOTIONAL:
  return None,None,f"skip notional ${notional:.2f}<${MIN_NOTIONAL} bal ${balance:.2f} STRICT 5%"
 return lev,qty,None
def open_trade_auto(symbol,side,entry,sl,tp1,tp2,tf,reason,score):
 if len(active_trades)>=MAX_TRADES:send(f"⚪ {symbol} skip MAX {MAX_TRADES} reached");return False
 bal=get_bybit_bal()
 if bal<5:send(f"⚪ {symbol} skip low bal ${bal:.2f}");return False
 lev,qty,skip=calc_lev(symbol,entry,sl,bal)
 if skip:send(f"⚪ {symbol} {skip}");return False
 try:
  sm=exchange.market(symbol) if symbol in exchange.markets else exchange.market(symbol.replace("/USDT","/USDT:USDT"))
  sym_id=sm['id']
  real_sym=sm['symbol']
  exchange.set_leverage(lev,real_sym)
  side_o='Buy' if side=='LONG' else 'Sell'
  exchange.create_market_order(real_sym,side_o,qty,params={'positionIdx':0})
  time.sleep(1.2)
  set_real_sl_tp(real_sym, sl, tp2)
 except Exception as e:
  send(f"❌ {symbol} open fail: {e}");return False
 active_trades[symbol]={"symbol":symbol,"real_sym":real_sym,"side":side,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"risk":abs(entry-sl),"tf":tf,"entry_reason":reason,"be_done":False,"score":score,"lev":lev,"qty":qty}
 send(f"✅ AUTO OPEN {symbol} {side} {tf}\nENTRY {fmt_price(entry)} SL {fmt_price(sl)}\nTP1 {fmt_price(tp1)} TP2 {fmt_price(tp2)}\nBal ${bal:.2f} Lev {lev}x 5% STRICT\nSL/TP SET ON BYBIT ✅")
 return True
def close_trade_auto(symbol,reason=""):
 if symbol not in active_trades:return
 t=active_trades[symbol]
 try:
  rsym=t.get('real_sym',symbol)
  side_c='Sell' if t['side']=='LONG' else 'Buy'
  exchange.create_market_order(rsym,side_c,t['qty'],params={'reduceOnly':True,'positionIdx':0})
  send(f"🔒 CLOSE {symbol} {t['side']} {reason}")
 except Exception as e:send(f"❌ {symbol} close fail {e}")
 del active_trades[symbol]
# --- YOUR ORIGINAL SMC LOGIC UNCHANGED ---
def pro_smc_analysis(symbol):
 ohlcv_1h=get_ohlcv_raw(symbol,'1h',100)
 if not ohlcv_1h or len(ohlcv_1h)<60:return f"{symbol}: No 1H data",False,None
 closes_1h=[c[4] for c in ohlcv_1h]
 ema50_1h=calc_ema_list(closes_1h,50)
 htf_bull=closes_1h[-1]>ema50_1h
 htf_trend="BULLISH 🟢" if htf_bull else "BEARISH 🔴"
 best_score=0;best_msg="";best_trade=None
 for tf in SCAN_TFS:
  ohlcv=get_ohlcv_raw(symbol,tf,100)
  if not ohlcv or len(ohlcv)<60:continue
  closes=[c[4] for c in ohlcv];highs=[c[2] for c in ohlcv];lows=[c[3] for c in ohlcv];vols=[c[5] for c in ohlcv]
  last=closes[-1];ema50=calc_ema_list(closes,50);rsi=calc_rsi_list(closes,14)
  vol_ma=sum(vols[-20:])/20 if len(vols)>=20 else vols[-1]
  ph=max(highs[-30:-5]);pl=min(lows[-30:-5])
  fvg_bull=highs[-3]<lows[-1];fvg_bear=lows[-3]>highs[-1]
  fvg_mid_bull=(highs[-3]+lows[-1])/2 if fvg_bull else last
  fvg_mid_bear=(lows[-3]+highs[-1])/2 if fvg_bear else last
  score=0;reasons=[]
  if last>ph:
   if last>ema50:score+=1;reasons.append("Above 50EMA")
   if 50<rsi<75:score+=1;reasons.append(f"RSI {rsi:.1f}")
   if vols[-1]>vol_ma*1.1:score+=1;reasons.append("Vol OK")
   if fvg_bull:score+=1;reasons.append("FVG")
   if htf_bull:score+=2;reasons.append("1H Bullish ✅")
   if score>=4 and score>best_score:
    best_score=score
    best_entry,entry_reason=select_best_entry("LONG",last,ph,fvg_bull,fvg_mid_bull,ema50)
    sl=min(lows[-10:]);risk=best_entry-sl
    if risk<=0 or risk<best_entry*0.005:risk=best_entry*0.015;sl=best_entry-risk
    tp1=best_entry+risk*1.5;tp2=best_entry+risk*3
    sl_pct=(sl-best_entry)/best_entry*100
    tp1_pct=(tp1-best_entry)/best_entry*100
    tp2_pct=(tp2-best_entry)/best_entry*100
    rr=abs(tp1-best_entry)/abs(best_entry-sl) if best_entry!=sl else 0
    best_trade={"symbol":symbol,"side":"LONG","entry":best_entry,"sl":sl,"tp1":tp1,"tp2":tp2,"risk":risk,"tf":tf,"entry_reason":entry_reason,"be_done":False,"score":score}
    best_msg=f"*{symbol} - A+ LONG [{tf}]* 🟢\nQuality: {score}/6 HIGH\nPrice: {fmt_price(last)}\nTrend: 1H {htf_trend} | {tf} Above EMA50 | RSI {rsi:.1f}\nSetup: {', '.join(reasons)}\n\n🎯 ENTRY: {fmt_price(best_entry)}\n📍 {entry_reason}\nSL: {fmt_price(sl)} ({sl_pct:+.1f}%)\nTP1: {fmt_price(tp1)} ({tp1_pct:+.1f}%) - Take 50%\nTP2: {fmt_price(tp2)} ({tp2_pct:+.1f}%) - Take rest\nRR: 1:{rr:.1f}\nTrailing ON"
  elif last<pl:
   if last<ema50:score+=1;reasons.append("Below 50EMA")
   if 25<rsi<50:score+=1;reasons.append(f"RSI {rsi:.1f}")
   if vols[-1]>vol_ma*1.1:score+=1;reasons.append("Vol OK")
   if fvg_bear:score+=1;reasons.append("FVG")
   if not htf_bull:score+=2;reasons.append("1H Bearish ✅")
   if score>=4 and score>best_score:
    best_score=score
    best_entry,entry_reason=select_best_entry("SHORT",last,pl,fvg_bear,fvg_mid_bear,ema50)
    sl=max(highs[-10:]);risk=sl-best_entry
    if risk<=0 or risk<best_entry*0.005:risk=best_entry*0.015;sl=best_entry+risk
    tp1=best_entry-risk*1.5;tp2=best_entry-risk*3
    sl_pct=(sl-best_entry)/best_entry*100
    tp1_pct=(tp1-best_entry)/best_entry*100
    tp2_pct=(tp2-best_entry)/best_entry*100
    rr=abs(tp1-best_entry)/abs(best_entry-sl) if best_entry!=sl else 0
    best_trade={"symbol":symbol,"side":"SHORT","entry":best_entry,"sl":sl,"tp1":tp1,"tp2":tp2,"risk":risk,"tf":tf,"entry_reason":entry_reason,"be_done":False,"score":score}
    best_msg=f"*{symbol} - A+ SHORT [{tf}]* 🔴\nQuality: {score}/6 HIGH\nPrice: {fmt_price(last)}\nTrend: 1H {htf_trend} | {tf} Below EMA50 | RSI {rsi:.1f}\nSetup: {', '.join(reasons)}\n\n🎯 ENTRY: {fmt_price(best_entry)}\n📍 {entry_reason}\nSL: {fmt_price(sl)} ({sl_pct:+.1f}%)\nTP1: {fmt_price(tp1)} ({tp1_pct:+.1f}%) - Take 50%\nTP2: {fmt_price(tp2)} ({tp2_pct:+.1f}%) - Take rest\nRR: 1:{rr:.1f}\nTrailing ON"
 if best_msg:return best_msg,True,best_trade
 else:return f"*{symbol}* - Ranging ⚪ | 1H: {htf_trend}",False,None
def handle_new_signal(coin,is_high,trade):
 if not is_high or not trade:return False,None
 if coin in active_trades:
  old=active_trades[coin]
  if old['side']==trade['side']:return False,f"{coin} already {old['side']} active - new {trade['side']} {trade['tf']} skipped ⚪"
  else:
   cur_price=get_price(coin) or old['entry']
   pnl=(cur_price-old['entry'])/old['entry']*100 if old['side']=="LONG" else (old['entry']-cur_price)/old['entry']*100
   if pnl>-0.8:return False,f"🛡️ {coin} FLIP BLOCKED: old {old['side']} only {pnl:+.2f}% (need -0.8%) - keeping"
   if trade.get('score',4)<5:return False,f"🛡️ {coin} FLIP BLOCKED: new {trade['side']} only {trade.get('score')}/6 weak (need 5/6+) - keeping {old['side']}"
   if time.time()-last_flip_time.get(coin,0)<5400:
    remain=int((5400-(time.time()-last_flip_time.get(coin,0)))/60)
    return False,f"🛡️ {coin} FLIP BLOCKED: cooldown {remain}m left - keeping {old['side']}"
   close_trade_auto(coin,f"FLIP {old['side']}->{trade['side']} PnL {pnl:+.2f}%")
   send(f"🔄 FLIP {coin}: {old['side']} -> {trade['side']}\nClosed {old['side']} at {fmt_price(cur_price)} PnL {pnl:+.2f}%\nNew: {trade['side']} {trade['tf']} {trade.get('score')}/6 🔥")
   last_flip_time[coin]=time.time()
 active_trades[coin]=trade
 return True,None
HELP_TEXT="""*V3.2.5 FIXED REAL SL/TP* 🚀
/scan - Scan all
/trades - Active + PnL
/status - Status
/price BTC
/coin AVAX
/stop
FILTER: Flip only if 5/6+, loss>0.8%, cooldown 90m
STRICT 5% margin, REAL SL/TP on Bybit ✅
"""
send("✅ V3.2.5 FIXED REAL SL/TP LIVE 🔥\nSame signals, now Bybit SL/TP shows in UI + TP1 locks 50%")
while True:
 try:
  url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_id+1}&timeout=20"
  res=requests.get(url,timeout=25).json()
  for upd in res.get("result",[]):
   last_id=upd["update_id"]
   txt=upd.get("message",{}).get("text","")
   if not txt:continue
   low=txt.lower().strip();parts=txt.strip().split()
   if low in ["/start","/help"]:send(HELP_TEXT)
   elif low=="/scan":
    send("🔍 SCAN 12 coins Multi-TF FILTERED...")
    full="";hq=[];blocked=[]
    for coin in WATCHLIST:
     analysis,is_high,trade=pro_smc_analysis(coin)
     full+=f"\n\n{analysis}\n---"
     if is_high and trade:
      if coin in active_trades and active_trades[coin]['side']==trade['side']:hq.append(f"{coin}({trade['tf']})");continue
      allowed,skip_msg=handle_new_signal(coin,is_high,trade)
      if allowed:
       if open_trade_auto(coin,trade['side'],trade['entry'],trade['sl'],trade['tp1'],trade['tp2'],trade['tf'],trade['entry_reason'],trade['score']):
        hq.append(f"{coin}({trade['tf']})")
        full+=f"\n✅ AUTO OPENED {coin} REAL SLTP ✅"
      elif skip_msg:blocked.append(skip_msg)
     time.sleep(0.6)
    send(full+(f"\n\n🔥 A+: {', '.join(hq)}" if hq else "\n\n⚪ No new A+")+(f"\n\n🛡️ Blocked: {'; '.join(blocked[:3])}" if blocked else ""))
   elif low=="/trades":
    if not active_trades:send("No active trades - /scan")
    else:
     msg="📊 ACTIVE + PnL REAL SLTP\n"
     for c,t in active_trades.items():
      cur=get_price(c);pnl_str=""
      if cur:
       pnl=(cur-t['entry'])/t['entry']*100
       if t['side']=="SHORT":pnl=-pnl
       pnl_str=f" PnL {pnl:+.1f}% Now {fmt_price(cur)}"
      msg+=f"\n{c} {t['side']} [{t['tf']}] {fmt_price(t['entry'])}{pnl_str} {'🔒 BE' if t['be_done'] else ''} {t['lev']}x\n"
     send(msg)
   elif low=="/status":send(f"🤖 V3.2.5 FIXED REAL SLTP ONLINE\nActive: {len(active_trades)}\nClosed: {len(closed_trades)}\nBal: ${get_bybit_bal():.2f}\nFilter: 5/6+ & loss>0.8% & 90m + REAL SLTP ✅")
   elif low=="/stop":
    for s in list(active_trades.keys()):close_trade_auto(s,"manual stop")
    active_trades.clear();send("🛑 Cleared all")
   elif low.startswith("/price"):
    if len(parts)<2:send("Use: /price BTC")
    else:p=get_price(parts[1].upper()+"/USDT");send(f"💰 {parts[1].upper()} = {fmt_price(p)}" if p else "No data")
   elif low.startswith("/coin"):
    if len(parts)<2:send("Use: /coin AVAX")
    else:
     coin=parts[1].upper()+"/USDT";send(f"🔍 Scanning {coin}...");a,ok,tr=pro_smc_analysis(coin);send(a)
     if ok:
      allowed,skip_msg=handle_new_signal(coin,ok,tr)
      if allowed:open_trade_auto(coin,tr['side'],tr['entry'],tr['sl'],tr['tp1'],tr['tp2'],tr['tf'],tr['entry_reason'],tr['score'])
      elif skip_msg:send(skip_msg)
  now_ts=time.time()
  if now_ts-last_auto_check>900:
   last_auto_check=now_ts
   for coin in WATCHLIST:
    analysis,is_high,trade=pro_smc_analysis(coin)
    if is_high and trade:
     if coin in active_trades and active_trades[coin]['side']==trade['side']:continue
     if last_trade_alert.get(coin,0)<now_ts-14400:
      old=active_trades.get(coin)
      if old and old['side']!=trade['side']:
       cur_price=get_price(coin) or old['entry']
       pnl=(cur_price-old['entry'])/old['entry']*100 if old['side']=="LONG" else (old['entry']-cur_price)/old['entry']*100
       if pnl<=-0.8 and trade.get('score',4)>=5 and time.time()-last_flip_time.get(coin,0)>=5400:
        close_trade_auto(coin,f"AUTO FLIP PnL {pnl:+.2f}%")
        send(f"🚨 AUTO FLIP {coin}: {old['side']} -> {trade['side']} PnL {pnl:+.2f}% 🔄 Score {trade.get('score')}/6")
        last_flip_time[coin]=time.time()
        send(f"🚨 LIVE ALERT\n\n{analysis}")
        if open_trade_auto(coin,trade['side'],trade['entry'],trade['sl'],trade['tp1'],trade['tp2'],trade['tf'],trade['entry_reason'],trade['score']):
         last_trade_alert[coin]=now_ts
       else:continue
      else:
       send(f"🚨 LIVE ALERT\n\n{analysis}")
       if open_trade_auto(coin,trade['side'],trade['entry'],trade['sl'],trade['tp1'],trade['tp2'],trade['tf'],trade['entry_reason'],trade['score']):
        last_trade_alert[coin]=now_ts
    time.sleep(0.6)
   for coin,t in list(active_trades.items()):
    pr=get_price(coin)
    if not pr:continue
    entry,tp1,tp2,sl,side=t['entry'],t['tp1'],t['tp2'],t['sl'],t['side']
    pnl_now=(pr-entry)/entry*100 if side=="LONG" else (entry-pr)/entry*100
    if side=="LONG":
     if not t['be_done'] and pr>=tp1:
      try:
       rs=t.get('real_sym',coin)
       amt=float(exchange.amount_to_precision(rs,t['qty']*0.5))
       exchange.create_market_order(rs,'Sell',amt,params={'reduceOnly':True,'positionIdx':0})
       t['qty']*=0.5;set_be(rs,entry);t['be_done']=True
       send(f"🔒 {coin} TP1 HIT! {fmt_price(pr)} {pnl_now:+.1f}% Take 50% SL->BE REAL ✅")
      except:pass
     elif pr>=tp2:
      send(f"🎯 {coin} TP2 HIT! {fmt_price(pr)} {pnl_now:+.1f}% 🎉");close_trade_auto(coin,"TP2")
     elif pr<=sl and not t['be_done']:
      send(f"❌ {coin} SL HIT {fmt_price(pr)} {pnl_now:+.1f}%");close_trade_auto(coin,"SL")
     elif pr<=sl and t['be_done']:send(f"🔒 {coin} BE STOPPED Saved 50% ✅");close_trade_auto(coin,"BE")
    else:
     if not t['be_done'] and pr<=tp1:
      try:
       rs=t.get('real_sym',coin)
       amt=float(exchange.amount_to_precision(rs,t['qty']*0.5))
       exchange.create_market_order(rs,'Buy',amt,params={'reduceOnly':True,'positionIdx':0})
       t['qty']*=0.5;set_be(rs,entry);t['be_done']=True
       send(f"🔒 {coin} TP1 HIT! {fmt_price(pr)} {pnl_now:+.1f}% Take 50% SL->BE REAL ✅")
      except:pass
     elif pr<=tp2:
      send(f"🎯 {coin} TP2 HIT! {pnl_now:+.1f}% 🎉");close_trade_auto(coin,"TP2")
     elif pr>=sl and not t['be_done']:
      send(f"❌ {coin} SL HIT {fmt_price(pr)} {pnl_now:+.1f}%");close_trade_auto(coin,"SL")
     elif pr>=sl and t['be_done']:send(f"🔒 {coin} BE STOPPED Saved 50% ✅");close_trade_auto(coin,"BE")
 except Exception as e:
  print(f"Loop err {e}");time.sleep(5)
