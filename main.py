from flask import Flask
from threading import Thread
app=Flask(__name__)
@app.route('/')
def home():return "V3.2.5 x V4.4 FIX ZEC BONK DEBUG"
def run_flask():app.run(host='0.0.0.0',port=10000)
Thread(target=run_flask,daemon=True).start()
import os,ccxt,requests,time
from datetime import datetime,timezone,timedelta
TELEGRAM_TOKEN=os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or ""
CHAT_ID=os.getenv("CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or ""
API_KEY=os.getenv("BYBIT_API_KEY","").strip()
API_SECRET=os.getenv("BYBIT_SECRET","").strip() or os.getenv("BYBIT_API_SECRET","").strip()
ex=ccxt.bybit({'apiKey':API_KEY,'secret':API_SECRET,'enableRateLimit':True,'options':{'defaultType':'unified'}})
try:ex.load_markets()
except:pass
spot=ccxt.okx({'enableRateLimit':True,'options':{'defaultType':'spot'}})
try:spot.load_markets()
except:pass
WAT=timezone(timedelta(hours=1))
WATCHLIST_RAW=["BCH/USDT","ETH/USDT","SOL/USDT","BNB/USDT","DOGE/USDT","BONK/USDT","WIF/USDT","ZEC/USDT","AVAX/USDT","DOT/USDT","ONDO/USDT","PAXG/USDT"]
WATCHLIST=[s+":USDT" if ":USDT" not in s else s for s in WATCHLIST_RAW]
SCAN_TFS=['15m','30m','1h','2h']
MAX_TRADES=4
AUTO_SCAN_SEC=900
PCT_PER_TRADE=0.05
MIN_NOTIONAL=1.0  # FIX: Bybit min for ZEC/BONK is 1-5, not 5.6
closed=[];active={};paused=False
last_flip_time={};last_trade_alert={}
last_id=0;last_scan=0;last_chk=0
def send(m):
 try:requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",data={"chat_id":CHAT_ID,"text":m[:3900],"parse_mode":"Markdown"},timeout=15)
 except:pass
def fmt_price(p):
 if p is None:return "N/A"
 if p<0.0001:return f"${p:.8f}"
 elif p<0.01:return f"${p:.6f}"
 elif p<1:return f"${p:.5f}"
 elif p<100:return f"${p:.4f}"
 else:return f"${p:.2f}"
def get_ohlcv_raw(symbol,timeframe='1h',limit=100):
 try:return spot.fetch_ohlcv(symbol,timeframe,limit=limit)
 except:
  try:return spot.fetch_ohlcv(symbol,timeframe.lower(),limit=limit)
  except:return None
def price(s):
 try:return float(ex.fetch_ticker(s)['last'])
 except:return None
def calc_rsi_list(closes,period=14):
 if len(closes)<period+1:return 50.0
 g,l=[],[]
 for i in range(1,len(closes)):
  d=closes[i]-closes[i-1];g.append(max(d,0));l.append(max(-d,0))
 ag=sum(g[-period:])/period;al=sum(l[-period:])/period
 return 70 if al==0 else 100-(100/(1+ag/al))
def calc_ema_list(closes,period=50):
 if len(closes)<period:return closes[-1]
 k=2/(period+1);e=sum(closes[:period])/period
 for pr in closes[period:]:e=pr*k+e*(1-k)
 return e
def select_best_entry(side,last,bos_level,fvg_exists,fvg_mid,ema50):
 def pct(a,b):return abs(a-b)/b*100 if b else 999
 if fvg_exists and pct(fvg_mid,bos_level)<0.8:return fvg_mid,"FVG 50% + BOS Confluence 🔥"
 if pct(ema50,bos_level)<1.0:return ema50,"EMA50 + BOS Confluence 🔥"
 if fvg_exists:return fvg_mid,"FVG 50% (Imbalance Fill)"
 return bos_level,"BOS Retest / Major S/R"
def bal():
 try:
  b=ex.fetch_balance(params={'accountType':'UNIFIED'})
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
  m=ex.market(sym)
  ex.private_post_v5_position_trading_stop({'category':'linear','symbol':m['id'],'stopLoss':str(ex.price_to_precision(sym, sl)),'takeProfit':str(ex.price_to_precision(sym, tp)),'tpslMode':'Full','positionIdx':0})
  return True
 except Exception as e:print(f"SLTP fail {e}");return False
def set_be(sym,en):
 try:
  m=ex.market(sym)
  ex.private_post_v5_position_trading_stop({'category':'linear','symbol':m['id'],'stopLoss':str(ex.price_to_precision(sym,en)),'tpslMode':'Full','positionIdx':0})
 except:pass
def calc_lev_v44(entry,sl,b):
 slp=abs(entry-sl)/entry if entry else 0.01
 raw=0.20/slp
 lev=max(5,min(int(raw),10))
 margin=b*PCT_PER_TRADE
 if margin*lev*slp>margin*0.20:margin=(margin*0.20)/(lev*slp)
 if margin<0.6:margin=0.6
 if margin>b*PCT_PER_TRADE:margin=b*PCT_PER_TRADE
 return lev,margin
def pro_smc_analysis(symbol):
 raw_sym=symbol.replace(":USDT","")
 ohlcv_1h=get_ohlcv_raw(raw_sym,'1h',100)
 if not ohlcv_1h or len(ohlcv_1h)<60:return f"{symbol}: No 1H data",False,None
 closes_1h=[c[4] for c in ohlcv_1h]
 ema50_1h=calc_ema_list(closes_1h,50)
 htf_bull=closes_1h[-1]>ema50_1h
 htf_trend="BULLISH 🟢" if htf_bull else "BEARISH 🔴"
 best_score=0;best_msg="";best_trade=None
 for tf in SCAN_TFS:
  ohlcv=get_ohlcv_raw(raw_sym,tf,100)
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
    best_trade={"symbol":symbol,"raw":raw_sym,"side":"LONG","entry":best_entry,"sl":sl,"tp1":tp1,"tp2":tp2,"risk":risk,"tf":tf,"entry_reason":entry_reason,"be_done":False,"score":score,"be":False,"amt":0}
    best_msg=f"*{symbol} - A+ LONG [{tf}]* 🟢\nQuality: {score}/6 HIGH\nPrice: {fmt_price(last)}\nTrend: 1H {htf_trend} | {tf} Above EMA50 | RSI {rsi:.1f}\nSetup: {', '.join(reasons)}\n\n🎯 ENTRY: {fmt_price(best_entry)}\n📍 {entry_reason}\nSL: {fmt_price(sl)}\nTP1: {fmt_price(tp1)}\nTP2: {fmt_price(tp2)}\nRR: 1:1.5"
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
    best_trade={"symbol":symbol,"raw":raw_sym,"side":"SHORT","entry":best_entry,"sl":sl,"tp1":tp1,"tp2":tp2,"risk":risk,"tf":tf,"entry_reason":entry_reason,"be_done":False,"score":score,"be":False,"amt":0}
    best_msg=f"*{symbol} - A+ SHORT [{tf}]* 🔴\nQuality: {score}/6 HIGH\nPrice: {fmt_price(last)}\nTrend: 1H {htf_trend} | {tf} Below EMA50 | RSI {rsi:.1f}\nSetup: {', '.join(reasons)}\n\n🎯 ENTRY: {fmt_price(best_entry)}\n📍 {entry_reason}\nSL: {fmt_price(sl)}\nTP1: {fmt_price(tp1)}\nTP2: {fmt_price(tp2)}\nRR: 1:1.5"
 if best_msg:return best_msg,True,best_trade
 else:return f"*{symbol}* - Ranging ⚪ | 1H: {htf_trend}",False,None

def handle_new_signal(coin,is_high,trade):
 if not is_high or not trade:return False,None
 if coin in active:
  old=active[coin]
  if old['side']==trade['side']:return False,f"{coin} already {old['side']}"
  else:
   cur_price=price(coin) or old['entry']
   pnl=(cur_price-old['entry'])/old['entry']*100 if old['side']=="LONG" else (old['entry']-cur_price)/old['entry']*100
   if pnl>-0.8:return False,f"🛡️ {coin} FLIP BLOCKED: {pnl:+.1f}% need -0.8%"
   if trade.get('score',4)<5:return False,f"🛡️ {coin} FLIP BLOCKED: score {trade.get('score')}/6 weak"
   if time.time()-last_flip_time.get(coin,0)<5400:
    remain=int((5400-(time.time()-last_flip_time.get(coin,0)))/60)
    return False,f"🛡️ {coin} FLIP BLOCKED: cooldown {remain}m"
   close_single_real(coin);send(f"🔄 FLIP {coin}: {old['side']} -> {trade['side']} PnL {pnl:+.2f}%");last_flip_time[coin]=time.time()
 active[coin]=trade
 return True,None

def open_trade_auto(tr):
 try:
  b=bal()
  if b<5:send(f"❌ {tr['symbol']} Low bal ${b:.2f}");return None
  if len(active)>=MAX_TRADES:send(f"⚪ {tr['symbol']} skip MAX {MAX_TRADES} reached");return None
  lev,margin=calc_lev_v44(tr['entry'],tr['sl'],b)
  if margin>b*PCT_PER_TRADE:margin=b*PCT_PER_TRADE
  try:ex.set_leverage(lev,tr['symbol'])
  except Exception as e:print(f"set lev fail {e}")
  pr=price(tr['symbol'])
  if not pr:send(f"❌ {tr['symbol']} No Bybit price ticker");return None
  # Get market limits
  try:mkt=ex.market(tr['symbol']);min_amt=mkt.get('limits',{}).get('amount',{}).get('min',0)
  except:min_amt=0
  qty_raw=(margin*lev)/pr
  # Force min notional $1 for ZEC/BONK fix
  if qty_raw*pr<MIN_NOTIONAL:
   qty_raw=(MIN_NOTIONAL*1.1)/pr
  try:qty=float(ex.amount_to_precision(tr['symbol'],qty_raw))
  except:qty=qty_raw
  if qty*pr<0.9:send(f"❌ {tr['symbol']} notional too low ${qty*pr:.2f} raw {qty_raw} pr {pr}");return None
  if min_amt and qty<min_amt:
   # try to bump to min
   try:qty=float(ex.amount_to_precision(tr['symbol'],min_amt))
   except:qty=min_amt
   if qty*pr>margin*lev*1.5:send(f"❌ {tr['symbol']} qty {qty} < min {min_amt} but bumping exceeds margin lev");return None
  side='buy' if tr['side']=='LONG' else 'sell'
  send(f"⏳ Trying {tr['symbol']} {tr['side']} lev {lev}x qty {qty} pr {fmt_price(pr)} notional ${qty*pr:.2f} bal ${b:.2f}")
  ex.create_market_order(tr['symbol'],side,qty,params={'positionIdx':0})
  time.sleep(1.2)
  set_real_sl_tp(tr['symbol'], tr['sl'], tr['tp2'])
  tr['entry']=pr;tr['amt']=qty;tr['lev']=lev;tr['margin']=margin
  return tr
 except Exception as e:
  send(f"❌ OPEN FAIL {tr['symbol']} {e}");print(f"OPEN FAIL {tr['symbol']} {e}");return None

def close_single_real(sym):
 try:
  poss=ex.fetch_positions(params={'accountType':'UNIFIED','symbol':sym})
  for p in poss:
   if p['symbol']!=sym:continue
   sz=float(p.get('contracts',0) or 0)
   if sz==0:continue
   side='sell' if p.get('side','').lower() in ['long','buy'] or sz>0 else 'buy'
   if sz<0 or p.get('side','').lower()=='short':side='buy'
   amt=abs(sz);ex.create_market_order(sym,side,amt,params={'reduceOnly':True,'positionIdx':0});return amt
 except:pass
 return 0
def close_all_real():
 cnt=0
 try:
  poss=ex.fetch_positions(params={'accountType':'UNIFIED'})
  for p in poss:
   sz=float(p.get('contracts',0) or 0)
   if sz==0:continue
   sym=p['symbol'];side='sell' if p.get('side','').lower() in ['long','buy'] or sz>0 else 'buy'
   if sz<0 or p.get('side','').lower()=='short':side='buy'
   amt=abs(sz)
   try:ex.create_market_order(sym,side,amt,params={'reduceOnly':True,'positionIdx':0});cnt+=1;time.sleep(0.3)
   except:pass
  return cnt
 except:return 0
def build_msg(tr,mode="AUTO"):
 entry=tr['entry'];sl=tr['sl'];tp1=tr['tp1'];tp2=tr['tp2']
 slp=(sl-entry)/entry*100;tp1p=(tp1-entry)/entry*100;tp2p=(tp2-entry)/entry*100
 msg=(f"*{tr['symbol']} - A+ {tr['side']} [{tr['tf']}]*\nQuality: {tr['score']}/6 HIGH\nPrice: {fmt_price(price(tr['symbol']) or entry)}\nSetup: {tr['entry_reason']}\n\n🎯 ENTRY: {fmt_price(entry)}\nSL: {fmt_price(sl)} ({slp:+.1f}%)\nTP1: {fmt_price(tp1)} ({tp1p:+.1f}%)\nTP2: {fmt_price(tp2)} ({tp2p:+.1f}%)\nREAL SL/TP ON BYBIT ✅\nBal ${bal():.2f} | Lev {tr.get('lev',5)}x")
 return msg
try:
 poss=ex.fetch_positions(params={'accountType':'UNIFIED'})
 for p in poss:
  sz=float(p.get('contracts',0) or 0)
  if sz!=0:
   sym=p['symbol'];en=float(p.get('entryPrice',0) or 0)
   if en==0:continue
   sd="LONG" if p.get('side','').lower() in ['long','buy'] or sz>0 else "SHORT"
   if sz<0:sd="SHORT"
   active[sym]={"symbol":sym,"raw":sym,"side":sd,"entry":en,"sl":en*0.97 if sd=="LONG" else en*1.03,"tp1":en*1.02 if sd=="LONG" else en*0.98,"tp2":en*1.04 if sd=="LONG" else en*0.96,"tf":"REC","score":5,"be_done":False,"be":False,"amt":abs(sz),"lev":5,"margin":0,"entry_reason":"Recovered"}
   set_real_sl_tp(sym, active[sym]['sl'], active[sym]['tp2'])
except:pass
send(f"🚀 V3.2.5 x V4.4 FIX ZEC BONK DEBUG LIVE\n💰 ${bal():.2f} Active {len(active)}/{MAX_TRADES}\nMIN_NOTIONAL $1 + debug msgs + dup block 90m ✅")
last_id=0
while True:
 try:
  url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_id+1}&timeout=20"
  r=requests.get(url,timeout=25).json()
  for u in r.get("result",[]):
   last_id=u["update_id"]
   txt=u.get("message",{}).get("text","") or ""
   if not txt:continue
   low=txt.lower().strip();parts=txt.strip().split()
   if low in ["/start","/help"]:
    send(f"🤖 V3.2.5 x V4.4 ZEC FIX\nState: {'⏸️ PAUSED' if paused else '▶️ PLAYING'} | ${bal():.2f}\n/scan /trades /bal /pause /play /closeall /status /price /coin")
   elif low=="/status":send(f"📊 STATUS\n{'⏸️ PAUSED' if paused else '▶️ PLAYING'}\n💰 ${bal():.2f}\nActive {len(active)}/{MAX_TRADES}\nMIN $1 ZEC/BONK fix")
   elif low=="/pause":paused=True;send(f"⏸️ PAUSED ${bal():.2f}")
   elif low in ["/play","/resume","/unpause"]:paused=False;send(f"▶️ RESUMED ${bal():.2f}")
   elif low=="/bal":send(f"💰 REAL ${bal():.2f} {len(active)}/{MAX_TRADES} Lev 5-10x 5%")
   elif low=="/trades":
    if not active:send(f"⚪ No active ${bal():.2f}")
    else:
     for c,t in active.items():
      cur=price(c);pn=(cur-t['entry'])/t['entry']*100 if cur else 0
      if t['side']=="SHORT":pn=-pn
      send(f"📊 {c} {t['side']} {pn:+.2f}% BE:{t['be']}\nEntry {fmt_price(t['entry'])} → {fmt_price(cur)}\nSL {fmt_price(t['sl'])} TP2 {fmt_price(t['tp2'])} Lev {t.get('lev',5)}x")
   elif low in ["/stop","/closeall","/close"]:
    n=close_all_real();active.clear();send(f"✅ CLOSED {n} REAL ${bal():.2f}")
   elif low.startswith("/price"):
    if len(parts)<2:send("Use: /price ZEC")
    else:coin=parts[1].upper()+"/USDT:USDT";p=price(coin);send(f"💰 {parts[1].upper()} = {fmt_price(p)}" if p else "No data")
   elif low.startswith("/coin"):
    if len(parts)<2:send("Use: /coin ZEC")
    else:
     coin=parts[1].upper()+"/USDT:USDT";send(f"🔍 Scanning {coin}...");a,ok,tr=pro_smc_analysis(coin);send(a)
     if ok:
      allowed,skip_msg=handle_new_signal(coin,ok,tr)
      if allowed:
       ot=open_trade_auto(tr)
       if ot:tr.update(ot);active[tr['symbol']]=tr;send(build_msg(tr,"🚀 MANUAL"))
       else:send(f"⚠️ {coin} open failed — see fail msg above")
      elif skip_msg:send(skip_msg)
   elif low=="/scan":
    if paused:send("⏸️ PAUSED use /play");continue
    send("🔍 SCAN 12 coins FIX ZEC/BONK...")
    full="";hq=[];blocked=[]
    for coin in WATCHLIST:
     if last_trade_alert.get(coin,0)>time.time()-5400:continue
     analysis,is_high,trade=pro_smc_analysis(coin)
     full+=f"\n\n{analysis}\n---"
     if is_high and trade:
      if coin in active and active[coin]['side']==trade['side']:hq.append(f"{coin}({trade['tf']})");continue
      allowed,skip_msg=handle_new_signal(coin,is_high,trade)
      if allowed:
       ot=open_trade_auto(trade)
       if ot:trade.update(ot);active[trade['symbol']]=trade;hq.append(f"{coin}({trade['tf']}) {trade['lev']}x");full+=f"\n✅ OPENED {coin} {trade['lev']}x REAL ✅"
       else:full+=f"\n❌ {coin} open fail (see above)";last_trade_alert[coin]=time.time()
       last_trade_alert[coin]=time.time()
      elif skip_msg:blocked.append(skip_msg)
     time.sleep(0.5)
    send(full+(f"\n\n🔥 A+: {', '.join(hq)}" if hq else "\n\n⚪ No new A+")+(f"\n\n🛡️ Blocked: {'; '.join(blocked[:3])}" if blocked else ""))
  now_ts=time.time();now_wat=datetime.now(WAT)
  if not paused and now_ts-last_scan>AUTO_SCAN_SEC:
   last_scan=now_ts
   for coin in WATCHLIST:
    if last_trade_alert.get(coin,0)>now_ts-5400:continue
    analysis,is_high,trade=pro_smc_analysis(coin)
    if is_high and trade:
     if coin in active and active[coin]['side']==trade['side']:continue
     old=active.get(coin)
     if old and old['side']!=trade['side']:
      cur_price=price(coin) or old['entry']
      pnl=(cur_price-old['entry'])/old['entry']*100 if old['side']=="LONG" else (old['entry']-cur_price)/old['entry']*100
      if pnl<=-0.8 and trade.get('score',4)>=5 and time.time()-last_flip_time.get(coin,0)>=5400:
       close_single_real(coin)
       if coin in active:del active[coin]
       closed.append({"date":now_wat.strftime("%Y-%m-%d"),"dt":now_wat,"sym":coin,"side":old['side'],"res":"FLIP","pnl":pnl})
       send(f"🔄 AUTO FLIP {coin}: {old['side']} -> {trade['side']} PnL {pnl:+.2f}%")
       last_flip_time[coin]=time.time()
       ot=open_trade_auto(trade)
       if ot:trade.update(ot);active[trade['symbol']]=trade;send(f"🚨 LIVE ALERT\n\n{analysis}\n\n✅ AUTO OPENED {coin} {trade['lev']}x REAL ✅")
       last_trade_alert[coin]=now_ts
      else:continue
     else:
      last_trade_alert[coin]=now_ts
      send(f"🚨 LIVE ALERT\n\n{analysis}")
      ot=open_trade_auto(trade)
      if ot:trade.update(ot);active[trade['symbol']]=trade
      else:send(f"⚠️ {coin} signal but open failed — retry 90m")
    time.sleep(0.5)
   for sym,t in list(active.items()):
    cur=price(sym)
    if not cur:continue
    en=t['entry'];sd=t['side'];pnl=(cur-en)/en*100 if sd=="LONG" else (en-cur)/en*100
    if not t['be']:
     if (sd=="LONG" and cur>=t['tp1']) or (sd=="SHORT" and cur<=t['tp1']):
      try:
       amt=float(ex.amount_to_precision(sym,t['amt']*0.5));side='sell' if sd=="LONG" else 'buy'
       ex.create_market_order(sym,side,amt,params={'reduceOnly':True,'positionIdx':0})
       t['amt']*=0.5;t['be']=True;t['be_done']=True;set_be(sym,en)
       send(f"🎯 {sym} TP1 HIT! {fmt_price(cur)} {pnl:+.2f}% Take 50% SL->BE REAL ✅ 💰 ${bal():.2f}")
      except:pass
    if sd=="LONG":
     if cur>=t['tp2']:close_single_real(sym);del active[sym];send(f"🎯 TP2 {sym} {pnl:+.2f}% 🎉 REAL ${bal():.2f}")
     elif cur<=t['sl']:
      if t['be']:close_single_real(sym);del active[sym];send(f"🔒 BE STOPPED {sym} breakeven ${bal():.2f}")
      else:close_single_real(sym);del active[sym];send(f"❌ SL {sym} {pnl:+.2f}% ${bal():.2f}")
    else:
     if cur<=t['tp2']:close_single_real(sym);del active[sym];send(f"🎯 TP2 {sym} {pnl:+.2f}% 🎉 REAL ${bal():.2f}")
     elif cur>=t['sl']:
      if t['be']:close_single_real(sym);del active[sym];send(f"🔒 BE STOPPED {sym} breakeven ${bal():.2f}")
      else:close_single_real(sym);del active[sym];send(f"❌ SL {sym} {pnl:+.2f}% ${bal():.2f}")
 except Exception as e:print(f"loop {e}");time.sleep(3)
