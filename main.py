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

# ==========================================
# CONFIGURATION
# ==========================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "MASUKKAN_TELEGRAM_BOT_TOKEN_ANDA")

# Kosongkan saja! Bot akan otomatis mengisi Chat ID Anda saat Anda ketik /start di Telegram
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

INDODAX_API_KEY = os.getenv("INDODAX_API_KEY", "MASUKKAN_INDODAX_API_KEY_ANDA")
INDODAX_SECRET_KEY = os.getenv("INDODAX_SECRET_KEY", "MASUKKAN_INDODAX_SECRET_KEY_ANDA")

FEE_RATE = float(os.getenv("FEE_RATE", 0.0021)) 
PAIRS = ["solidr", "tslaidr"]

# Kontrol Risiko Keseluruhan (Max Loss 3%)
global_risk_control = {
    "initial_total_capital": 0.0,
    "max_drawdown_pct": 0.03,
    "portfolio_stopped": False,
    "stop_reason": ""
}

coins_state = {}
for p in PAIRS:
    coins_state[p] = {
        "is_running": True,
        "is_cooldown": False,
        "cooldown_until_time": 0.0,
        "idr_balance": 0.0,
        "asset_balance": 0.0,
        "in_position": False,
        "buy_price": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "logs": [],
        "last_market_price": 0.0,
        "price_trend": "⏺",
        "chart_history": ["—", "—", "—", "—", "—", "—", "—", "—"]
    }

global_state = {
    "dashboard_msg_id": None,
    "dashboard_chat_id": ALLOWED_CHAT_ID if ALLOWED_CHAT_ID else None,
    "last_rendered_text": ""
}

# ==========================================
# API HELPERS
# ==========================================
def telegram(method, params=None):
    if not TOKEN: return None
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    try:
        data = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

def indodax_private_request(method_name, extra_params=None):
    if not INDODAX_API_KEY or not INDODAX_SECRET_KEY or "MASUKKAN" in INDODAX_API_KEY:
        return None
    
    url = "https://indodax.com/tapi"
    nonce = str(int(time.time() * 1000))
    params = {"method": method_name, "nonce": nonce}
    if extra_params: params.update(extra_params)
        
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
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"API Error ({method_name}):", e)
        return None

def sync_real_wallet_balance():
    res = indodax_private_request("getInfo")
    if res and res.get("success") == 1:
        balances = res.get("return", {}).get("balance", {})
        idr_total = float(balances.get("idr", 0))
        
        if global_risk_control["initial_total_capital"] == 0.0 and idr_total > 0:
            global_risk_control["initial_total_capital"] = idr_total

        share_idr = idr_total / len(PAIRS) if len(PAIRS) > 0 else 0
        
        for p in PAIRS:
            coin_code = p.replace("idr", "").replace("x", "")
            coin_bal = float(balances.get(p.replace("idr", ""), balances.get(coin_code, 0.0)))
            
            coins_state[p]["idr_balance"] = share_idr
            coins_state[p]["asset_balance"] = coin_bal
            if coin_bal > 0:
                coins_state[p]["in_position"] = True
                
        print(f"Saldo Asli Disinkronkan. Total IDR: Rp {idr_total:,.2f}")
    else:
        print("Gagal mengambil saldo asli.")

def get_main_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🔄 Refresh Dashboard", "callback_data": "btn_refresh"}]
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
    if text == global_state["last_rendered_text"]: return {"ok": True}
    global_state["dashboard_chat_id"] = chat_id
    global_state["last_rendered_text"] = text

    res = telegram("editMessageText", {
        "chat_id": str(chat_id),
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": get_main_keyboard()
    })
    if not res or not res.get("ok"): send_menu(chat_id, text)
    return res

def answer_callback(cb_id, text=None):
    payload = {"callback_query_id": cb_id}
    if text: payload["text"] = text
    return telegram("answerCallbackQuery", payload)

# ==========================================
# PRICE FETCHER
# ==========================================
def fetch_price(pair):
    url = f"https://indodax.com/api/ticker/{pair}"
    st = coins_state[pair]
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            new_price = float(data["ticker"]["last"])
            if new_price <= 0: return st["last_market_price"]

            if st["last_market_price"] > 0 and new_price != st["last_market_price"]:
                diff = new_price - st["last_market_price"]
                if diff > 0:
                    st["price_trend"] = "🔺"
                    char = "▇" if diff > (new_price * 0.001) else "▂"
                elif diff < 0:
                    st["price_trend"] = "🔻"
                    char = "▂"
                else:
                    st["price_trend"] = "⏺"
                    char = "—"
                st["chart_history"].append(char)
                if len(st["chart_history"]) > 6: st["chart_history"].pop(0)
            
            st["last_market_price"] = new_price
            return new_price
    except Exception:
        return st["last_market_price"]

def update_all_initial_prices():
    for p in PAIRS:
        while coins_state[p]["last_market_price"] <= 0:
            fetch_price(p)
            time.sleep(0.3)

# ==========================================
# INDODAX-STYLE DASHBOARD BUILDER
# ==========================================
def get_indodax_style_dashboard():
    total_combined_equity = 0.0
    total_wins = 0
    total_losses = 0
    now_wib = get_wib_time()
    current_timestamp = time.time()

    for p in PAIRS:
        st = coins_state[p]
        price = st["last_market_price"]
        asset_val = st["asset_balance"] * price
        equity = st["idr_balance"] + asset_val
        total_combined_equity += equity
        total_wins += st["winning_trades"]
        total_losses += st["losing_trades"]

    text_blocks = [
        f"📊 *INDODAX PORTFOLIO DASHBOARD* 📊\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Estimasi Total Aset:* *Rp {total_combined_equity:,.2f}*\n"
    ]

    if global_risk_control["portfolio_stopped"]:
        text_blocks.append(f"🚨 *STATUS: DARURAT (RISK LIMIT 3% TERPICU)*\n_Alasan: {global_risk_control['stop_reason']}_\n")

    text_blocks.append(f"📦 *Rincian Saldo Per Aset (Fund Balance):*")

    for p in PAIRS:
        st = coins_state[p]
        price = st["last_market_price"]
        asset_val = st["asset_balance"] * price
        equity = st["idr_balance"] + asset_val
        share_pct = (equity / total_combined_equity * 100) if total_combined_equity > 0 else 0.0
        
        if st["is_cooldown"]:
            remaining_cd = int(st["cooldown_until_time"] - current_timestamp)
            if remaining_cd > 0:
                status = f"⏳ Cooldown ({remaining_cd}s)"
            else:
                st["is_cooldown"] = False
                status = f"🟢 Aktif ({st['price_trend']})"
        elif global_risk_control["portfolio_stopped"]:
            status = "🛑 Berhenti"
        else:
            status = f"🟢 Aktif ({st['price_trend']})"

        chart_vis = "".join(st["chart_history"])
        pos_str = f"All-In ({st['asset_balance']:,.4f})" if st["in_position"] else f"IDR Ready (Rp {st['idr_balance']:,.0f})"
        pair_display = p.upper().replace("IDR", "/IDR").replace("X", "X/IDR")
        coin_name = p.replace("idr", "").upper()

        text_blocks.append(
            f"\n🔹 *{pair_display}* [{status}]\n"
            f"   • Pegang {coin_name}: `{st['asset_balance']:.6f}`\n"
            f"   • Nilai Aset: Rp {asset_val:,.2f} *({share_pct:.1f}% dari total)*\n"
            f"   • Harga Pasar: Rp {price:,.2f}\n"
            f"   • Grafik Tren: `{chart_vis}`\n"
            f"   • Posisi: {pos_str}\n"
            f"   • Statistik: 🟢 {st['winning_trades']} Win | 🔴 {st['losing_trades']} Loss"
        )

    init_cap = global_risk_control["initial_total_capital"]
    if init_cap > 0 and not global_risk_control["portfolio_stopped"]:
        loss_amount = init_cap - total_combined_equity
        loss_pct = loss_amount / init_cap
        if loss_pct >= global_risk_control["max_drawdown_pct"]:
            global_risk_control["portfolio_stopped"] = True
            global_risk_control["stop_reason"] = f"Total loss mencapai {loss_pct*100:.2f}% (Batas max 3%)"
            for cp in PAIRS:
                coins_state[cp]["is_running"] = False

    all_logs = []
    for p in PAIRS:
        pair_display = p.upper().replace("IDR", "/IDR")
        for lg in coins_state[p]["logs"]:
            all_logs.append(f"[{pair_display}] {lg}")
            
    if all_logs:
        logs_str = "\n".join(all_logs[-4:])
        block_text = f"```\n{logs_str}\n```"
    else:
        block_text = f"```\nMemantau market... siap mengeksekusi.\n
