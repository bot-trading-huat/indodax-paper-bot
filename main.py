import os
import time
import threading
import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone, timedelta

import sys
sys.stdout.reconfigure(line_buffering=True)

WIB = timezone(timedelta(hours=7))

def get_wib_time():
    return datetime.now(WIB).strftime("%H:%M:%S")

# ==========================================
# CONFIGURATION (3 KOIN SEKALIGUS)
# ==========================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "MASUKKAN_TOKEN_ANDA_DISINI")
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Modal awal dibagi rata ke 3 koin (Total Rp 100.000)
INITIAL_CAPITAL_PER_COIN = float(os.getenv("START_BALANCE", 100000)) / 3.0
FEE_RATE = float(os.getenv("FEE_RATE", 0.0021)) 

# Daftar pair sesuai format endpoint API Indodax (tanpa underscore)
PAIRS = ["solusdt", "ethusdt", "dogeusdt"]

coins_state = {}
for p in PAIRS:
    coins_state[p] = {
        "is_running": True,
        "is_cooldown": False,
        "cooldown_until": "",
        "idr_balance": INITIAL_CAPITAL_PER_COIN,
        "asset_balance": 0.0,
        "in_position": False,
        "buy_price": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "minute_start_equity": INITIAL_CAPITAL_PER_COIN,
        "minute_wins": 0,
        "minute_losses": 0,
        "logs": [],
        "last_market_price": 0.0,
        "price_trend": "⏺",
        "chart_history": ["—", "—", "—", "—", "—", "—", "—", "—"]
    }

global_state = {
    "dashboard_msg_id": None,
    "dashboard_chat_id": ALLOWED_CHAT_ID,
    "last_rendered_text": ""
}

# ==========================================
# TELEGRAM HELPER FUNCTIONS
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
    all_running = all(coins_state[p]["is_running"] for p in PAIRS)
    play_stop_text = "⏹ Hentikan Semua Bot" if all_running else "▶️ Jalankan Semua Bot"
    play_stop_cb = "btn_stop_all" if all_running else "btn_start_all"

    return {
        "inline_keyboard": [
            [{"text": play_stop_text, "callback_data": play_stop_cb}],
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
    global_state["dashboard_msg_id"] = message_id
    global_state["dashboard_chat_id"] = chat_id
    global_state["last_rendered_text"] = text

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

# ==========================================
# INDODAX REAL-TIME DATA & MINI CHART
# ==========================================
def fetch_price(pair):
    url = f"https://indodax.com/api/ticker/{pair}"
    st = coins_state[pair]
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            new_price = float(data["ticker"]["last"])
            
            if st["last_market_price"] > 0:
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
                if len(st["chart_history"]) > 6:
                    st["chart_history"].pop(0)
            
            st["last_market_price"] = new_price
            return new_price
    except Exception as e:
        print(f"Error fetch price {pair}:", e)
        return st["last_market_price"] or 1000.0

def update_all_prices():
    for p in PAIRS:
        fetch_price(p)

# ==========================================
# DASHBOARD TEXT BUILDER
# ==========================================
def get_home_text():
    update_all_prices()
    
    total_combined_equity = 0.0
    total_wins = 0
    total_losses = 0
    now_wib = get_wib_time()

    text_blocks = [f"🤖 *BOT MULTI-SCALPING (3 KOIN)*\n"]

    for p in PAIRS:
        st = coins_state[p]
        price = st["last_market_price"]
        asset_val = st["asset_balance"] * price
        equity = st["idr_balance"] + asset_val
        total_combined_equity += equity
        total_wins += st["winning_trades"]
        total_losses += st["losing_trades"]

        if st["is_cooldown"]:
            status = f"🟡 Cooldown"
        elif st["is_running"]:
            status = "🟢 Jalan"
        else:
            status = "🔴 Berhenti"

        chart_vis = "".join(st["chart_history"])
        pos_str = "⚡ Target 0.6%" if st["in_position"] else "💵 Standby"
        pair_display = p.upper().replace("USDT", "/USDT")

        text_blocks.append(
            f"🔹 *{pair_display}* | {status}\n"
            f"   • Harga: {price:,.2f} {st['price_trend']}\n"
            f"   • Grafik: `{chart_vis}`\n"
            f"   • Saldo: Rp {equity:,.2f} ({pos_str})\n"
            f"   • Win: {st['winning_trades']} | Loss: {st['losing_trades']}"
        )

    all_logs = []
    for p in PAIRS:
        pair_display = p.upper().replace("USDT", "/USDT")
        for lg in coins_state[p]["logs"]:
            all_logs.append(f"[{pair_display}] {lg}")
            
    if all_logs:
        logs_str = "\n".join(all_logs[-4:])
        block_text = f"```\n{logs_str}\n```"
    else:
        block_text = f"```\nMemantau pergerakan pasar...\n```"

    text_blocks.append(f"\n📋 *RIWAYAT TRANSAKSI:*\n{block_text}")
    text_blocks.append(f"━━━━━━━━━━━━━━━━━━━\n💰 *TOTAL KESELURUHAN SALDO:* *Rp {total_combined_equity:,.2f}*\n📊 *Total Win/Loss:* 🟢 {total_wins} | 🔴 {total_losses}\n⏱ _Live Ticker: {now_wib} WIB_")

    return "\n".join(text_blocks)

# ==========================================
# AUTO-REFRESH & TRADING LOOPS
# ==========================================
def auto_refresh_dashboard_loop():
    while True:
        try:
            if global_state["dashboard_chat_id"] and global_state["dashboard_msg_id"]:
                new_text = get_home_text()
                if new_text != global_state["last_rendered_text"]:
                    res = telegram("editMessageText", {
                        "chat_id": str(global_state["dashboard_chat_id"]),
                        "message_id": global_state["dashboard_msg_id"],
                        "text": new_text,
                        "parse_mode": "Markdown",
                        "reply_markup": get_main_keyboard()
                    })
                    if res and res.get("ok"):
                        global_state["last_rendered_text"] = new_text
        except Exception as e:
            print("Auto Refresh Error:", e)
        time.sleep(2)

def single_coin_trading_worker(pair):
    st = coins_state[pair]
    highest_price = 0.0
    pair_display = pair.upper().replace("USDT", "/USDT")
    print(f"Engine Trading untuk {pair_display} aktif...")

    while True:
        try:
            if st["is_cooldown"]:
                now_dt = datetime.now(WIB)
                cooldown_end_dt = datetime.strptime(st["cooldown_until"], "%H:%M:%S").replace(
                    year=now_dt.year, month=now_dt.month, day=now_dt.day, tzinfo=WIB
                )
                if now_dt >= cooldown_end_dt:
                    st["is_cooldown"] = False
                    st["is_running"] = True
                    st["minute_start_equity"] = st["idr_balance"] + (st["asset_balance"] * st["last_market_price"])
                time.sleep(5)
                continue

            if st["is_running"]:
                current_price = st["last_market_price"]
                now_wib = get_wib_time()

                if current_price > 0:
                    current_equity = st["idr_balance"] + (st["asset_balance"] * current_price)
                    allowed_drop_limit = st["minute_start_equity"] * 0.98
                    
                    if current_equity <= allowed_drop_limit:
                        st["is_running"] = False
                        st["is_cooldown"] = True
                        cooldown_target = datetime.now(WIB) + timedelta(minutes=5)
                        st["cooldown_until"] = cooldown_target.strftime("%H:%M:%S")

                        if st["in_position"]:
                            gross = st["asset_balance"] * current_price
                            st["idr_balance"] = gross * (1 - FEE_RATE)
                            st["asset_balance"] = 0.0
                            st["in_position"] = False
                        st["logs"].append(f"[{now_wib}] COOLDOWN 5M")
                        continue

                    # 1. KONDISI BELI (ENTRY)
                    if not st["in_position"] and st["idr_balance"] > 1000:
                        st["buy_price"] = current_price
                        highest_price = current_price
                        
                        net_idr = st["idr_balance"] * (1 - FEE_RATE)
                        st["asset_balance"] = net_idr / current_price
                        st["idr_balance"] = 0.0
                        st["in_position"] = True

                        st["logs"].append(f"[{now_wib}] BUY @ {current_price:,.2f}")
                        if len(st["logs"]) > 6: st["logs"].pop(0)

                    # 2. KONDISI JUAL (TARGET 0.6% / STOP LOSS -2%)
                    elif st["in_position"]:
                        if current_price > highest_price:
                            highest_price = current_price

                        price_change_pct = (current_price - st["buy_price"]) / st["buy_price"]
                        is_target_hit = price_change_pct >= 0.006
                        is_stop_loss = price_change_pct <= -0.02

                        if is_target_hit or is_stop_loss:
                            gross = st["asset_balance"] * current_price
                            net_idr = gross * (1 - FEE_RATE)
                            pnl_idr = net_idr - (st["asset_balance"] * st["buy_price"])
                            
                            st["idr_balance"] = net_idr
                            st["asset_balance"] = 0.0
                            st["in_position"] = False
                            st["total_trades"] += 1
                            highest_price = 0.0

                            if price_change_pct > 0:
                                st["winning_trades"] += 1
                                tag = "WIN (+0.6%)"
                            else:
                                st["losing_trades"] += 1
                                tag = "LOSS (-2%)"

                            st["logs"].append(f"[{now_wib}] {tag} ({pnl_idr:+,.0f})")
                            if len(st["logs"]) > 6: st["logs"].pop(0)

        except Exception as e:
            print(f"ENGINE ERROR ({pair}):", e)

        time.sleep(1.5)

# ==========================================
# TELEGRAM HANDLERS & POLLING
# ==========================================
def handle_update(update):
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        data = cb.get("data", "")

        if data == "btn_start_all":
            for p in PAIRS:
                coins_state[p]["is_running"] = True
                coins_state[p]["is_cooldown"] = False
            answer_callback(cb_id, "▶️ Semua bot dijalankan.")
            update_menu(chat_id, msg_id, get_home_text())
        elif data == "btn_stop_all":
            for p in PAIRS:
                coins_state[p]["is_running"] = False
                coins_state[p]["is_cooldown"] = False
            answer_callback(cb_id, "⏹ Semua bot dihentikan.")
            update_menu(chat_id, msg_id, get_home_text())
        elif data == "btn_refresh":
            answer_callback(cb_id, "🔄 Data diperbarui.")
            update_menu(chat_id, msg_id, get_home_text())
        return

    if "message" in update:
        msg = update["message"]
        chat_id = msg.get("chat", {}).get("id")
        text = (msg.get("text") or "").strip()
        if not chat_id: return

        if text.startswith("/start") or text.startswith("/menu"):
            send_menu(chat_id, get_home_text())

def polling():
    offset = None
    telegram("deleteWebhook", {"drop_pending_updates": "false"})
    print("Polling Telegram Multi-Bot dimulai...")
    while True:
        try:
            params = {"timeout": 25, "allowed_updates": json.dumps(["message", "callback_query"])}
            if offset is not None: params["offset"] = offset
            res = telegram("getUpdates", params)
            if res and res.get("ok"):
                for upd in res.get("result", []):
                    offset = upd["update_id"] + 1
                    handle_update(upd)
        except Exception as e:
            print("POLLING ERROR:", e)
            time.sleep(5)

if __name__ == "__main__":
    for p in PAIRS:
        threading.Thread(target=single_coin_trading_worker, args=(p,), daemon=True).start()

    threading.Thread(target=auto_refresh_dashboard_loop, daemon=True).start()
    polling()
