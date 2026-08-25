import os
import time
import threading
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

def get_wib_datetime():
    return datetime.now(WIB)

# ==========================================
# CONFIGURATION
# ==========================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8604634624:AAHKJaVhA3b7fGqOy66yxP9cOkehqwMbn5U")
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8026634236")

INDODAX_API_KEY = os.getenv("INDODAX_API_KEY", "FHKI0WWQ-CREFEVQM-4NYKVNHQ-1HAGNSL4-EL9NWIEK").strip()
INDODAX_SECRET_KEY = os.getenv("INDODAX_SECRET_KEY", "431cdf95bf07326082fa4a271bd120b600f0cc13b4beca9248320a69de1ea3cec7e3961016f17d1b").strip()

PAIRS = ["solidr", "usdtidr"]

coins_state = {}
for p in PAIRS:
    coins_state[p] = {
        "asset_balance": 0.0,
        "last_market_price": 0.0,
        "price_trend": "⏺",
        "chart_history": ["—", "—", "—", "—", "—", "—"]
    }

global_state = {
    "real_idr_balance": 0.0,
    "dashboard_msg_id": None,
    "dashboard_chat_id": ALLOWED_CHAT_ID if ALLOWED_CHAT_ID else None,
    "last_rendered_text": ""
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
    except Exception:
        return None

def get_main_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "🔄 Refresh Dashboard", "callback_data": "btn_refresh"},
                {"text": "💰 Cek Saldo Real", "callback_data": "btn_check_pl"}
            ]
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
        global_state["dashboard_msg_id"] = res["result"]["message_id"]
        global_state["dashboard_chat_id"] = chat_id
        global_state["last_rendered_text"] = text
    return res

def update_menu(chat_id, message_id, text):
    global_state["dashboard_chat_id"] = chat_id
    global_state["last_rendered_text"] = text
    res = telegram("editMessageText", {
        "chat_id": str(chat_id),
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": get_main_keyboard()
    })
    if not res or not res.get("ok"):
        send_menu(chat_id, text)

def answer_callback(cb_id, text=None):
    payload = {"callback_query_id": cb_id}
    if text: payload["text"] = text
    return telegram("answerCallbackQuery", payload)

# ==========================================
# INDODAX PRIVATE API
# ==========================================
def indodax_private_request(method_name, extra_params=None):
    if not INDODAX_API_KEY or not INDODAX_SECRET_KEY:
        return None
    url = "https://indodax.com/tapi"
    nonce = str(int(time.time() * 1000))
    params = {"method": method_name, "nonce": nonce}
    if extra_params: 
        params.update(extra_params)
        
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
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"API Error ({method_name}):", e)
        return None

def sync_real_wallet_balance():
    """Membaca saldo tunai IDR dan aset kripto langsung dari Indodax"""
    res = indodax_private_request("getInfo")
    
    if res and res.get("success") == 1:
        ret = res.get("return", {})
        balances = ret.get("balance", {})
        
        # Saldo Utuh Rupiah
        idr_total = float(balances.get("idr", 0))
        global_state["real_idr_balance"] = idr_total
        
        # Saldo Koin
        for p in PAIRS:
            base_coin = p.replace("idr", "").lower()
            coin_bal = float(balances.get(base_coin, 0))
            coins_state[p]["asset_balance"] = coin_bal
                
        print(f"✅ Sinkronisasi Saldo Berhasil! Total IDR: Rp {idr_total:,.2f}")
    else:
        err_msg = res.get("error", "Koneksi Gagal") if res else "No Response"
        print(f"❌ Gagal Membaca Saldo: {err_msg}")

def fetch_price(pair):
    url = f"https://indodax.com/api/ticker/{pair}"
    st = coins_state[pair]
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "ticker" in data and "last" in data["ticker"]:
                new_price = float(data["ticker"]["last"])
                if new_price > 0:
                    if st["last_market_price"] > 0:
                        if new_price > st["last_market_price"]:
                            st["price_trend"] = "🔺"
                            char = "▇"
                        elif new_price < st["last_market_price"]:
                            st["price_trend"] = "🔻"
                            char = "▂"
                        else:
                            st["price_trend"] = "⏺"
                            char = "—"
                        st["chart_history"].append(char)
                        if len(st["chart_history"]) > 6: st["chart_history"].pop(0)
                    
                    st["last_market_price"] = new_price
                    return new_price
    except Exception as e:
        print(f"Fetch price error ({pair}):", e)
    return st["last_market_price"]

# ==========================================
# DASHBOARD FORMATTER
# ==========================================
def get_indodax_style_dashboard():
    total_idr = global_state["real_idr_balance"]
    total_crypto_val = sum(st["asset_balance"] * st["last_market_price"] for st in coins_state.values())
    total_equity = total_idr + total_crypto_val
    now_wib = get_wib_time()

    text_blocks = [
        f"📊 *INDODAX LIVE DASHBOARD* 📊\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Estimasi Total Aset:* *Rp {total_equity:,.2f}*\n"
        f"💳 *Saldo Cash IDR:* Rp {total_idr:,.2f}\n\n"
        f"📦 *Rincian Pasar & Koin:*"
    ]

    for p in PAIRS:
        st = coins_state[p]
        price = st["last_market_price"]
        asset_val = st["asset_balance"] * price
        pair_display = "SOL/IDR" if p == "solidr" else ("USDT/IDR" if p == "usdtidr" else p.upper())
        chart_vis = "".join(st["chart_history"])

        text_blocks.append(
            f"\n🔹 *{pair_display}* [{st['price_trend']}]\n"
            f"   • Harga Market: Rp {price:,.2f}\n"
            f"   • Koin Dimiliki: {st['asset_balance']:,.4f}\n"
            f"   • Estimasi Nilai: Rp {asset_val:,.2f}\n"
            f"   • Trend Grafik: `{chart_vis}`"
        )

    text_blocks.append(f"\n━━━━━━━━━━━━━━━━━━━\n⏱ *Live Sync:* `{now_wib} WIB`")
    return "\n".join(text_blocks)

# ==========================================
# WORKERS & BOT ENGINE
# ==========================================
def background_market_worker():
    while True:
        for p in PAIRS:
            fetch_price(p)
        
        if global_state["dashboard_chat_id"] and global_state["dashboard_msg_id"]:
            try:
                update_menu(global_state["dashboard_chat_id"], global_state["dashboard_msg_id"], get_indodax_style_dashboard())
            except Exception:
                pass
        time.sleep(5)

def handle_update(update):
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        data = cb.get("data", "")

        if data in ["btn_refresh", "btn_check_pl"]:
            sync_real_wallet_balance()
            answer_callback(cb_id, "🔄 Saldo Real Diperbarui!")
            update_menu(chat_id, msg_id, get_indodax_style_dashboard())
        return

    if "message" in update:
        msg = update["message"]
        chat_id = msg.get("chat", {}).get("id")
        text = (msg.get("text") or "").strip()
        if not chat_id: return

        if text.startswith("/start") or text.startswith("/menu") or text.startswith("/saldo"):
            sync_real_wallet_balance()
            send_menu(chat_id, get_indodax_style_dashboard())

def polling():
    offset = None
    telegram("deleteWebhook", {"drop_pending_updates": "false"})
    print("Bot Live Telegram Aktif...")
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
            time.sleep(2)

if __name__ == "__main__":
    sync_real_wallet_balance()
    for p in PAIRS:
        fetch_price(p)

    threading.Thread(target=background_market_worker, daemon=True).start()
    polling()
