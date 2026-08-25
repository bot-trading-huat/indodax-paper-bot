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
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

INDODAX_API_KEY = os.getenv("INDODAX_API_KEY", "")
INDODAX_SECRET_KEY = os.getenv("INDODAX_SECRET_KEY", "")

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
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Telegram API Error ({method}):", e)
        return None

def indodax_private_request(method_name, extra_params=None):
    if not INDODAX_API_KEY or not INDODAX_SECRET_KEY:
        return None
    
    url = "https://indodax.com/tapi"
    nonce = str(int(time.time() * 1000))
    params = {"method": method_name, "nonce": nonce}
    if extra_params: params.update(extra_params)
        
    try:
        post_data = urllib.parse.urlencode(params).encode("utf-8")
        sign = hmac.new(INDODAX_SECRET_KEY.encode('utf-8'), post_data, hashlib.sha512).hexdigest()
        
        headers = {
            "Key": INDODAX_API_KEY,
            "Sign": sign,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0"
        }
        
        req = urllib.request.Request(url, data=post_data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Indodax API Error ({method_name}):", e)
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
        print("Gagal mengambil saldo asli (Cek API Key & Secret Key Anda).")

def get_main_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🔄 Refresh Dashboard", "callback_data": "btn_refresh"}]
        ]
    }

def send_menu(chat_id, text):
    if not chat_id: return None
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
    if not chat_id or not message_id: return None
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
    if not res or not res.get("ok"): 
        send_menu(chat_id, text)
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
# DASHBOARD BUILDER
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
        block_text = f"```\nMemantau market... siap mengeksekusi.\n```"

    text_blocks.append(f"\n📋 *RIWAYAT AKSI BOT:*\n{block_text}")
    text_blocks.append(f"━━━━━━━━━━━━━━━━━━━\n📈 *Total Win/Loss Akumulasi:* 🟢 {total_wins} | 🔴 {total_losses}\n⏱ _Live Sync Indodax: {now_wib} WIB_")

    return "\n".join(text_blocks)

def auto_refresh_dashboard_loop():
    update_all_initial_prices()
    sync_real_wallet_balance()

    print("Menunggu Anda mengirim pesan /start ke bot Telegram untuk menampilkan dashboard...")
    while not global_state["dashboard_chat_id"]:
        time.sleep(1)

    send_menu(global_state["dashboard_chat_id"], get_indodax_style_dashboard())

    while True:
        try:
            if global_state["dashboard_chat_id"] and global_state["dashboard_msg_id"]:
                update_menu(global_state["dashboard_chat_id"], global_state["dashboard_msg_id"], get_indodax_style_dashboard())
        except Exception as e:
            print("Dashboard Refresh Error:", e)
        time.sleep(2)

# ==========================================
# TRADING WORKER
# ==========================================
def single_coin_trading_worker(pair):
    st = coins_state[pair]
    highest_price = 0.0
    print(f"Engine All-In untuk {pair.upper()} aktif...")

    while st["last_market_price"] <= 0:
        fetch_price(pair)
        time.sleep(0.5)

    while True:
        try:
            if global_risk_control["portfolio_stopped"]:
                time.sleep(5)
                continue

            if st["is_cooldown"]:
                if time.time() < st["cooldown_until_time"]:
                    time.sleep(2)
                    continue
                else:
                    st["is_cooldown"] = False

            current_price = fetch_price(pair)
            if current_price <= 0:
                time.sleep(1)
                continue

            if st["is_running"]:
                now_wib = get_wib_time()
                is_market_good = (st["price_trend"] == "🔺") or (len(st["chart_history"]) >= 3 and st["chart_history"][-1] == "▇")

                if not st["in_position"] and st["idr_balance"] > 10000 and is_market_good:
                    indodax_private_request("trade", {
                        "pair": pair, "type": "buy",
                        "idr": int(st["idr_balance"] * (1 - FEE_RATE))
                    })
                    st["buy_price"] = current_price
                    highest_price = current_price
                    net_idr = st["idr_balance"] * (1 - FEE_RATE)
                    st["asset_balance"] = net_idr / current_price
                    st["idr_balance"] = 0.0
                    st["in_position"] = True

                    st["logs"].append(f"[{now_wib}] ALL-IN BUY @ {current_price:,.0f}")
                    if len(st["logs"]) > 6: st["logs"].pop(0)

                elif st["in_position"]:
                    if current_price > highest_price: highest_price = current_price

                    price_change_pct = (current_price - st["buy_price"]) / st["buy_price"]
                    is_target_hit = price_change_pct >= 0.006
                    is_stop_loss = price_change_pct <= -0.02

                    if is_target_hit or is_stop_loss:
                        indodax_private_request("trade", {
                            "pair": pair, "type": "sell",
                            pair.replace("idr", ""): st["asset_balance"]
                        })

                        gross = st["asset_balance"] * current_price
                        net_idr = gross * (1 - FEE_RATE)
                        pnl_idr = net_idr - (st["asset_balance"] * st["buy_price"])
                        
                        st["idr_balance"] = net_idr
                        st["asset_balance"] = 0.0
                        st["in_position"] = False
                        highest_price = 0.0

                        if price_change_pct > 0:
                            st["winning_trades"] += 1
                            tag = "WIN (+0.6%)"
                        else:
                            st["losing_trades"] += 1
                            tag = "LOSS (-2%)"
                            st["is_cooldown"] = True
                            st["cooldown_until_time"] = time.time() + 300
                            st["logs"].append(f"[{now_wib}] Jeda 5m karena Loss")

                        st["logs"].append(f"[{now_wib}] {tag} ({pnl_idr:+,.0f})")
                        if len(st["logs"]) > 6: st["logs"].pop(0)

        except Exception as e:
            print(f"ENGINE ERROR ({pair}):", e)

        time.sleep(1)

# ==========================================
# TELEGRAM HANDLERS
# ==========================================
def handle_update(update):
    try:
        if "callback_query" in update:
            cb = update["callback_query"]
            cb_id = cb["id"]
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]
            data = cb.get("data", "")

            if not global_state["dashboard_chat_id"]:
                global_state["dashboard_chat_id"] = chat_id

            if data == "btn_refresh":
                sync_real_wallet_balance()
                answer_callback(cb_id, "🔄 Saldo disinkronkan.")
                update_menu(chat_id, msg_id, get_indodax_style_dashboard())
            return

        if "message" in update:
            msg = update["message"]
            chat_id = msg.get("chat", {}).get("id")
            text = (msg.get("text") or "").strip()
            if not chat_id: return

            if not global_state["dashboard_chat_id"]:
                global_state["dashboard_chat_id"] = chat_id
                print(f"Chat ID Berhasil Dikenali: {chat_id}")

            if text.startswith("/start") or text.startswith("/menu") or text.startswith("/id"):
                send_menu(chat_id, get_indodax_style_dashboard())
    except Exception as e:
        print("Handler Error:", e)

def polling():
    offset = None
    telegram("deleteWebhook", {"drop_pending_updates": "false"})
    print("Telegram Polling Berjalan Aman...")
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
            print("POLLING ERROR:", e)
            time.sleep(3)

if __name__ == "__main__":
    if not TOKEN or "MASUKKAN" in TOKEN:
        print("PERINGATAN: TELEGRAM_BOT_TOKEN belum diatur dengan benar!")

    for p in PAIRS:
        threading.Thread(target=single_coin_trading_worker, args=(p,), daemon=True).start()

    threading.Thread(target=auto_refresh_dashboard_loop, daemon=True).start()
    polling()
