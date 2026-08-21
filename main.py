import os
import time
import json
import threading
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

import sys
sys.stdout.reconfigure(line_buffering=True)

# Format Timezone WIB (UTC+7)
WIB = timezone(timedelta(hours=7))

def get_wib_time():
    """Mengembalikan string jam dalam format WIB (HH:MM:SS)"""
    return datetime.now(WIB).strftime("%H:%M:%S")

# ==========================================
# CONFIGURATION
# ==========================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

START_BALANCE = float(os.getenv("START_BALANCE", 100000))
PAIR = os.getenv("PAIR", "btc_idr").lower()
FEE_RATE = float(os.getenv("FEE_RATE", 0.0021)) # Fee Indodax 0.21% (Beli/Jual)

state = {
    "is_running": True,
    "idr_balance": START_BALANCE,
    "asset_balance": 0.0,
    "in_position": False,
    "buy_price": 0.0,
    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,
    "minute_start_equity": START_BALANCE,
    "minute_wins": 0,
    "minute_losses": 0,
    "minute_logs": [],
    "dashboard_msg_id": None,
    "dashboard_chat_id": ALLOWED_CHAT_ID,
    "last_rendered_text": "",
    "last_market_price": 0.0
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
        {"text": "⏹ Hentikan Bot", "callback_data": "btn_stop"}
        if state["is_running"]
        else {"text": "▶️ Jalankan Bot", "callback_data": "btn_start"}
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
            [{"text": "🏠 Kembali ke Dashboard", "callback_data": "btn_home"}]
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
            price = float(data["ticker"]["last"])
            state["last_market_price"] = price
            return price
    except Exception as e:
        print("Error fetch price:", e)
        return state["last_market_price"] or 1350000000.0

# ==========================================
# DASHBOARD TEXT BUILDER
# ==========================================
def get_home_text(is_final=False):
    status_str = "🟢 *BERJALAN (ACTIVE)*" if state["is_running"] else "🔴 *BERHENTI (STOPPED)*"
    price = get_indodax_price() or 0
    asset_val = state["asset_balance"] * price
    total_equity = state["idr_balance"] + asset_val
    now_wib = get_wib_time()

    pos_info = "⚡ *Posisi:* Scalping (Holding BTC)" if state["in_position"] else "💵 *Posisi:* Standby (Persiapan Beli)"

    if state["minute_logs"]:
        logs_str = "\n".join(state["minute_logs"][-8:])
        block_text = f"```\n{logs_str}\n```"
    else:
        block_text = "```\nMenunggu sinyal transaksi aktif...\n```"

    if is_final:
        profit_loss_minute = total_equity - state["minute_start_equity"]
        profit_str = f"Rp {profit_loss_minute:+,.2f}"

        return (
            f"🤖 *BOT TRADING INDODAX*\n\n"
            f"Status Bot: 🏁 *REKAP SESI (SELESAI)*\n"
            f"💰 *Saldo Akhir:* Rp {total_equity:,.2f}\n"
            f"{pos_info}\n"
            f"⏱ _Waktu Selesai: {now_wib} WIB_\n\n"
            f"📋 *RIWAYAT TRANSAKSI SESI INI:*\n{block_text}\n"
            f"📊 *RINGKASAN SESI:*\n"
            f"🟢 *Profit:* {state['minute_wins']}x\n"
            f"🔴 *Loss:* {state['minute_losses']}x\n"
            f"💵 *Hasil PnL Sesi:* {profit_str}"
        )

    return (
        f"🤖 *BOT TRADING INDODAX*\n\n"
        f"Status Bot: {status_str}\n"
        f"💰 *Saldo Saat Ini:* Rp {total_equity:,.2f}\n"
        f"{pos_info}\n"
        f"⏱ _Live Update: {now_wib} WIB_\n\n"
        f"📋 *RIWAYAT TRANSAKSI (SESI INI):*\n{block_text}\n\n"
        f"Pilih menu di bawah untuk mengelola bot:"
    )

# ==========================================
# AUTO-REFRESH LIVE DASHBOARD
# ==========================================
def auto_refresh_dashboard_loop():
    while True:
        try:
            if state["is_running"] and state["dashboard_chat_id"] and state["dashboard_msg_id"]:
                new_text = get_home_text()
                if new_text != state["last_rendered_text"]:
                    res = telegram("editMessageText", {
                        "chat_id": str(state["dashboard_chat_id"]),
                        "message_id": state["dashboard_msg_id"],
                        "text": new_text,
                        "parse_mode": "Markdown",
                        "reply_markup": get_main_keyboard()
                    })
                    if res and res.get("ok"):
                        state["last_rendered_text"] = new_text
        except Exception as e:
            print("Auto Refresh Error:", e)
        time.sleep(1.5)

# ==========================================
# PERGANTIAN SESI CHAT PER 1 MENIT
# ==========================================
def minutely_reset_loop():
    while True:
        time.sleep(60)
        try:
            if state["is_running"] and state["dashboard_chat_id"] and state["dashboard_msg_id"]:
                old_msg_id = state["dashboard_msg_id"]
                final_text = get_home_text(is_final=True)
                
                state["dashboard_msg_id"] = None
                
                telegram("editMessageText", {
                    "chat_id": str(state["dashboard_chat_id"]),
                    "message_id": old_msg_id,
                    "text": final_text,
                    "parse_mode": "Markdown"
                })

                price = get_indodax_price() or 0
                state["minute_start_equity"] = state["idr_balance"] + (state["asset_balance"] * price)
                state["minute_wins"] = 0
                state["minute_losses"] = 0
                state["minute_logs"] = []

                new_home_text = get_home_text()
                send_menu(state["dashboard_chat_id"], new_home_text)
        except Exception as e:
            print("MINUTELY RESET ERROR:", e)

# ==========================================
# ENGINE TRADING: TARGET 10% HARIAN & SAFETY
# ==========================================
def trading_loop():
    print("Engine Trading Target 10% Aktif...")
    highest_price = 0.0

    while True:
        try:
            if state["is_running"]:
                current_price = get_indodax_price()
                now_wib = get_wib_time()

                if current_price > 0:
                    # 1. KONDISI BELI (ENTRY): Langsung eksekusi buy jika standby & saldo cukup
                    if not state["in_position"] and state["idr_balance"] > 1000:
                        state["buy_price"] = current_price
                        highest_price = current_price
                        
                        net_idr = state["idr_balance"] * (1 - FEE_RATE)  # Potong Fee Beli 0.21%
                        state["asset_balance"] = net_idr / current_price
                        state["idr_balance"] = 0.0
                        state["in_position"] = True

                        log_entry = f"[{now_wib}] BUY  @ Rp {current_price:,.0f}"
                        state["minute_logs"].append(log_entry)

                    # 2. KONDISI JUAL (TAKE PROFIT / TRAILING / STOP LOSS)
                    elif state["in_position"]:
                        if current_price > highest_price:
                            highest_price = current_price

                        price_change_pct = (current_price - state["buy_price"]) / state["buy_price"]
                        drop_from_peak = (highest_price - current_price) / highest_price if highest_price > 0 else 0

                        # Aturan Eksekusi Optimal Target 10% & Safety:
                        # - Take Profit Target: Tercapai kenaikan +1.2% (Menutup fee 0.42% + bersih ~0.8%)
                        # - Trailing Stop Cepat: Jika harga sempat naik tipis lalu koreksi turun 0.2% dari puncak
                        # - Stop Loss Safety: Cut loss di -1.5% untuk pengaman modal agar tidak boncos dalam
                        is_target_hit = price_change_pct >= 0.012
                        is_trailing = (highest_price >= state["buy_price"] * 1.015) and (drop_from_peak >= 0.002)
                        is_stop_loss = price_change_pct <= -0.015

                        if is_target_hit or is_trailing or is_stop_loss:
                            gross = state["asset_balance"] * current_price
                            net_idr = gross * (1 - FEE_RATE)  # Potong Fee Jual 0.21%
                            
                            pnl_idr = net_idr - (state["asset_balance"] * state["buy_price"])

                            state["idr_balance"] = net_idr
                            state["asset_balance"] = 0.0
                            state["in_position"] = False
                            state["total_trades"] += 1
                            highest_price = 0.0

                            if pnl_idr > 0:
                                state["winning_trades"] += 1
                                state["minute_wins"] += 1
                                tag = "SELL PROFIT"
                            else:
                                state["losing_trades"] += 1
                                state["minute_losses"] += 1
                                tag = "SELL LOSS"

                            log_entry = f"[{now_wib}] {tag} @ Rp {current_price:,.0f} ({pnl_idr:+,.0f})"
                            state["minute_logs"].append(log_entry)

        except Exception as e:
            print("ENGINE ERROR:", e)

        time.sleep(2) # Cek harga setiap 2 detik

# ==========================================
# TELEGRAM HANDLER
# ==========================================
def get_status_text():
    price = get_indodax_price() or 0
    status_str = "🟢 Berjalan (Active)" if state["is_running"] else "🔴 Berhenti (Stopped)"
    pos = f"Memegang Aset ({state['asset_balance']:.6f} BTC)" if state["in_position"] else "Standby (Persiapan Beli)"
    return f"📊 *STATUS BOT*\n\n• Mode Bot: {status_str}\n• Pair: {PAIR.upper()}\n• Harga BTC saat ini: Rp {price:,.0f}\n• Posisi: {pos}"

def get_balance_text():
    price = get_indodax_price() or 0
    asset_val = state["asset_balance"] * price
    equity = state["idr_balance"] + asset_val
    return f"💰 *SALDO DEMO*\n\n• Saldo IDR: Rp {state['idr_balance']:,.2f}\n• Nilai Aset BTC: Rp {asset_val:,.2f}\n• Total Equity: Rp {equity:,.2f}"

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
            answer_callback(cb_id, "▶️ Bot dijalankan.")
            update_menu(chat_id, msg_id, get_home_text(), is_home=True)
        elif data == "btn_stop":
            state["is_running"] = False
            answer_callback(cb_id, "⏹ Bot dihentikan.")
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
    print("Polling Telegram dimulai...")
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
