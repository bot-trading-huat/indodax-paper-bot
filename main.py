import os
import time
import urllib.request
import urllib.parse
import json
import hmac
import hashlib
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

# Hanya fokus pada 2 Pair ini
TARGET_PAIRS = ["btcidr", "usdtidr"]

# ==========================================
# TELEGRAM HELPERS
# ==========================================
def telegram(method, params=None):
    if not TOKEN: return None
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    try:
        data = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print("Telegram API Error:", e)
        return None

def get_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "🔄 Refresh Dashboard", "callback_data": "btn_refresh"}
            ]
        ]
    }

# ==========================================
# INDODAX TICKER & BALANCE ENGINE
# ==========================================
def get_market_prices():
    prices = {"BTC": 0.0, "USDT": 0.0}
    for pair in TARGET_PAIRS:
        coin = "BTC" if "btc" in pair else "USDT"
        url = f"https://indodax.com/api/ticker/{pair}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if "ticker" in data and "last" in data["ticker"]:
                    prices[coin] = float(data["ticker"]["last"])
        except Exception:
            pass
    return prices

def fetch_btc_usdt_account():
    prices = get_market_prices()
    
    url = "https://indodax.com/tapi"
    nonce = str(int(time.time() * 1000))
    params = {"method": "getInfo", "nonce": nonce}
    
    post_data_str = urllib.parse.urlencode(params)
    post_data = post_data_str.encode("utf-8")
    
    sign = hmac.new(INDODAX_SECRET_KEY.encode('utf-8'), post_data, hashlib.sha512).hexdigest()
    headers = {
        "Key": INDODAX_API_KEY,
        "Sign": sign,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0"
    }

    try:
        req = urllib.request.Request(url, data=post_data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=7) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            
            if res.get("success") == 1:
                balances = res.get("return", {}).get("balance", {})
                balances_hold = res.get("return", {}).get("balance_hold", {})
                
                # Saldo IDR
                idr_free = float(balances.get("idr", 0))
                idr_hold = float(balances_hold.get("idr", 0))
                idr_total = idr_free + idr_hold
                
                # Saldo BTC
                btc_free = float(balances.get("btc", 0))
                btc_hold = float(balances_hold.get("btc", 0))
                btc_total = btc_free + btc_hold
                btc_idr_val = btc_total * prices["BTC"]
                
                # Saldo USDT
                usdt_free = float(balances.get("usdt", 0))
                usdt_hold = float(balances_hold.get("usdt", 0))
                usdt_total = usdt_free + usdt_hold
                usdt_idr_val = usdt_total * prices["USDT"]
                
                # Grand Total Aset dalam IDR
                grand_total_idr = idr_total + btc_idr_val + usdt_idr_val
                
                return True, {
                    "idr": idr_total,
                    "btc": btc_total,
                    "btc_val": btc_idr_val,
                    "usdt": usdt_total,
                    "usdt_val": usdt_idr_val,
                    "grand_total": grand_total_idr,
                    "btc_price": prices["BTC"],
                    "usdt_price": prices["USDT"]
                }, "OK"
            else:
                err_msg = res.get("error", "Gagal respon dari Indodax")
                return False, {}, f"Indodax Error: {err_msg}"
                
    except Exception as e:
        return False, {}, f"Network Error: {str(e)}"

# ==========================================
# DASHBOARD BUILDER
# ==========================================
def build_dashboard():
    success, data, err_detail = fetch_btc_usdt_account()
    now = get_wib_time()

    if not success:
        return f"❌ *AKSES SALDO GAGAL*\n`{err_detail}`"

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
    text += f"⏱ *Live Sync:* `{now} WIB`"
    return text

# ==========================================
# MAIN POLLING LOOP
# ==========================================
def polling():
    offset = None
    telegram("deleteWebhook", {"drop_pending_updates": "false"})
    print("Bot Indodax (BTC & USDT Only) Aktif...")
    
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
                        
                        telegram("answerCallbackQuery", {"callback_query_id": cb["id"], "text": "🔄 Refreshing..."})
                        telegram("editMessageText", {
                            "chat_id": str(chat_id),
                            "message_id": msg_id,
                            "text": build_dashboard(),
                            "parse_mode": "Markdown",
                            "reply_markup": get_keyboard()
                        })

                    elif "message" in upd:
                        chat_id = upd["message"]["chat"]["id"]
                        telegram("sendMessage", {
                            "chat_id": str(chat_id),
                            "text": build_dashboard(),
                            "parse_mode": "Markdown",
                            "reply_markup": get_keyboard()
                        })
        except Exception as e:
            time.sleep(2)

if __name__ == "__main__":
    polling()
