import os
import time
import json
import threading
import urllib.request
import urllib.parse

# ==========================================
# CONFIGURATION & STATE MANAGEMENT
# ==========================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Indodax & Risk Parameters
START_BALANCE = float(os.getenv("START_BALANCE", 100000))
PAIR = os.getenv("PAIR", "btc_idr").lower()
FEE_RATE = float(os.getenv("FEE_RATE", 0.002))
MIN_TAKE_PROFIT = float(os.getenv("MIN_TAKE_PROFIT", 0.02))
MAX_TAKE_PROFIT = float(os.getenv("MAX_TAKE_PROFIT", 0.30))
STOP_LOSS = float(os.getenv("STOP_LOSS", 0.05))
DAILY_LOSS_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT", 0.10))
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", 30))

# State Paper Trading
state = {
    "idr_balance": START_BALANCE,
    "asset_balance": 0.0,
    "in_position": False,
    "buy_price": 0.0,
    "daily_start_balance": START_BALANCE,
    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,
    "last_reset_day": time.localtime().tm_mday
}

# ==========================================
# TELEGRAM BOT HELPER FUNCTIONS
# ==========================================
def telegram(method, params=None):
    if not TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN belum diisi.")
        return None

    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = urllib.parse.urlencode(params or {}).encode("utf-8")

    try:
        request = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result
    except Exception as error:
        print("TELEGRAM ERROR:", repr(error))
        return None

def send_message(chat_id, text):
    return telegram(
        "sendMessage",
        {
            "chat_id": str(chat_id),
            "text": text,
            "parse_mode": "Markdown"
        },
    )

def broadcast(text):
    """Kirim notifikasi otomatis ke admin (ALLOWED_CHAT_ID)."""
    if ALLOWED_CHAT_ID:
        send_message(ALLOWED_CHAT_ID, text)

def is_allowed(chat_id):
    if not ALLOWED_CHAT_ID:
        return True
    return str(chat_id) == str(ALLOWED_CHAT_ID)

# ==========================================
# INDODAX MARKET DATA & TRADING ENGINE
# ==========================================
def get_indodax_price():
    url = f"https://indodax.com/api/ticker/{PAIR}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            return float(data["ticker"]["last"])
    except Exception as e:
        print(f"Error fetching Indodax price: {e}")
        return None

def check_daily_reset():
    current_day = time.localtime().tm_mday
    if current_day != state["last_reset_day"]:
        current_price = get_indodax_price() or state["buy_price"]
        total_equity = state["idr_balance"] + (state["asset_balance"] * current_price)
        state["daily_start_balance"] = total_equity
        state["last_reset_day"] = current_day
        broadcast(f"📅 *RESET HARIAN*\nModal awal hari ini diset ke: Rp {total_equity:,.0f}")

def trading_loop():
    print("📈 Trading Engine Started...")
    while True:
        try:
            check_daily_reset()
            current_price = get_indodax_price()

            if current_price:
                total_equity = state["idr_balance"] + (state["asset_balance"] * current_price if state["in_position"] else 0)
                daily_pnl = (total_equity - state["daily_start_balance"]) / state["daily_start_balance"]

                # 1. Protection: Daily Loss Limit
                if daily_pnl <= -DAILY_LOSS_LIMIT:
                    print(f"[PAUSE] Daily loss limit reached ({daily_pnl*100:.2f}%). Bot paused.")
                    time.sleep(INTERVAL_SECONDS)
                    continue

                # 2. Sinyal Beli (Beli ketika belum memegang aset)
                if not state["in_position"]:
                    amount_to_buy_idr = state["idr_balance"] * (1 - FEE_RATE)
                    state["asset_balance"] = amount_to_buy_idr / current_price
                    state["buy_price"] = current_price
                    state["idr_balance"] = 0.0
                    state["in_position"] = True

                    msg = (
                        f"🟢 *SIMULASI BUY*\n\n"
                        f"• Pair: {PAIR.upper()}\n"
                        f"• Harga Beli: Rp {currentPrice:,.0f}\n"
                        f"• Total Aset: {state['asset_balance']:.8f}\n"
                        f"• Target TP: Rp {current_price * (1 + MIN_TAKE_PROFIT):,.0f}\n"
                        f"• Cut Loss: Rp {current_price * (1 - STOP_LOSS):,.0f}"
                    )
                    print(msg)
                    broadcast(msg)

                # 3. Sinyal Jual (Cek TP / SL)
                elif state["in_position"]:
                    pnl_percent = (current_price - state["buy_price"]) / state["buy_price"]
                    should_sell = False
                    reason = ""

                    if pnl_percent >= MIN_TAKE_PROFIT:
                        should_sell = True
                        reason = f"TAKE PROFIT (+{pnl_percent*100:.2f}%)"
                        state["winning_trades"] += 1
                    elif pnl_percent <= -STOP_LOSS:
                        should_sell = True
                        reason = f"STOP LOSS ({pnl_percent*100:.2f}%)"
                        state["losing_trades"] += 1

                    if should_sell:
                        gross_idr = state["asset_balance"] * current_price
                        net_idr = gross_idr * (1 - FEE_RATE)
                        pnl_idr = net_idr - (state["asset_balance"] * state["buy_price"])

                        state["idr_balance"] = net_idr
                        state["asset_balance"] = 0.0
                        state["in_position"] = False
                        state["total_trades"] += 1

                        msg = (
                            f"🔴 *SIMULASI SELL ({reason})*\n\n"
                            f"• Harga Jual: Rp {current_price:,.0f}\n"
                            f"• Profit/Loss: Rp {pnl_idr:,.0f}\n"
                            f"• Saldo IDR Sekarang: Rp {state['idr_balance']:,.0f}"
                        )
                        print(msg)
                        broadcast(msg)

        except Exception as e:
            print("TRADING LOOP ERROR:", repr(e))

        time.sleep(INTERVAL_SECONDS)

# ==========================================
# TELEGRAM MESSAGE HANDLER
# ==========================================
def handle_message(message):
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return

    command = text.split()[0].lower().split("@")[0]

    if command == "/id":
        send_message(
            chat_id,
            "🆔 *TELEGRAM CHAT ID*\n\n"
            f"`{chat_id}`\n\n"
            "Copy angka di atas ke Variable Railway:\n"
            "*TELEGRAM_CHAT_ID*"
        )
        return

    if not is_allowed(chat_id):
        send_message(chat_id, "⛔ Chat ID ini belum diizinkan.")
        return

    if command == "/start":
        send_message(
            chat_id,
            "🤖 *INDODAX PAPER BOT*\n\n"
            "Bot trading simulasi aktif 24 jam.\n\n"
            "/id - Melihat Chat ID\n"
            "/status - Status running bot\n"
            "/balance - Saldo IDR & Aset saat ini\n"
            "/report - Laporan performa trading"
        )

    elif command == "/status":
        current_price = get_indodax_price() or 0
        pos_status = f"In Position ({state['asset_balance']:.6f} {PAIR.split('_')[0].upper()})" if state["in_position"] else "Searching Buy Signal"
        
        send_message(
            chat_id,
            "🟢 *BOT ONLINE*\n\n"
            f"• Mode: PAPER TRADING\n"
            f"• Pair: {PAIR.upper()}\n"
            f"• Harga Saat Ini: Rp {current_price:,.0f}\n"
            f"• Status Position: {pos_status}"
        )

    elif command == "/balance":
        current_price = get_indodax_price() or 0
        asset_value = state["asset_balance"] * current_price
        total_equity = state["idr_balance"] + asset_value

        send_message(
            chat_id,
            "💰 *SALDO DEMO*\n\n"
            f"• IDR Cash: Rp {state['idr_balance']:,.0f}\n"
            f"• Nilai Aset: Rp {asset_value:,.0f}\n"
            f"• Total Equity: Rp {total_equity:,.0f}"
        )

    elif command == "/report":
        current_price = get_indodax_price() or 0
        total_equity = state["idr_balance"] + (state["asset_balance"] * current_price)
        total_pnl = total_equity - START_BALANCE
        pnl_pct = (total_pnl / START_BALANCE) * 100

        send_message(
            chat_id,
            "📊 *DEMO REPORT*\n\n"
            f"• Modal Awal: Rp {START_BALANCE:,.0f}\n"
            f"• Equity Sekarang: Rp {total_equity:,.0f}\n"
            f"• Total PnL: Rp {total_pnl:,.0f} ({pnl_pct:+.2f}%)\n"
            f"• Total Executed Trade: {state['total_trades']}\n"
            f"• Win / Loss: {state['winning_trades']} W / {state['losing_trades']} L"
        )

    else:
        send_message(
            chat_id,
            "❓ Command tidak dikenal.\n\nGunakan /start untuk melihat daftar perintah."
        )

# ==========================================
# POLLING LOOP
# ==========================================
def polling():
    offset = None
    telegram("deleteWebhook", {"drop_pending_updates": "false"})

    while True:
        try:
            params = {
                "timeout": 25,
                "allowed_updates": json.dumps(["message"]),
            }
            if offset is not None:
                params["offset"] = offset

            result = telegram("getUpdates", params)

            if not result or not result.get("ok"):
                time.sleep(3)
                continue

            updates = result.get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message")
                if message:
                    handle_message(message)

        except Exception as error:
            print("POLLING ERROR:", repr(error))
            time.sleep(5)

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    print("==============================")
    print(" INDODAX BOT ENGINE & TELEGRAM")
    print("==============================")

    # Jalankan Trading Loop di background thread
    t = threading.Thread(target=trading_loop, daemon=True)
    t.start()

    # Jalankan Telegram Polling di main thread
    polling()
