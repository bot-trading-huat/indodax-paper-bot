import os,time,json,urllib.request,urllib.parse
from datetime import datetime

START_BALANCE=float(os.getenv("START_BALANCE","100000"))
FEE_RATE=float(os.getenv("FEE_RATE","0.002"))
TAKE_PROFIT=float(os.getenv("TAKE_PROFIT","0.02"))
STOP_LOSS=float(os.getenv("STOP_LOSS","0.01"))
DAILY_LOSS_LIMIT=float(os.getenv("DAILY_LOSS_LIMIT","0.05"))
PAIR=os.getenv("PAIR","btc_idr")
INTERVAL=int(os.getenv("INTERVAL_SECONDS","30"))
TG_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","")
TG_CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","")

balance=START_BALANCE
position=None
day_start=START_BALANCE
trades=[]
last_day=datetime.now().date()

def ticker():
    url=f"https://indodax.com/api/{PAIR}/ticker"
    with urllib.request.urlopen(url,timeout=10) as r:
        return json.loads(r.read())["ticker"]

def tg(text):
    if not TG_TOKEN or not TG_CHAT_ID:
        print(text); return
    data=urllib.parse.urlencode({"chat_id":TG_CHAT_ID,"text":text}).encode()
    req=urllib.request.Request(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",data=data)
    try: urllib.request.urlopen(req,timeout=10).read()
    except Exception as e: print("Telegram:",e)

def report():
    pnl=balance-day_start
    pct=(pnl/day_start*100) if day_start else 0
    wins=sum(1 for x in trades if x>0)
    losses=sum(1 for x in trades if x<0)
    tg(f"📊 PAPER REPORT\nPair: {PAIR.upper()}\nSaldo: Rp{balance:,.0f}\nPnL hari ini: Rp{pnl:,.0f} ({pct:+.2f}%)\nTrade: {len(trades)} | Win: {wins} | Loss: {losses}\nMode: DEMO / PAPER TRADING")

def main():
    global balance,position,day_start,trades,last_day
    tg(f"🟢 Paper bot aktif\nModal virtual: Rp{balance:,.0f}\nPair: {PAIR.upper()}")
    while True:
        try:
            now=datetime.now()
            if now.date()!=last_day:
                report(); last_day=now.date(); day_start=balance; trades=[]
            t=ticker()
            price=float(t["last"]); high=float(t["high"]); low=float(t["low"])
            ref=(high+low)/2
            if position is None and ref>0 and price<ref*0.995:
                size=min(balance*0.50, balance*0.01/STOP_LOSS)
                if size>10000:
                    position={"entry":price,"qty":size/price,"cost":size}
                    tg(f"🟢 DEMO ENTRY\nPrice: Rp{price:,.0f}\nSize: Rp{size:,.0f}\nTP: Rp{price*(1+TAKE_PROFIT):,.0f}\nSL: Rp{price*(1-STOP_LOSS):,.0f}")
            elif position:
                entry=position["entry"]; pct=(price-entry)/entry
                if pct>=TAKE_PROFIT or pct<=-STOP_LOSS:
                    gross=position["qty"]*(price-entry)
                    fees=position["cost"]*FEE_RATE+(position["qty"]*price)*FEE_RATE
                    pnl=gross-fees
                    balance+=pnl; trades.append(pnl)
                    label="TP" if pct>=TAKE_PROFIT else "SL"
                    tg(f"{'🟢' if pnl>=0 else '🔴'} DEMO EXIT {label}\nEntry: Rp{entry:,.0f}\nExit: Rp{price:,.0f}\nPnL: Rp{pnl:,.0f}\nSaldo: Rp{balance:,.0f}")
                    position=None
            if balance<=day_start*(1-DAILY_LOSS_LIMIT):
                tg("🛑 DAILY LOSS LIMIT\nDemo bot berhenti sementara.")
                time.sleep(300)
        except Exception as e:
            print("Loop error:",repr(e))
        time.sleep(INTERVAL)

if __name__=="__main__": main()
