import os
import time
import json
import threading
import urllib.request
import urllib.parse
import hmac
import hashlib
from datetime import datetime, timezone, timedelta
import sys

sys.stdout.reconfigure(line_buffering=True)

WIB = timezone(timedelta(hours=7))

def get_wib_time():
    return datetime.now(WIB).strftime("%H:%M:%S")

# ==========================================
# CONFIGURATION REAL ACCOUNT
# ==========================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8604634624:AAHKJaVhA3b7fGqOy66yxP9cOkehqwMbn5U")
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8026634236")

# API Credentials Indodax (Uang Asli)
INDODAX_API_KEY = os.getenv("INDODAX_API_KEY", "FHKI0WWQ-CREFEVQM-4NYKVNHQ-1HAGNSL4-EL9NWIEK").strip()
INDODAX_SECRET_KEY = os.getenv("INDODAX_SECRET_KEY", "431cdf95bf07326082fa4a271bd120b600f0cc13b4beca9248320a69de1ea3cec7e3961016f17d1b").strip()

# Pair Crypto (Contoh: btc_idr, eth_idr, solidr)
PAIR = os.getenv("PAIR", "btc_idr").lower()
BASE_COIN = PAIR.replace("idr", "").lower()

state = {
    "is_running": True,
    "idr_balance": 0.0,
    "asset_balance": 0.0,
    "in_position": False,
    "buy_price": 0.0,
    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,
    "minute_logs": [],
    "dashboard_msg_id": None,
    "dashboard_chat_id": ALLOWED_CHAT_ID,
    "last_rendered_text": "",
    "last_market_price": 0.0
}

state_lock = threading.Lock()

# ==========================================
# INDODAX PRIVATE API (TAPI - UANG ASLI)
# ==========================================
def indodax_private_request(method_name, extra_params=None):
    if not INDODAX_API_KEY or not INDODAX_SECRET_KEY:
        print("❌ API Key atau Secret Key belum disetting!")
        return None
        
    url = "https://indodax.com/tapi"
    nonce = str(int(time.time() * 1000))
    params = {"method": method_name, "nonce": nonce}
    if extra_params:
        params.update(extra_params)
        
    post_data_str = urllib.parse.urlencode(params)
    post_data = post_data_str.encode("utf-8")
    
    sign = hmac.new(
        INDODAX_SECRET_KEY.encode('utf-8'), 
        post_data_str.encode('utf-8'), 
        hashlib.sha512
    ).hexdigest()
    
    headers = {
        "Key": INDODAX_API_KEY,
        "Sign": sign,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0"
    }
    
    try:
        req = urllib.request.Request(url, data=post_data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=7) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"❌ Indodax Private API Error ({method_name}):", e)
        return None

def sync_real_wallet_balance():
    res = indodax_private_request("getInfo")
    if res and res.get("success") == 1:
        ret = res.get("return", {})
        balances = ret.get("balance", {})
        
        idr_total = float(balances.get("idr") or balances.get("IDR") or 0)
        coin_total = float(balances.get(BASE_COIN) or balances.get(BASE_COIN.upper()) or 0)
        
        with state_lock:
            state["idr_balance"] = idr_total
            state["asset_balance"] = coin_total
            state["in_position"] = coin_total > 0.0001
        
        print(f"✅ SALDO REAL SYNCED | IDR: Rp {idr_total:,.2f} | {BASE_COIN.upper()}: {coin_total}")
    else:
        print("❌ GAGAL MEMBACA SALDO INDODAX REAL:", res)

def execute_real_buy(idr_amount):
    """Mengeksekusi Order Beli Instan di Indodax dengan Uang Asli"""
    params = {
        "pair": PAIR,
        "type": "buy",
        "price": str(int(state["last_market_price"])),
        "idr": str(int(idr_amount))
    }
    return indodax_private_request("trade", params)

def execute_real_sell(coin_amount):
    """Mengeksekusi Order Jual Instan di Indodax dengan Uang Asli"""
    params = {
        "pair": PAIR,
        "type": "sell",
        "price": str(int(state["last_market_price"])),
        "coin": str(coin_amount)
    }
    return indodax_private_request("trade", params)

# ==========================================
# PUBLIC MARKET PRICE FETCH
# ==========================================
def get_indodax_price():
    url = f"https://indodax.com/api/ticker/{PAIR}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            price = float(data["ticker"]["last"])
            with state_lock:
                state["last_market_price"] = price
            return price
    except Exception as e:
        print("Error fetch price:", e)
        return state["last_market_price"]

# ==========================================
# TELEGRAM HELPERS & DASHBOARD
# ==========================================
def telegram(method, params=None):
    if not TOKEN: return None
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = json.dumps(params or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print("Telegram API Error:", e)
        return None

def get_main_keyboard():
    play_stop_btn = (
        {"text": "⏹ Hentikan Bot", "callback_data": "btn_stop"}
        if state["is_running"]
        else {"text": "▶️ Jalankan Bot", "callback_data": "btn_start"}
    )
    return {
        "inline_keyboard": [
            [play_stop_btn],
            [{"text": "🔄 Synchronize Saldo Real", "callback_data": "btn_sync"}],
            [{"text": f"⚡ Harga {PAIR.upper()} Real-Time", "callback_data": "btn_price"}]
        ]
    }

def send_menu(chat_id, text):
    res = telegram("sendMessage", {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": get_main_keyboard()
    })
    if res and res.get("ok"):
        with state_lock:
            state["dashboard_msg_id"] = res["result"]["message_id"]
            state["dashboard_chat_id"] = chat_id
            state["last_rendered_text"] = text
    return res

def update_menu(chat_id, message_id, text):
    with state_lock:
        state["dashboard_msg_id"] = message_id
        state["dashboard_chat_id"] = chat_id
        state["last_rendered_text"] = text

    return telegram("editMessageText", {
        "chat_id": str(chat_id),
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": get_main_keyboard()
    })

def answer_callback(callback_query_id, text=None):
    payload = {"callback_query_id": callback_query_id}
    if text: payload["text"] = text
    return telegram("answerCallbackQuery", payload)

def get_home_text():
    with state_lock:
        is_running = state["is_running"]
        idr_bal = state["idr_balance"]
        asset_bal = state["asset_balance"]
        in_pos = state["in_position"]
        logs = list(state["minute_logs"])
        price = state["last_market_price"]

    status_str = "🟢 *BERJALAN (REAL TRADING)*" if is_running else "🔴 *BERHENTI (STOPPED)*"
    asset_val = asset_bal * price
    total_equity = idr_bal + asset_val
    now_wib = get_wib_time()

    pos_info = f"⚡ *Posisi:* Holding {BASE_COIN.upper()} ({asset_bal:,.4f})" if in_pos else "💵 *Posisi:* Standby (Saldo IDR Siap)"

    logs_str = "\n".join(logs[-6:]) if logs else "Memantau pasar akun real..."

    return (
        f"🔴 *BOT TRADING INDODAX (AKUN REAL)* 🔴\n"
        f"📌 Pair Target: *{PAIR.upper()}*\n\n"
        f"Status Bot: {status_str}\n"
        f"💰 *Total Equity Real:* Rp {total_equity:,.2f}\n"
        f"💳 *Saldo IDR Real:* Rp {idr_bal:,.2f}\n"
        f"📦 *Nilai Aset Real:* Rp {asset_val:,.2f}\n"
        f"{pos_info}\n"
        f"⏱ _Live Update: {now_wib} WIB_\n\n"
        f"📋 *LOG TRANSAKSI:* \n```\n{logs_str}\n```\n"
        f"Gunakan menu di bawah untuk mengelola bot:"
    )

# ==========================================
# TRADING ENGINE & WORKERS
# ==========================================
def background_worker():
    while True:
        try:
            get_indodax_price()
            sync_real_wallet_balance()

            with state_lock:
                is_running = state["is_running"]
                chat_id = state["dashboard_chat_id"]
                msg_id = state["dashboard_msg_id"]

            if is_running and chat_id and msg_id:
                new_text = get_home_text()
                update_menu(chat_id, msg_id, new_text)
        except Exception as e:
            print("Background Worker Error:", e)
        time.sleep(10)

def handle_update(update):
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        data = cb.get("data", "")

        if data == "btn_start":
            with state_lock:
                state["is_running"] = True
            answer_callback(cb_id, "▶️ Bot Real Trading Dijalankan.")
            update_menu(chat_id, msg_id, get_home_text())
        elif data == "btn_stop":
            with state_lock:
                state["is_running"] = False
            answer_callback(cb_id, "⏹ Bot Real Trading Dihentikan.")
            update_menu(chat_id, msg_id, get_home_text())
        elif data == "btn_sync":
            sync_real_wallet_balance()
            answer_callback(cb_id, f"✅ Saldo Real Diperbarui: Rp {state['idr_balance']:,.2f}")
            update_menu(chat_id, msg_id, get_home_text())
        elif data == "btn_price":
            price = get_indodax_price()
            answer_callback(cb_id, f"Harga {PAIR.upper()}: Rp {price:,.0f}")
        return

    if "message" in update:
        msg = update["message"]
        chat_id = msg.get("chat", {}).get("id")
        text = (msg.get("text") or "").strip()
        if not chat_id: return

        if text.startswith("/start") or text.startswith("/menu"):
            sync_real_wallet_balance()
            send_menu(chat_id, get_home_text())

def polling():
    offset = None
    telegram("deleteWebhook", {"drop_pending_updates": "false"})
    print("Bot Real Trading Aktif...")
    while True:
        try:
            params = {"timeout": 20, "allowed_updates": json.dumps(["message", "callback_query"])}
            if offset is not None: params["offset"] = offset
            res = telegram("getUpdates", params)
            if res and res.get("ok"):
                for upd in res.get("result", []):
                    offset = upd["update_id"] + 1
                    handle_update(upd)
        except Exception as e:
            print("Polling Error:", e)
            time.sleep(4)

if __name__ == "__main__":
    get_indodax_price()
    sync_real_wallet_balance()
    threading.Thread(target=background_worker, daemon=True).start()
    polling()
