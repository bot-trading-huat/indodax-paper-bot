import os
import time
import json
import threading
import urllib.request
import urllib.parse
from datetime import datetime

import sys
sys.stdout.reconfigure(line_buffering=True)

# ==========================================
# CONFIGURATION & STATE MANAGEMENT
# ==========================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

START_BALANCE = float(os.getenv("START_BALANCE", 100000))
PAIR = os.getenv("PAIR", "btc_idr").lower()
FEE_RATE = float(os.getenv("FEE_RATE", 0.002))

MIN_TAKE_PROFIT = float(os.getenv("MIN_TAKE_PROFIT", 0.008))
STOP_LOSS = float(os.getenv("STOP_LOSS", 0.015))
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", 1))

state = {
    "is_running": True,
    "idr_balance": START_BALANCE,
    "asset_balance": 0.0,
    "in_position": False,
    "buy_price": 0.0,
    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,
    "minute_wins": 0,
    "minute_losses": 0,
    "minute_logs": [],        # Menampung log transaksi per menit
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
    play_stop_btn = (
        {"text": "⏹ Stop Bot", "callback_data": "btn_stop"}
        if state["is_running"]
        else {"text": "▶️ Mainkan Bot (Start)", "callback_data": "btn_start"}
    )
    return {
        "inline_keyboard": [
            [play_stop_btn],
            [{"text": "📊 Status Bot & Posisi", "callback_data": "btn_status"}],
            [{"text": "💰 Cek Saldo Demo", "callback_data": "btn_balance"}],
            [{"text": "📈 Laporan PnL & WinRate", "callback_data": "btn_report"}],
            [{"text": "⚡ Cek Harga BTC Real-Time", "callback_data": "btn_price"}]
        ]
    }

def get_back_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🏠 Tampilan Utama (Kembali)", "callback_data": "btn_home"}]
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
        state["dashboard_msg_id"] = res["result"]["message_id"]
        state["dashboard_chat_id"] = chat_id
        state["last_rendered_text"] = text
    return res

def update_menu(chat_id, message_id, text, is_home=False, markup=None):
    if markup is None:
        markup = get_main_keyboard() if is_home else get_back_keyboard()

    if is_home:
        state["dashboard_msg_id"] = message_id
        state["dashboard_chat_id"] = chat_id
        state["last_rendered_text"] = text
    else:
        state["dashboard_msg_id"] = None

    return telegram("editMessageText", {
        "chat_id": str(chat_id),
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": markup
    })

def answer_callback(callback_query_id, text=None):
    payload = {"callback_query_id": callback_query_id}
    if text: payload["text"] = text
    return telegram("answerCallbackQuery", payload)

# ==========================================
# INDODAX REAL-TIME DATA
# ==========================================
def get_indodax_price():
    url = f"https://indodax.com/api/ticker/{PAIR}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return float(data["ticker"]["last"])
    except Exception as e:
        print("Error fetch price:", e)
        return None

# ==========================================
# TEXT GENERATOR FOR DASHBOARD
# ==========================================
def get_home_text(is_final=False):
    status_str = "🟢 *AKTIF (RUNNING)*" if state["is_running"] else "🔴 *BERHENTI (STOPPED)*"
    price = get_indodax_price() or 0
    asset_val = state["asset_balance"] * price
    total_equity = state["idr_balance"] + asset_val
    now = datetime.now().strftime("%H:%M:%S")

    pos_info = "⚡ *Posisi:* Beli BTC @ Rp {:,.0f}".format(state["buy_price"]) if state["in_position"] else "💵 *Posisi:* Cash IDR Ready"

    # Membuat Format Kolom Hitam untuk Riwayat Transaksi Menit Ini
    if state["minute_logs"]:
        logs_str = "\n".join(state["minute_logs"])
        block_text = f"```\n{logs_str}\n```"
    else:
        block_text = "```\nBelum ada transaksi transaksi di menit ini...\n```"

    if is_final:
        return (
            f"🤖 *TRADE INDODAX #HUAT*\n\n"
            f"Status Bot: 🏁 *SELESAI (MENIT INI)*\n"
            f"💰 *Saldo Akhir:* Rp {total_equity:,.2f}\n"
            f"{pos_info}\n"
            f"⏱ _Waktu Selesai: {now}_\n\n"
            f"📋 *RIWAYAT TRANSAKSI:* \n{block_text}\n"
            f"🏁 *FINAL :*\n"
            f"🟢 *PROFIT :* {state['minute_wins']}\n"
            f"🔴 *LOSE :* {state['minute_losses']}"
        )

    return (
        f"🤖 *TRADE INDODAX #HUAT*\n\n"
        f"Status Bot: {status_str}\n"
        f"💰 *Saldo Saat Ini:* Rp {total_equity:,.2f}\n"
        f"{pos_info}\n"
        f"⏱ _Live Updated: {now}_\n\n"
        f"📋 *RIWAYAT TRANSAKSI (MENIT INI):*\n{block_text}\n\n"
        f"Pilih menu di bawah ini untuk memantau atau mengendalikan bot:"
    )

# ==========================================
# AUTO-REFRESH LIVE DASHBOARD
# ==========================================
def auto_refresh_dashboard_loop():
    while True:
        try:
            if state["dashboard_chat_id"]:
                new_text = get_home_text()
                
                if not state["dashboard_msg_id"]:
                    send_menu(state["dashboard_chat_id"], new_text)
                elif new_text != state["last_rendered_text"]:
                    res = telegram("editMessageText", {
                        "chat_id": str(state["dashboard_chat_id"]),
                        "message_id": state["dashboard_msg_id"],
                        "text": new_text,
                        "parse_mode": "Markdown",
                        "reply_markup": get_main_keyboard()
                    })
                    if res and res.get("ok"):
                        state["last_rendered_text"] = new_text
                    elif res and not res.get("ok"):
                        send_menu(state["dashboard_chat_id"], new_text)
        except Exception as e:
            print("Auto Refresh Error:", e)
        time.sleep(2)

# ==========================================
# RESET CHAT PER 1 MENIT & FINAL REKAP
# ==========================================
def minutely_reset_loop():
    while True:
        time.sleep(60)
        try:
            if state["dashboard_chat_id"] and state["dashboard_msg_id"]:
                # 1. Update chat pertama menjadi FINAL (tanpa keyboard)
                final_text = get_home_text(is_final=True)
                telegram("editMessageText", {
                    "chat_id": str(state["dashboard_chat_id"]),
                    "message_id": state["dashboard_msg_id"],
                    "text": final_text,
                    "parse_mode": "Markdown"
                })

                # 2. Reset penghitung transaksi menit ini
                state["minute_wins"] = 0
                state["minute_losses"] = 0
                state["minute_logs"] = []

                # 3. Kirim chat baru sebagai dashboard lanjutan
                new_home_text = get_home_text()
                send_menu(state["dashboard_chat_id"], new_home_text)
        except Exception as e:
            print("MINUTELY RESET ERROR:", e)

# ==========================================
# TRADING ENGINE
# ==========================================
def trading_loop():
    print("Loop trading dinyalakan...")
    while True:
        try:
            if state["is_running"]:
                current_price = get_indodax_price()
                if current_price:
                    now = datetime.now().strftime("%H:%M:%S")

                    # 1. BUY INSTAN
                    if not state["in_position"] and state["idr_balance"] > 0:
                        amount_buy = state["idr_balance"] * (1 - FEE_RATE)
                        state["asset_balance"] = amount_buy / current_price
                        state["buy_price"] = current_price
                        state["idr_balance"] = 0.0
                        state["in_position"] = True

                        log_entry = f"[{now}] BUY  @ Rp {current_price:,.0f}"
                        state["minute_logs"].append(log_entry)

                    # 2. SELL (TAKE PROFIT / STOP LOSS)
                    elif state["in_position"]:
                        pnl_pct = (current_price - state["buy_price"]) / state["buy_price"]
                        should_sell = False
                        is_win = False

                        if pnl_pct >= MIN_TAKE_PROFIT:
                            should_sell = True
                            is_win = True
                            state["winning_trades"] += 1
                            state["minute_wins"] += 1
                        elif pnl_pct <= -STOP_LOSS:
                            should_sell = True
                            is_win = False
                            state["losing_trades"] += 1
                            state["minute_losses"] += 1

                        if should_sell:
                            gross = state["asset_balance"] * current_price
                            net = gross * (1 - FEE_RATE)
                            pnl_idr = net - (state["asset_balance"] * state["buy_price"])

                            state["idr_balance"] = net
                            state["asset_balance"] = 0.0
                            state["in_position"] = False
                            state["total_trades"] += 1

                            tag = "SELL PROFIT" if is_win else "SELL LOSS"
                            log_entry = f"[{now}] {tag} @ Rp {current_price:,.0f} ({pnl_idr:+,.0f})"
                            state["minute_logs"].append(log_entry)
        except Exception as e:
            print("TRADING ERROR:", e)

        time.sleep(INTERVAL_SECONDS)

# ==========================================
# TELEGRAM HANDLER
# ==========================================
def get_status_text():
    price = get_indodax_price() or 0
    status_str = "🟢 Aktif Running" if state["is_running"] else "🔴 Berhenti (Stopped)"
    pos = f"Sedang Memegang Aset ({state['asset_balance']:.6f} BTC)" if state["in_position"] else "Mencari Sinyal Beli (Cash Ready)"
    return f"📊 *STATUS BOT*\n\n• Mode Bot: {status_str}\n• Pair: {PAIR.upper()}\n• Harga BTC: Rp {price:,.0f}\n• Posisi: {pos}"

def get_balance_text():
    price = get_indodax_price() or 0
    asset_val = state["asset_balance"] * price
    equity = state["idr_balance"] + asset_val
    return f"💰 *SALDO DEMO*\n\n• Cash IDR: Rp {state['idr_balance']:,.2f}\n• Nilai Aset: Rp {asset_val:,.2f}\n• Total Equity: Rp {equity:,.2f}"

def get_report_text():
    price = get_indodax_price() or 0
    equity = state["idr_balance"] + (state["asset_balance"] * price)
    pnl = equity - START_BALANCE
    pct = (pnl / START_BALANCE) * 100
    return f"📈 *LAPORAN PERFORMA*\n\n• Modal Awal: Rp {START_BALANCE:,.2f}\n• Total Equity: Rp {equity:,.2f}\n• Total PnL: Rp {pnl:,.2f} ({pct:+.2f}%)\n• Win/Loss: {state['winning_trades']} Win / {state['losing_trades']} Loss"

def handle_update(update):
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        data = cb.get("data", "")

        if data == "btn_start":
            state["is_running"] = True
            answer_callback(cb_id, "▶️ Bot Berhasil Dijalankan!")
            update_menu(chat_id, msg_id, get_home_text(), is_home=True)
        elif data == "btn_stop":
            state["is_running"] = False
            answer_callback(cb_id, "⏹ Bot Berhasil Dihentikan!")
            update_menu(chat_id, msg_id, get_home_text(), is_home=True)
        else:
            answer_callback(cb_id)

        if data == "btn_home":
            update_menu(chat_id, msg_id, get_home_text(), is_home=True)
        elif data == "btn_status":
            update_menu(chat_id, msg_id, get_status_text(), is_home=False)
        elif data == "btn_balance":
            update_menu(chat_id, msg_id, get_balance_text(), is_home=False)
        elif data == "btn_report":
            update_menu(chat_id, msg_id, get_report_text(), is_home=False)
        elif data == "btn_price":
            price = get_indodax_price() or 0
            update_menu(chat_id, msg_id, f"⚡ *HARGA REAL-TIME*\n\n{PAIR.upper()}: Rp {price:,.0f}", is_home=False)
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
    print("Bot Polling Telegram dimulai...")
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
    threading.Thread(target=trading_loop, daemon=True).start()
    threading.Thread(target=minutely_reset_loop, daemon=True).start()
    threading.Thread(target=auto_refresh_dashboard_loop, daemon=True).start()
    polling()
