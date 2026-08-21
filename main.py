import os
import time
import json
import threading
import urllib.request
import urllib.parse
from datetime import datetime

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
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", 2))

state = {
    "idr_balance": START_BALANCE,
    "asset_balance": 0.0,
    "in_position": False,
    "buy_price": 0.0,
    "price_history": [],
    "total_trades": 0,
    "trades_this_minute": 0,
    "winning_trades": 0,
    "losing_trades": 0,
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
    """Menu Utama Inline Keyboard"""
    return {
        "inline_keyboard": [
            [{"text": "📊 Status Bot & Posisi", "callback_data": "btn_status"}],
            [{"text": "💰 Cek Saldo Demo", "callback_data": "btn_balance"}],
            [{"text": "📈 Laporan PnL & WinRate", "callback_data": "btn_report"}],
            [{"text": "⚡ Cek Harga BTC Real-Time", "callback_data": "btn_price"}]
        ]
    }

def get_back_keyboard():
    """Tombol Kembali / Home agar antarmuka tidak lag"""
    return {
        "inline_keyboard": [
            [{"text": "🏠 Tampilan Utama (Kembali)", "callback_data": "btn_home"}]
        ]
    }

def send_menu(chat_id, text):
    return telegram("sendMessage", {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": get_main_keyboard()
    })

def update_menu(chat_id, message_id, text, is_home=False):
    markup = get_main_keyboard() if is_home else get_back_keyboard()
    return telegram("editMessageText", {
        "chat_id": str(chat_id),
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": markup
    })

def answer_callback(callback_query_id):
    return telegram("answerCallbackQuery", {"callback_query_id": callback_query_id})

def broadcast(text, include_keyboard=True):
    if ALLOWED_CHAT_ID:
        payload = {
            "chat_id": str(ALLOWED_CHAT_ID),
            "text": text,
            "parse_mode": "Markdown"
        }
        if include_keyboard:
            payload["reply_markup"] = get_main_keyboard()
        telegram("sendMessage", payload)

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
    except Exception:
        return None

# ==========================================
# LAPORAN RUTIN PER 1 MENIT
# ==========================================
def minutely_report_loop():
    while True:
        time.sleep(60)
        try:
            current_price = get_indodax_price() or 0
            asset_value = state["asset_balance"] * current_price
            total_equity = state["idr_balance"] + asset_value
            pnl_idr = total_equity - START_BALANCE
            pnl_percent = (pnl_idr / START_BALANCE) * 100
            now = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

            report_msg = (
                f"⏱ *LAPORAN TOTAL RUTIN 1 MENIT*\n"
                f"📅 *Waktu:* `{now}`\n"
                f"────────────────────────\n"
                f"🔄 *Aksi Menit Ini:* {state['trades_this_minute']} transaksi\n"
                f"💵 *Saldo IDR:* Rp {state['idr_balance']:,.0f}\n"
                f"🪙 *Nilai Aset ({PAIR.split('_')[0].upper()}):* Rp {asset_value:,.0f}\n"
                f"💰 *Total Equity Saat Ini:* Rp {total_equity:,.0f}\n"
                f"📈 *Total PnL Overall:* Rp {pnl_idr:,.0f} ({pnl_percent:+.2f}%)\n"
                f"🎯 *Win / Loss:* {state['winning_trades']} Win / {state['losing_trades']} Loss\n"
                f"📊 *Total Eksekusi Keseluruhan:* {state['total_trades']} x"
            )
            state['trades_this_minute'] = 0
            broadcast(report_msg, include_keyboard=True)
        except Exception as e:
            print("REPORT ERROR:", e)

# ==========================================
# TRADING ENGINE
# ==========================================
def analyze_signal(current_price):
    state["price_history"].append(current_price)
    if len(state["price_history"]) > 10:
        state["price_history"].pop(0)
    if len(state["price_history"]) < 5:
        return "WAIT"

    avg_price = sum(state["price_history"]) / len(state["price_history"])
    if current_price > avg_price and state["price_history"][-1] > state["price_history"][-2]:
        return "BUY"
    return "WAIT"

def trading_loop():
    while True:
        try:
            current_price = get_indodax_price()
            if current_price:
                now = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

                # 1. LAPORAN SEKETIKA SAAT BOT MEMBELI
                if not state["in_position"]:
                    if analyze_signal(current_price) == "BUY":
                        amount_buy = state["idr_balance"] * (1 - FEE_RATE)
                        state["asset_balance"] = amount_buy / current_price
                        state["buy_price"] = current_price
                        state["idr_balance"] = 0.0
                        state["in_position"] = True
                        state["trades_this_minute"] += 1

                        broadcast(
                            f"⚡ *LAPORAN EKSEKUSI: BUY (BELI)*\n"
                            f"📅 *Waktu:* `{now}`\n"
                            f"────────────────────────\n"
                            f"• Pair: {PAIR.upper()}\n"
                            f"• Harga Beli: Rp {current_price:,.0f}\n"
                            f"• Target TP (+0.8%): Rp {current_price * (1 + MIN_TAKE_PROFIT):,.0f}\n"
                            f"• Stop Loss (-1.5%): Rp {current_price * (1 - STOP_LOSS):,.0f}\n"
                            f"• Jumlah Aset Beli: {state['asset_balance']:.6f} BTC",
                            include_keyboard=False
                        )

                # 2. LAPORAN SEKETIKA SAAT BOT MENJUAL
                elif state["in_position"]:
                    pnl_pct = (current_price - state["buy_price"]) / state["buy_price"]
                    should_sell = False
                    reason = ""

                    if pnl_pct >= MIN_TAKE_PROFIT:
                        should_sell = True
                        reason = f"PROFIT (+{pnl_pct*100:.2f}%)"
                        state["winning_trades"] += 1
                    elif pnl_pct <= -STOP_LOSS:
                        should_sell = True
                        reason = f"STOP LOSS ({pnl_pct*100:.2f}%)"
                        state["losing_trades"] += 1

                    if should_sell:
                        gross = state["asset_balance"] * current_price
                        net = gross * (1 - FEE_RATE)
                        pnl_idr = net - (state["asset_balance"] * state["buy_price"])

                        state["idr_balance"] = net
                        state["asset_balance"] = 0.0
                        state["in_position"] = False
                        state["total_trades"] += 1
                        state["trades_this_minute"] += 1
                        state["price_history"].clear()

                        broadcast(
                            f"🎯 *LAPORAN EKSEKUSI: SELL ({reason})*\n"
                            f"📅 *Waktu:* `{now}`\n"
                            f"────────────────────────\n"
                            f"• Harga Beli Awal: Rp {state['buy_price']:,.0f}\n"
                            f"• Harga Jual: Rp {current_price:,.0f}\n"
                            f"• Hasil PnL Transaksi: Rp {pnl_idr:,.0f}\n"
                            f"• Saldo Cash IDR Sekarang: Rp {state['idr_balance']:,.0f}",
                            include_keyboard=False
                        )
        except Exception as e:
            print("TRADING ERROR:", e)

        time.sleep(INTERVAL_SECONDS)

# ==========================================
# TELEGRAM HANDLER
# ==========================================
def get_home_text():
    return "🤖 *STAFF AG TRADING DASHBOARD*\n\nPilih menu di bawah ini untuk memantau aktivitas bot:"

def get_status_text():
    price = get_indodax_price() or 0
    pos = f"Sedang Memegang Aset ({state['asset_balance']:.6f} BTC)" if state["in_position"] else "Mencari Sinyal Beli (Cash Ready)"
    return f"📊 *STATUS BOT*\n\n• Pair: {PAIR.upper()}\n• Harga BTC: Rp {price:,.0f}\n• Posisi: {pos}"

def get_balance_text():
    price = get_indodax_price() or 0
    asset_val = state["asset_balance"] * price
    equity = state["idr_balance"] + asset_val
    return f"💰 *SALDO DEMO*\n\n• Cash IDR: Rp {state['idr_balance']:,.0f}\n• Nilai Aset: Rp {asset_val:,.0f}\n• Total Equity: Rp {equity:,.0f}"

def get_report_text():
    price = get_indodax_price() or 0
    equity = state["idr_balance"] + (state["asset_balance"] * price)
    pnl = equity - START_BALANCE
    pct = (pnl / START_BALANCE) * 100
    return f"📈 *LAPORAN PERFORMA*\n\n• Modal Awal: Rp {START_BALANCE:,.0f}\n• Total Equity: Rp {equity:,.0f}\n• Total PnL: Rp {pnl:,.0f} ({pct:+.2f}%)\n• Win/Loss: {state['winning_trades']} Win / {state['losing_trades']} Loss"

def handle_update(update):
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        data = cb.get("data", "")

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
        elif text.startswith("/id"):
            telegram("sendMessage", {"chat_id": str(chat_id), "text": f"ID Anda: `{chat_id}`", "parse_mode": "Markdown"})

def polling():
    offset = None
    telegram("deleteWebhook", {"drop_pending_updates": "false"})
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
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=trading_loop, daemon=True).start()
    threading.Thread(target=minutely_report_loop, daemon=True).start()
    polling()
