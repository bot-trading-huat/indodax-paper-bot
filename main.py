import os
import time
import urllib.request
import urllib.parse
import json
import hmac
import hashlib
import threading
from datetime import datetime, timezone, timedelta

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

active_dashboards = {}
last_rendered_text = {}

def telegram(method, params=None):
    if not TOKEN: return None
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    try:
        data = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return None

def fetch_realtime_account():
    btc_price = 0.0
    usdt_price = 0.0
    
    # 1. Ticker Realtime tanpa cache (ts timestamp milidetik)
    ts = int(time.time() * 1000)
    try:
        req = urllib.request.Request(f"https://indodax.com/api/ticker/btcidr?ts={ts}", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=2) as resp:
            btc_price = float(json.loads(resp.read().decode("utf-8")).get("ticker", {}).get("last", 0))
    except: pass

    try:
        req = urllib.request.Request(f"https://indodax.com/api/ticker/usdtidr?ts={ts}", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=2) as resp:
            usdt_price = float(json.loads(resp.read().decode("utf-8")).get("ticker", {}).get("last", 0))
    except: pass

    # 2. Ambil Saldo Private API
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
                
                idr_cash = float(balances.get("idr", 0)) + float(balances_hold.get("idr", 0))
                btc_amt = float(balances.get("btc", 0)) + float(balances_hold.get("btc", 0))
                usdt_amt = float(balances.get("usdt", 0)) + float(balances_hold.get("usdt", 0))
                
                btc_val = btc_amt * btc_price
                usdt_val = usdt_amt * usdt_price
                grand_total = idr_cash + btc_val + usdt_val
                
                return True, {
                    "idr": idr_cash,
                    "btc": btc_amt,
                    "btc_val": btc_val,
                    "usdt": usdt_amt,
                    "usdt_val": usdt_val,
                    "grand_total": grand_total,
                    "btc_price": btc_price,
                    "usdt_price": usdt_price
                }, "OK"
            else:
                return False, {}, res.get("error", "API Error")
    except Exception as e:
        return False, {}, str(e)

def build_dashboard():
    success, data, err = fetch_realtime_account()
    now = get_wib_time()

    if not success:
        return f"❌ *GAGAL KONEKSI:* `{err}`"

    text = f"📊 *INDODAX LIVE DASHBOARD (BTC & USDT)*\n"
    text += f"━━━━━━━━━━━━━━━━━━━\n"
    text += f"💰 *Estimasi Total Aset:* *Rp {data['grand_total']:,.0f}*\n"
    text += f"💳 *Saldo Cash IDR:* Rp {data['idr']:,.0f}\n\n"
    
    text += f"🔸 *BTC / IDR*\n"
    text += f"  • Harga Market: Rp {data['btc_price']:,.0f}\n"
    text += f"  • Jumlah Dimiliki: `{data['btc']:.8f}` BTC\n"
    text += f"  • Estimasi Nilai: Rp {data['btc_val']:,.0f}\n\n"
    
    text += f"🔹 *USDT / IDR*\n"
    text += f"  • Harga Market: Rp {data['usdt_price']:,.0f}\n"
    text += f"  • Jumlah Dimiliki: `{data['usdt']:.4f}` USDT\n"
    text += f"  • Estimasi Nilai: Rp {data['usdt_val']:,.0f}\n"

    text += f"━━━━━━━━━━━━━━━━━━━\n"
    text += f"⚡ *Realtime Sync:* `{now} WIB`"
    return text

# Loop Background Super Cepat (Update 1-2 Detik)
def ultra_fast_update_loop():
    while True:
        try:
            new_text = build_dashboard()
            for chat_id, msg_id in list(active_dashboards.items()):
                # Hanya kirim jika teks/harga berubah untuk menghindari spamming telegram
                if last_rendered_text.get(chat_id) != new_text:
                    res = telegram("editMessageText", {
                        "chat_id": str(chat_id),
                        "message_id": msg_id,
                        "text": new_text,
                        "parse_mode": "Markdown",
                        "reply_markup": {"inline_keyboard": [[{"text": "⚡ Realtime Active (Auto Update)", "callback_data": "btn_refresh"}]]}
                    })
                    if res and res.get("ok"):
                        last_rendered_text[chat_id] = new_text
        except Exception:
            pass
        time.sleep(1.5) # Interval tercepat yang aman dari limit Telegram API

def polling():
    offset = None
    telegram("deleteWebhook", {"drop_pending_updates": "false"})
    
    threading.Thread(target=ultra_fast_update_loop, daemon=True).start()
    print("Bot Realtime Ultra Fast Sync Berjalan...")
    
    while True:
        try:
            params = {"timeout": 20}
            if offset: params["offset"] = offset
            res = telegram("getUpdates", params)
            
            if res and res.get("ok"):
                for upd in res.get("result", []):
                    offset = upd["update_id"] + 1
                    
                    if "callback_query" in upd:
                        cb = upd["callback_query"]
                        chat_id = cb["message"]["chat"]["id"]
                        msg_id = cb["message"]["message_id"]
                        active_dashboards[chat_id] = msg_id
                        
                        telegram("answerCallbackQuery", {"callback_query_id": cb["id"], "text": "⚡ Syncing Realtime..."})

                    elif "message" in upd:
                        chat_id = upd["message"]["chat"]["id"]
                        dash_text = build_dashboard()
                        resp = telegram("sendMessage", {
                            "chat_id": str(chat_id),
                            "text": dash_text,
                            "parse_mode": "Markdown",
                            "reply_markup": {"inline_keyboard": [[{"text": "⚡ Realtime Active (Auto Update)", "callback_data": "btn_refresh"}]]}
                        })
                        if resp and resp.get("ok"):
                            active_dashboards[chat_id] = resp["result"]["message_id"]
                            last_rendered_text[chat_id] = dash_text
        except Exception:
            time.sleep(1)

if __name__ == "__main__":
    polling()
