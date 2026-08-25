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
# KONFIGURASI BOT & API V1 INDODAX
# ==========================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8604634624:AAHKJaVhA3b7fGqOy66yxP9cOkehqwMbn5U")
INDODAX_API_KEY = os.getenv("INDODAX_API_KEY", "FHKI0WWQ-CREFEVQM-4NYKVNHQ-1HAGNSL4-EL9NWIEK").strip()
INDODAX_SECRET_KEY = os.getenv("INDODAX_SECRET_KEY", "431cdf95bf07326082fa4a271bd120b600f0cc13b4beca9248320a69de1ea3cec7e3961016f17d1b").strip()

# Pair koin yang ingin dipantau harganya
PAIRS = ["solidr", "usdtidr"]

# State global penyimpanan harga market
market_prices = {
    "solidr": 0.0,
    "usdtidr": 0.0
}

# ==========================================
# TELEGRAM API HELPERS
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
                {"text": "🔄 Refresh Saldo Real", "callback_data": "btn_refresh"}
            ]
        ]
    }

# ==========================================
# FETCH MARKET PRICE (PUBLIC API)
# ==========================================
def fetch_market_prices():
    for pair in PAIRS:
        url = f"https://indodax.com/api/ticker/{pair}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if "ticker" in data and "last" in data["ticker"]:
                    market_prices[pair] = float(data["ticker"]["last"])
        except Exception:
            pass

# ==========================================
# INDODAX PRIVATE API V1 ENGINE
# ==========================================
def fetch_indodax_v1_account():
    """Mengambil Saldo IDR & Koin Langsung dari Indodax V1 TAPI"""
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
                
                # Saldo IDR Cash Asli
                idr_cash = float(balances.get("idr", 0))
                
                # Rincian Aset Koin
                coin_assets = {}
                crypto_total_value = 0.0
                
                for k, v in balances.items():
                    amt = float(v)
                    if k.lower() != "idr" and amt > 0:
                        coin_name = k.upper()
                        coin_assets[coin_name] = amt
                        
                        # Hitung estimasi IDR koin jika ada pair di market_prices
                        pair_key = f"{k.lower()}idr"
                        if pair_key in market_prices:
                            crypto_total_value += (amt * market_prices[pair_key])

                total_equity = idr_cash + crypto_total_value
                return True, idr_cash, total_equity, coin_assets, "OK"
            else:
                err_msg = res.get("error", "Gagal respon dari Indodax")
                return False, 0.0, 0.0, {}, f"Indodax Error: {err_msg}"
                
    except Exception as e:
        return False, 0.0, 0.0, {}, f"HTTP/Network Error: {str(e)}"

# ==========================================
# DASHBOARD RENDERER
# ==========================================
def build_dashboard():
    fetch_market_prices()
    success, idr_cash, total_equity, coins, err_detail = fetch_indodax_v1_account()
    now = get_wib_time()

    if not success:
        return (
            f"❌ *AKSES SALDO GAGAL*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ Respon Error: `{err_detail}`\n\n"
            f"📌 *Langkah Perbaikan:*\n"
            f"1. Jika error `Invalid key/sign`, pastikan API Key & Secret Key V1 di bot tidak ada typo.\n"
            f"2. Pastikan akun Indodax kamu izin 'Info' pada API-nya aktif.\n"
            f"⏱ _Live Sync: {now} WIB_"
        )

    # Tampilan Dashboard Utama jika sukses
    text = f"📊 *INDODAX LIVE DASHBOARD*\n"
    text += f"━━━━━━━━━━━━━━━━━━━\n"
    text += f"💰 *Estimasi Total Aset:* *Rp {total_equity:,.2f}*\n"
    text += f"💳 *Saldo Cash IDR:* Rp {idr_cash:,.2f}\n\n"
    text += f"📦 *Aset Koin Dimiliki:*\n"
    
    if coins:
        for coin, amt in coins.items():
            text += f"  • {coin}: `{amt:,.4f}`\n"
    else:
        text += "  • (Tidak ada koin aktif)\n"

    text += f"\n📈 *Harga Market Realtime:*\n"
    text += f"  • SOL/IDR: Rp {market_prices['solidr']:,.2f}\n"
    text += f"  • USDT/IDR: Rp {market_prices['usdtidr']:,.2f}\n"

    text += f"━━━━━━━━━━━━━━━━━━━\n"
    text += f"⏱ *Live Sync:* `{now} WIB`"
    return text

# ==========================================
# MAIN BOT ENGINE
# ==========================================
def polling():
    offset = None
    telegram("deleteWebhook", {"drop_pending_updates": "false"})
    print("✅ Bot Indodax Live Sync Aktif...")
    
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
                        
                        telegram("answerCallbackQuery", {"callback_query_id": cb["id"], "text": "🔄 Mengambil Saldo Real..."})
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
