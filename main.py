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

# Scalping Settings (Main Cepat)
MIN_TAKE_PROFIT = float(os.getenv("MIN_TAKE_PROFIT", 0.008)) # Target profit cepat (0.8%)
STOP_LOSS = float(os.getenv("STOP_LOSS", 0.015))            # Stop loss ketat (1.5%)
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", 2))    # Pengecekan cepat tiap 2 detik

# State Paper Trading
state = {
    "idr_balance": START_BALANCE,
    "asset_balance": 0.0,
    "in_position": False,
    "buy_price": 0.0,
    "price_history": [],      # Menyimpan histori harga untuk deteksi momentum
    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,
    "last_report_hour": -1
}

# ==========================================
# TELEGRAM HELPER FUNCTIONS
# ==========================================
def telegram(method, params=None):
    if not TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = urllib.parse.urlencode(params or {}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return None

def send_message(chat_id, text):
    return telegram("sendMessage", {"chat_id": str(chat_id), "text": text, "parse_mode": "Markdown"})

def broadcast(text):
    if ALLOWED_CHAT_ID:
        send_message(ALLOWED_CHAT_ID, text)

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
# STRATEGI SCALPING MOMENTUM (PINTAR & CEPAT)
# ==========================================
def analyze_signal(current_price):
    """Menganalisis pergerakan harga singkat (momentum)"""
    state["price_history"].append(current_price)
    
    # Simpan maksimal 10 data harga terakhir (20 detik terakhir)
    if len(state["price_history"]) > 10:
        state["price_history"].pop(0)
        
    if len(state["price_history"]) < 5:
        return "WAIT" # Butuh data awal dulu

    # Hitung pergerakan rata-rata singkat
    avg_price = sum(state["price_history"]) / len(state["price_history"])
    
    # Sinyal Beli: Harga saat ini mendadak naik di atas rata-rata (Momentum Beli)
    if current_price > avg_price and state["price_history"][-1] > state["price_history"][-2]:
        return "BUY"
        
    return "WAIT"

def trading_loop():
    print("⚡ Scalping Engine Started (Mode Cepat)...")
    
    while True:
        try:
            current_price = get_indodax_price()

            if current_price:
                # 1. LOGIKA BELI (Mencari Momentum Naik)
                if not state["in_position"]:
                    signal = analyze_signal(current_price)
                    
                    if signal == "BUY":
                        amount_to_buy_idr = state["idr_balance"] * (1 - FEE_RATE)
                        state["asset_balance"] = amount_to_buy_idr / current_price
                        state["buy_price"] = current_price
                        state["idr_balance"] = 0.0
                        state["in_position"] = True

                        msg = (
                            f"⚡ *SCALPING BUY*\n"
                            f"• Pair: {PAIR.upper()}\n"
                            f"• Harga Beli: Rp {current_price:,.0f}\n"
                            f"• Target TP: Rp {current_price * (1 + MIN_TAKE_PROFIT):,.0f}\n"
                            f"• Cut Loss: Rp {current_price * (1 - STOP_LOSS):,.0f}"
                        )
                        print(msg)
                        broadcast(msg)

                # 2. LOGIKA JUAL (Cek Profit/Rugi Cepat)
                elif state["in_position"]:
                    pnl_percent = (current_price - state["buy_price"]) / state["buy_price"]
                    should_sell = False
                    reason = ""

                    if pnl_percent >= MIN_TAKE_PROFIT:
                        should_sell = True
                        reason = f"QUICK PROFIT (+{pnl_percent*100:.2f}%)"
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
                        state["price_history"].clear() # Reset histori harga setelah jual

                        msg = (
                            f"🎯 *SCALPING SELL ({reason})*\n"
                            f"• Harga Jual: Rp {current_price:,.0f}\n"
                            f"• Hasil PnL: Rp {pnl_idr:,.0f}\n"
                            f"• Sisa Saldo: Rp {state['idr_balance']:,.0f}"
                        )
                        print(msg)
                        broadcast(msg)

        except Exception as e:
            print("TRADING ERROR:", repr(e))

        time.sleep(INTERVAL_SECONDS)

# ==========================================
# LAPORAN OTOMATIS PER JAM (AUTOMATIC REPORT)
# ==========================================
def hourly_report_loop():
    while True:
        current_hour = time.localtime().tm_hour
        if current_hour != state["last_report_hour"]:
            state["last_report_hour"] = current_hour
            
            current_price = get_indodax_price() or 0
            asset_val = state["asset_balance"] * current_price
            total_equity = state["idr_balance"] + asset_val
            total_pnl = total_equity - START_BALANCE

            msg = (
                f"📈 *LAPORAN PERJAM (AUTOMATIC REPORT)*\n\n"
                f"• Total Equity: Rp {total_equity:,.0f}\n"
                f"• Total PnL: Rp {total_pnl:,.0f}\n"
                f"• Total Transaksi: {state['total_trades']} kali\n"
                f"• Win Rate: {state['winning_trades']} Win / {state['losing_trades']} Loss"
            )
            broadcast(msg)
            
        time.sleep(60)

# ==========================================
# TELEGRAM COMMANDS & MAIN EXECUTION
# ==========================================
def handle_message(message):
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()
    if not chat_id or not text: return

    command = text.split()[0].lower().split("@")[0]

    if command == "/start":
        send_message(chat_id, "🤖 *SCALPER BOT INDODAX ACTIVE*\n\nBot aktif memantau harga per 2 detik.")
    elif command == "/balance":
        current_price = get_indodax_price() or 0
        total_equity = state["idr_balance"] + (state["asset_balance"] * current_price)
        send_message(chat_id, f"💰 *SALDO DEMO*\n\n• Cash IDR: Rp {state['idr_balance']:,.0f}\n• Nilai Aset: Rp {state['asset_balance']*current_price:,.0f}\n• Total Equity: Rp {total_equity:,.0f}")
    elif command == "/report":
        current_price = get_indodax_price() or 0
        total_equity = state["idr_balance"] + (state["asset_balance"] * current_price)
        send_message(chat_id, f"📊 *LAPORAN SCALPING*\n\n• Equity: Rp {total_equity:,.0f}\n• Trades: {state['total_trades']} x\n• Win/Loss: {state['winning_trades']}/{state['losing_trades']}")

def polling():
    offset = None
    telegram("deleteWebhook", {"drop_pending_updates": "false"})
    while True:
        try:
            params = {"timeout": 25, "allowed_updates": json.dumps(["message"])}
            if offset is not None: params["offset"] = offset
            result = telegram("getUpdates", params)
            if result and result.get("ok"):
                for update in result.get("result", []):
                    offset = update["update_id"] + 1
                    if update.get("message"): handle_message(update["message"])
        except Exception:
            time.sleep(5)

if __name__ == "__main__":
    # Jalankan Trading Loop (Tiap 2 detik)
    threading.Thread(target=trading_loop, daemon=True).start()
    # Jalankan Laporan Otomatis (Tiap jam)
    threading.Thread(target=hourly_report_loop, daemon=True).start()
    # Jalankan Telegram Listener
    polling()
