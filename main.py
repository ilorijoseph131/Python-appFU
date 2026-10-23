from flask import Flask
from threading import Thread
app=Flask(__name__)
@app.route('/')
def home():return "V3.2.19 LIVE $3 AUTO PNL"
def run_flask():app.run(host='0.0.0.0',port=10000)
Thread(target=run_flask,daemon=True).start()
import os,ccxt,requests,time
from datetime import datetime,timezone,timedelta
TELEGRAM_TOKEN=os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
CHAT_ID=os.getenv("CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
BYBIT_API_KEY=os.getenv("BYBIT_API_KEY","").strip()
BYBIT_SECRET=os.getenv("BYBIT_SECRET","").strip()
PCT=33;MAX_T=1;MIN_L=5;MAX_L=6
exchange=ccxt.bybit({'apiKey':BYBIT_API_KEY,'secret':BYBIT_SECRET,'enableRateLimit':True,'options':{'defaultType':'unified'}})
try:exchange.load_markets();print("LIVE OK")
except Exception as e:print(e)
WATCH=[s.replace("/USDT","/USDT:USDT") for s in ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","DOGE/USDT","BONK/USDT","WIF/USDT","ZEC/USDT","AVAX/USDT","DOT/USDT"]]
WAT=timezone(timedelta(hours=1));TFS=['15m','30m','1h','2h']
closed=[];active={};last_flip={};last_daily="";last_weekly="";last_monthly="";last_id=0;last_alert={};last_auto=0
def add_closed(sym,side,tf,en,sl,tp1,tp2,res,pnl,reason):
    now=datetime.now(WAT);closed.append({"date":now.strftime("%Y-%m-%d"),"week":now.strftime("%Y-W%W"),"month":now.strftime("%Y-%m"),"time":now.strftime("%H:%M"),"symbol":sym,"side":side,"tf":tf,"entry":en,"sl":sl,"tp1":tp1,"tp2":tp2,"result":res,"pnl":pnl,"reason":reason})
    if len(closed)>500:closed.pop(0)
def send(m):
    try:requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",data={"chat_id":CHAT_ID,"text":m[:3900],"parse_mode":"Markdown"},timeout=10)
    except:pass
def fmt(p):
    if p is None:return "N/A"
    if p<0.0001:return f"${p:.8f}"
    if p<0.01:return f"${p:.6f}"
    if p<1:return f"${p:.5f}"
    if p<100:return f"${p:.4f}"
    return f"${p:.2f}"
def ohlc(s,tf,l=100):
    try:return exchange.fetch_ohlcv(s,tf,limit=l)
    except:return None
def price(s):
    try:return float(exchange.fetch_ticker(s)['last'])
    except:
        o=ohlc(s,'1h',5);return float(o[-1][4]) if o else None
def bal():
    try:b=exchange.fetch_balance(params={'accountType':'UNIFIED'});return float(b['total'].get('USDT',0) or 0)
    except:return 0
def rsi_calc(c,p=14):
    if len(c)<p+1:return 50
    g,l=[],[]
    for i in range(1,len(c)):d=c[i]-c[i-1];g.append(max(d,0));l.append(max(-d,0))
    ag=sum(g[-p:])/p;al=sum(l[-p:])/p
    return 70 if al==0 else 100-(100/(1+ag/al))
def ema_calc(c,p=50):
    if len(c)<p:return c[-1]
    k=2/(p+1);e=sum(c[:p])/p
    for pr in c[p:]:e=pr*k+e*(1-k)
    return e
def best_entry(bos,fvg,fvg_mid,ema):
    def pd(a,b):return abs(a-b)/b*100 if b else 999
    if fvg and pd(fvg_mid,bos)<0.8:return fvg_mid,"FVG 50% + BOS 🔥"
    if pd(ema,bos)<1.0:return ema,"EMA50 + BOS 🔥"
    if fvg:return fvg_mid,"FVG 50%"
    return bos,"BOS Retest"
def pro_smc(sym):
    o1h=ohlc(sym,'1h',100)
    if not o1h or len(o1h)<60:return f"{sym}: No 1H",False,None
    c1h=[x[4] for x in o1h];e50_1h=ema_calc(c1h,50);bull=c1h[-1]>e50_1h;htf="BULL 🟢" if bull else "BEAR 🔴"
    best_s=0;best_msg="";best_tr=None
    for tf in TFS:
        o=ohlc(sym,tf,100)
        if not o or len(o)<60:continue
        closes=[x[4] for x in o];highs=[x[2] for x in o];lows=[x[3] for x in o];vols=[x[5] for x in o]
        last=closes[-1];ema50=ema_calc(closes,50);rsi=rsi_calc(closes,14);vma=sum(vols[-20:])/20 if len(vols)>=20 else vols[-1]
        ph=max(highs[-30:-5]);pl=min(lows[-30:-5])
        fvg_b=highs[-3]<lows[-1];fvg_s=lows[-3]>highs[-1]
        fvg_mb=(highs[-3]+lows[-1])/2 if fvg_b else last;fvg_ms=(lows[-3]+highs[-1])/2 if fvg_s else last
        score=0;rs=[]
        if last>ph:
            if last>ema50:score+=1;rs.append("Above EMA")
            if 50<rsi<75:score+=1;rs.append(f"RSI {rsi:.0f}")
            if vols[-1]>vma*1.1:score+=1;rs.append("Vol")
            if fvg_b:score+=1;rs.append("FVG")
            if bull:score+=2;rs.append("1H Bull ✅")
            if score>=4 and score>best_s:
                best_s=score;en,re=best_entry(ph,fvg_b,fvg_mb,ema50);sl=min(lows[-10:]);risk=en-sl
                if risk<=0 or risk<en*0.005:risk=en*0.015;sl=en-risk
                tp1=en+risk*1.5;tp2=en+risk*3;rr=abs(tp1-en)/abs(en-sl) if en!=sl else 0
                best_tr={"symbol":sym,"side":"LONG","entry":en,"sl":sl,"tp1":tp1,"tp2":tp2,"risk":risk,"tf":tf,"entry_reason":re,"be_done":False,"score":score}
                best_msg=f"*{sym} LONG [{tf}]* 🟢 {score}/6\nPrice {fmt(last)} {htf} {', '.join(rs)}\n🎯 {fmt(en)} {re}\nSL {fmt(sl)} TP1 {fmt(tp1)} TP2 {fmt(tp2)} RR 1:{rr:.1f}"
        elif last<pl:
            if last<ema50:score+=1;rs.append("Below EMA")
            if 25<rsi<50:score+=1;rs.append(f"RSI {rsi:.0f}")
            if vols[-1]>vma*1.1:score+=1;rs.append("Vol")
            if fvg_s:score+=1;rs.append("FVG")
            if not bull:score+=2;rs.append("1H Bear ✅")
            if score>=4 and score>best_s:
                best_s=score;en,re=best_entry(pl,fvg_s,fvg_ms,ema50);sl=max(highs[-10:]);risk=sl-en
                if risk<=0 or risk<en*0.005:risk=en*0.015;sl=en+risk
                tp1=en-risk*1.5;tp2=en-risk*3;rr=abs(tp1-en)/abs(en-sl) if en!=sl else 0
                best_tr={"symbol":sym,"side":"SHORT","entry":en,"sl":sl,"tp1":tp1,"tp2":tp2,"risk":risk,"tf":tf,"entry_reason":re,"be_done":False,"score":score}
                best_msg=f"*{sym} SHORT [{tf}]* 🔴 {score}/6\nPrice {fmt(last)} {htf} {', '.join(rs)}\n🎯 {fmt(en)} {re}\nSL {fmt(sl)} TP1 {fmt(tp1)} TP2 {fmt(tp2)} RR 1:{rr:.1f}"
    if best_msg:return best_msg,True,best_tr
    return f"*{sym}* Ranging ⚪ {htf}",False,None
def calc_lev(en,sl):
    d=abs(en-sl)/en if en else 0.01;ml=0.2/d if d>0 else 5;return max(MIN_L,min(int(ml),MAX_L))
def open_bybit(sym,side,lev,margin):
    try:
        try:exchange.set_leverage(lev,sym,params={'marginMode':'cross'})
        except:pass
        pr=price(sym)
        if not pr:return None,0,0
        amt=(margin*lev)/pr;amt=float(exchange.amount_to_precision(sym,amt))
        if amt*pr<5:amt=float(exchange.amount_to_precision(sym,5.1/pr))
        od=exchange.create_market_order(sym,'buy' if side=='LONG' else 'sell',amt,params={'positionIdx':0})
        return od,amt,pr
    except Exception as e:send(f"❌ OPEN {sym}: {e}");return None,0,0
def close_bybit(sym,side,amt,perc=100):
    try:
        cs='sell' if side=='LONG' else 'buy';a=float(exchange.amount_to_precision(sym,amt*perc/100))
        exchange.create_market_order(sym,cs,a,params={'reduceOnly':True,'positionIdx':0})
    except Exception as e:send(f"❌ CLOSE {sym}: {e}")
def report(ft):
    now=datetime.now(WAT)
    if ft=="today":tr=[t for t in closed if t['date']==now.strftime("%Y-%m-%d")];title=f"📅 TODAY {now.strftime('%Y-%m-%d')}"
    elif ft=="week":tr=[t for t in closed if t['week']==now.strftime("%Y-W%W")];title=f"📆 WEEK {now.strftime('%Y-W%W')}"
    else:tr=[t for t in closed if t['month']==now.strftime("%Y-%m")];title=f"📆 MONTH {now.strftime('%Y-%m')}"
    if not tr:return f"{title}\nNo trades - PnL 0%"
    w=len([t for t in tr if t['pnl']>0]);l=len([t for t in tr if t['pnl']<0]);wr=w/len(tr)*100 if tr else 0
    msg=f"{title}\nTotal:{len(tr)} Wins:{w} Loss:{l} WR:{wr:.1f}%\n"
    for t in tr[-10:]:msg+=f"{'✅' if t['pnl']>0 else '❌'} {t['symbol']} {t['result']} {t['pnl']:+.1f}% {t['date']}\n"
    msg+=f"Total PnL:{sum([t['pnl'] for t in tr]):+.2f}%"
    return msg
HELP="*V3.2.19 LIVE $3*\n/scan /trades /today /week /month /bal /test /price BTC /coin AVAX /status /stop\nAuto Daily 23:55 Weekly Sun 23:00 Monthly last day"
send(f"✅ V3.2.19 LIVE $3\nBal ${bal():.2f} $1x5=$5 Max1\nFVG+Vol+BOS kept\nAuto PNL 23:55/Week/Month\n/scan /bal /test")
def handle(coin,ok,tr):
    if not ok or not tr:return True,None
    if coin in active:
        old=active[coin]
        if old['side']==tr['side']:return False,f"{coin} already {old['side']}"
        cur=price(coin) or old['entry'];pnl=(cur-old['entry'])/old['entry']*100 if old['side']=="LONG" else (old['entry']-cur)/old['entry']*100
        if pnl>-0.8:return False,f"🛡️ {coin} BLOCK {pnl:+.1f}% need -0.8%"
        if tr['score']<5:return False,f"🛡️ {coin} BLOCK {tr['score']}/6 need 5/6+"
        if time.time()-last_flip.get(coin,0)<5400:return False,f"🛡️ {coin} cooldown"
        add_closed(coin,old['side'],old['tf'],old['entry'],old['sl'],old['tp1'],old['tp2'],"FLIPPED",pnl,old['entry_reason'])
        try:
            if 'amount' in old:close_bybit(coin,old['side'],old['amount'],100)
        except:pass
        del active[coin];last_flip[coin]=time.time();send(f"🔄 FLIP {coin} {old['side']}->{tr['side']} {pnl:+.1f}%")
    return True,None
while True:
    try:
        now=datetime.now(WAT);td=now.strftime("%Y-%m-%d");wk=now.strftime("%Y-W%W");mn=now.strftime("%Y-%m")
        if now.hour==23 and now.minute>=55 and last_daily!=td:
            send(report("today")+f"\n💰 Bal ${bal():.2f} Reset 00:00");last_daily=td
        if now.weekday()==6 and now.hour==23 and last_weekly!=wk:
            send(report("week")+f"\n💰 Bal ${bal():.2f}");last_weekly=wk
        if (now+timedelta(days=1)).month!=now.month and now.hour==23 and now.minute>=55 and last_monthly!=mn:
            send(report("month")+f"\n💰 Bal ${bal():.2f}");last_monthly=mn
        r=requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_id+1}&timeout=20",timeout=25).json()
        for upd in r.get("result",[]):
            last_id=upd["update_id"];txt=upd.get("message",{}).get("text","");low=txt.lower().strip();parts=txt.split()
            if low in ["/start","/help"]:send(HELP)
            elif low=="/bal":b=bal();send(f"💰 Bal ${b:.2f} Margin ${b*PCT/100:.2f} x{MIN_L}-{MAX_L} Active {len(active)}/{MAX_T} Today {sum([t['pnl'] for t in closed if t['date']==td]):+.2f}%")
            elif low=="/test":
                b=bal()
                if b<1:send(f"❌ Bal ${b:.2f} need $1");continue
                pr=price("BTC/USDT:USDT");mg=max(1.0,b*0.33);amt=float(exchange.amount_to_precision("BTC/USDT:USDT",(mg*5)/pr))
                if amt*pr<5:amt=float(exchange.amount_to_precision("BTC/USDT:USDT",5.1/pr))
                try:o=exchange.create_market_order("BTC/USDT:USDT","buy",amt,params={'positionIdx':0});send(f"✅ TEST OPEN ${amt*pr:.2f}");time.sleep(2);exchange.create_market_order("BTC/USDT:USDT","sell",amt,params={'reduceOnly':True,'positionIdx':0});send("✅ TEST CLOSE OK /scan")
                except Exception as e:send(f"❌ TEST FAIL {e}")
            elif low=="/scan":
                send("🔍 SCAN 10 coins FVG+Vol+BOS...");full="";hq=[];blk=[]
                for coin in WATCH:
                    an,ok,tr=pro_smc(coin);full+=f"\n\n{an}\n---"
                    if ok and tr:
                        allow,msg=handle(coin,ok,tr)
                        if allow:
                            b=bal()
                            if b<1 or len(active)>=MAX_T:
                                if len(active)>=MAX_T:blk.append(f"{coin} Max{MAX_T}")
                                continue
                            lev=calc_lev(tr['entry'],tr['sl']);mg=max(1.0,b*PCT/100);o,a,p=open_bybit(coin,tr['side'],lev,mg)
                            if o:tr['amount']=a;tr['entry']=p;tr['margin']=mg;tr['leverage']=lev;active[coin]=tr;last_alert[coin]=time.time();hq.append(coin);send(f"🟢 OPENED {coin} {tr['side']} {lev}x {tr['entry_reason']} M ${mg:.2f}")
                            else:blk.append(f"{coin} fail")
                        elif msg:blk.append(msg)
                    time.sleep(0.3)
                send(full[:3500]+(f"\n\n🔥 OPENED {', '.join(hq)}" if hq else "\n\n⚪ No A+ 4/6")+(f"\n🛡️ {'; '.join(blk[:2])}" if blk else ""))
            elif low=="/trades":
                if not active:send("No active - /scan")
                else:
                    m="📊 ACTIVE\n"
                    for c,t in active.items():cur=price(c);pn=(cur-t['entry'])/t['entry']*100 if t['side']=="LONG" else (t['entry']-cur)/t['entry']*100 if cur else 0;m+=f"{c} {t['side']} {fmt(t['entry'])} PnL {pn:+.1f}% {'🔒' if t['be_done'] else ''} {t.get('leverage',5)}x\n"
                    send(m)
            elif "today" in low or low=="/today":send(report("today"))
            elif "week" in low or low=="/week":send(report("week"))
            elif "month" in low or low=="/month":send(report("month"))
            elif low=="/status":send(f"Active {len(active)}/{MAX_T} Closed {len(closed)} Bal ${bal():.2f} Today {sum([t['pnl'] for t in closed if t['date']==td]):+.1f}% Week {sum([t['pnl'] for t in closed if t['week']==wk]):+.1f}%")
            elif low=="/stop":
                for c,t in list(active.items()):
                    try:close_bybit(c,t['side'],t['amount'],100)
                    except:pass
                active.clear();send("🛑 Cleared")
            elif low.startswith("/price"):
                if len(parts)<2:send("Use /price BTC")
                else:p=price(parts[1].upper()+"/USDT:USDT");send(f"💰 {parts[1].upper()} {fmt(p)}")
            elif low.startswith("/coin"):
                if len(parts)<2:send("Use /coin AVAX")
                else:coin=parts[1].upper()+"/USDT:USDT";an,ok,tr=pro_smc(coin);send(an)
                if ok and tr:
                    allow,msg=handle(coin,ok,tr)
                    if allow:
                        b=bal();lev=calc_lev(tr['entry'],tr['sl']);mg=max(1.0,b*PCT/100);o,a,p=open_bybit(coin,tr['side'],lev,mg)
                        if o:tr['amount']=a;tr['entry']=p;tr['margin']=mg;tr['leverage']=lev;active[coin]=tr;send(f"🟢 OPENED {coin} {tr['side']}")
                    elif msg:send(msg)
        if time.time()-last_auto>900:
            last_auto=time.time()
            for coin in WATCH:
                an,ok,tr=pro_smc(coin)
                if ok and tr and len(active)<MAX_T and coin not in active and time.time()-last_alert.get(coin,0)>14400:
                    b=bal()
                    if b>=1:lev=calc_lev(tr['entry'],tr['sl']);mg=max(1.0,b*PCT/100);o,a,p=open_bybit(coin,tr['side'],lev,mg); 
                    if o:tr['amount']=a;tr['entry']=p;tr['margin']=mg;tr['leverage']=lev;active[coin]=tr;last_alert[coin]=time.time();send(f"🚨 AUTO {coin} {tr['side']} {lev}x\n{an}")
                time.sleep(0.4)
            for coin,t in list(active.items()):
                pr=price(coin)
                if not pr:continue
                en,tp1,tp2,sl,side=t['entry'],t['tp1'],t['tp2'],t['sl'],t['side'];pnl=(pr-en)/en*100 if side=="LONG" else (en-pr)/en*100
                if side=="LONG":
                    if not t['be_done'] and pr>=tp1:close_bybit(coin,side,t['amount'],50);t['be_done']=True;t['amount']*=0.5;add_closed(coin,side,t['tf'],en,sl,tp1,tp2,"TP1+BE",pnl*0.5,t['entry_reason']);send(f"🔒 {coin} TP1 {pnl:+.1f}%")
                    elif pr>=tp2:close_bybit(coin,side,t['amount'],100);add_closed(coin,side,t['tf'],en,sl,tp1,tp2,"TP2",pnl,t['entry_reason']);del active[coin];send(f"🎯 {coin} TP2 {pnl:+.1f}%")
                    elif pr<=sl and not t['be_done']:close_bybit(coin,side,t['amount'],100);add_closed(coin,side,t['tf'],en,sl,tp1,tp2,"SL",pnl,t['entry_reason']);del active[coin];send(f"❌ {coin} SL {pnl:+.1f}%")
                else:
                    if not t['be_done'] and pr<=tp1:close_bybit(coin,side,t['amount'],50);t['be_done']=True;t['amount']*=0.5;add_closed(coin,side,t['tf'],en,sl,tp1,tp2,"TP1+BE",pnl*0.5,t['entry_reason']);send(f"🔒 {coin} TP1 {pnl:+.1f}%")
                    elif pr<=tp2:close_bybit(coin,side,t['amount'],100);add_closed(coin,side,t['tf'],en,sl,tp1,tp2,"TP2",pnl,t['entry_reason']);del active[coin];send(f"🎯 {coin} TP2 {pnl:+.1f}%")
                    elif pr>=sl and not t['be_done']:close_bybit(coin,side,t['amount'],100);add_closed(coin,side,t['tf'],en,sl,tp1,tp2,"SL",pnl,t['entry_reason']);del active[coin];send(f"❌ {coin} SL {pnl:+.1f}%")
    except Exception as e:print(f"Loop err {e}");time.sleep(3)
