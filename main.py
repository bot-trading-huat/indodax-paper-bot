import os
import time
import urllib.request
import urllib.parse
import json
import hmac
import hashlib
import threading
from datetime import datetime, timezone, timedelta
from collections import deque

import sys
sys.stdout.reconfigure(line_buffering=True)

WIB = timezone(timedelta(hours=7))

def get_wib_time():
    return datetime.now(WIB).strftime("%H:%M:%S")

# ==========================================
# KONFIGURASI API & BOT
# ==========================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8604634624:AAHKJaVhA3b7fGqOy66yxP9cOkehqwMbn5U")
INDODAX_API_KEY = os.getenv("INDODAX_API_KEY", "FHKI0WWQ-CREFEVQM-4NYKVNHQ-1HAGNSL4-EL9NWIEK").strip()
INDODAX_SECRET_KEY = os.getenv("INDODAX_SECRET_KEY", "431cdf95bf07326082fa4a271bd120b600f0cc13b4beca9248320a69de1ea3cec7e3961016f17d1b").strip()
PAIR = "btcidr"

state = {
    "is_running": False,
    "in_position": False,
    "buy_price": 0.0,
    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,
    
    "last_market_price": 0.0,
    "price_trend": "⏺",
    
    # Sesi per 1 menit
    "minute_start_equity": 0.0,
    "minute_wins": 0,
    "minute_losses": 0,
    "minute_logs": deque(["Bot siap, cek saldo..."], maxlen=8),
    
    # Dashboard Tracking
    "dashboard_chat_id": None,
    "dashboard_msg_id": None,
    "last_rendered_text": ""
}

chart_chars = deque(maxlen=10)

def telegram(method, params=None):
    if not TOKEN: return None
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    try:
        data = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

def add_log(text):
    timestamp = get_wib_time()
    log_line = f"[{timestamp}] {text}"
    state["minute_logs"].append(log_line)

def get_indodax_price():
    try:
        ts = int(time.time() * 1000)
        url = f"https://indodax.com/api/ticker/{PAIR}?ts={ts}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            price = float(data.get("ticker", {}).get("last", 0))
            
            if price > 0:
                if state["last_market_price"] > 0:
                    if price > state["last_market_price"]:
                        state["price_trend"] = "🔺"
                        char = "▇"
                    elif price < state["last_market_price"]:
                        state["price_trend"] = "🔻"
                        char = "▂"
                    else:
                        state["price_trend"] = "⏺"
                        char = "—"
                else:
                    char = "—"
                    
                chart_chars.append(char)
                state["last_market_price"] = price
                
            return price
    except Exception:
        if state["last_market_price"] > 0:
            return state["last_market_price"]
        return 0.0

def generate_block_chart():
    if not chart_chars:
        return "——"
    return "".join(chart_chars)

def fetch_realtime_account():
    price = get_indodax_price()
    
    url = "https://indodax.com/tapi"
    nonce = str(int(time.time() * 1000))
    params = {"method": "getInfo", "nonce": nonce}
    
    post_data = urllib.parse.urlencode(params).encode("utf-8")
    sign = hmac.new(INDODAX_SECRET_KEY.encode('utf-8'), post_data, hashlib.sha512).hexdigest()
    headers = {
        "Key": INDODAX_API_KEY,
        "Sign": sign,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0"
    }

    try:
        req = urllib.request.Request(url, data=post_data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=3) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            if res.get("success") == 1:
                balances = res.get("return", {}).get("balance", {})
                balances_hold = res.get("return", {}).get("balance_hold", {})
                
                idr_cash = float(balances.get("idr", 0))
                idr_hold = float(balances_hold.get("idr", 0))
                total_idr = idr_cash + idr_hold
                
                btc_amt = float(balances.get("btc", 0)) + float(balances_hold.get("btc", 0))
                btc_val = btc_amt * price
                grand_total = total_idr + btc_val
                
                return True, idr_cash, btc_amt, grand_total, price, "OK"
            else:
                return False, 0.0, 0.0, 0.0, price, res.get("error", "API Error")
    except Exception as e:
        return False, 0.0, 0.0, 0.0, price, str(e)

# ==========================================
# KEYBOARDS
# ==========================================
def get_main_keyboard():
    play_stop_btn = (
        {"text": "⏹ Hentikan Bot", "callback_data": "btn_stop"}
        if state["is_running"]
        else {"text": "▶️ Jalankan Bot", "callback_data": "btn_start"}
    )
    return {
        "inline_keyboard": [
            [play_stop_btn],
            [{"text": "📊 Status Bot & Posisi", "callback_data": "btn_status"}],
            [{"text": "📈 Laporan PnL & WinRate", "callback_data": "btn_report"}],
            [{"text": "⚡ Cek Harga BTC Real-Time", "callback_data": "btn_price"}]
        ]
    }

def get_back_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🏠 Kembali ke Dashboard", "callback_data": "btn_home"}]
        ]
    }

# ==========================================
# DASHBOARD TEXT BUILDER
# ==========================================
def get_home_text(is_final=False):
    success, idr_bal, btc_amt, total_equity, price, err = fetch_realtime_account()
    if not success:
        return f"❌ *GAGAL KONEKSI API INDODAX:* `{err}`"

    status_str = "🟢 Aktif 🔘" if state["is_running"] else "🔴 Berhenti 🔘"
    now_wib = get_wib_time()

    pos_info = f"• Posisi: Memegang Aset ({btc_amt:.6f} BTC)" if state["in_position"] else f"• Posisi: IDR Ready (Rp {idr_bal:,.0f})"
    chart_str = generate_block_chart()

    if state["minute_logs"]:
        logs_str = "\n".join(state["minute_logs"])
        block_text = f"```\n{logs_str}\n```"
    else:
        block_text = "```\nMemantau pergerakan market...\n
