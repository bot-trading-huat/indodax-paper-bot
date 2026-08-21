import os
import time
import json
import random
import threading
import urllib.request
import urllib.parse
from collections import deque
from datetime import datetime

import websocket

# ============================================================
# RAILWAY VARIABLES
# ============================================================
START_BALANCE = float(os.getenv("START_BALANCE", "100000"))
PAIR = os.getenv("PAIR", "btc_idr").lower()

FEE_RATE = float(os.getenv("FEE_RATE", "0.002"))

MIN_TAKE_PROFIT = float(os.getenv("MIN_TAKE_PROFIT", "0.02"))
MAX_TAKE_PROFIT = float(os.getenv("MAX_TAKE_PROFIT", "0.30"))

STOP_LOSS = float(os.getenv("STOP_LOSS", "0.05"))
DAILY_LOSS_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT", "0.10"))

INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "5"))
WINDOW_SIZE = int(os.getenv("WINDOW_SIZE", "60"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Official Indodax Market Data WebSocket.
WS_URL = os.getenv("INDODAX_WS_URL", "wss://ws3.indodax.com/ws/")
WS_TOKEN = os.getenv("INDODAX_WS_TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE5NDY2MTg0MTV9.UR1lBM6Eqh0yWz-PVirw1uPCxe60FdchR8eNVdsske0")

# ============================================================
# PAPER STATE
# ============================================================
balance = START_BALANCE
day_start_balance = START_BALANCE
position = None
trades = []
paused = False

last_report_date = datetime.now().date()
prices = deque(maxlen=WINDOW_SIZE)

state_lock = threading.Lock()


# ============================================================
# TELEGRAM
# ============================================================
def telegram_api(method, params=None):
    if not TELEGRAM_BOT_TOKEN:
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    body = urllib.parse.urlencode(params or {}).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=body)
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print("Telegram error:", repr(exc))
        return None


def send_telegram(text, chat_id=None):
    target = chat_id or TELEGRAM_CHAT_ID

    if not TELEGRAM_BOT_TOKEN or not target:
        print("\n[TELEGRAM NOT CONFIGURED]\n" + text)
        return

    telegram_api(
        "sendMessage",
        {
            "chat_id": str(target),
            "text": text,
        },
    )


def authorized(chat_id):
    if not TELEGRAM_CHAT_ID:
        return True
    return str(chat_id) == str(TELEGRAM_CHAT_ID)


def status_text():
    with state_lock:
        pnl = balance - START_BALANCE
        pnl_pct = (pnl / START_BALANCE * 100) if START_BALANCE else 0

        if position:
            pos = (
                f"OPEN\n"
                f"Entry: Rp{position['entry']:,.0f}\n"
                f"TP: Rp{position['tp']:,.0f}\n"
                f"SL: Rp{position['sl']:,.0f}"
            )
        else:
            pos = "NONE"

        return (
            "🤖 INDODAX PAPER BOT\n\n"
            f"Status: {'⏸ PAUSED' if paused else '🟢 RUNNING'}\n"
            "Mode: PAPER TRADING\n"
            f"Pair: {PAIR.upper()}\n"
            f"Saldo: Rp{balance:,.0f}\n"
            f"PnL: Rp{pnl:,.0f} ({pnl_pct:+.2f}%)\n"
            f"Posisi: {pos}\n\n"
            f"TP random: {MIN_TAKE_PROFIT*100:.0f}%–{MAX_TAKE_PROFIT*100:.0f}%\n"
            f"SL: {STOP_LOSS*100:.0f}%\n"
            f"Daily loss limit: {DAILY_LOSS_LIMIT*100:.0f}%"
        )


def daily_report():
    with state_lock:
        pnl = balance - day_start_balance
        pct = pnl / day_start_balance * 100 if day_start_balance else 0
        wins = sum(1 for x in trades if x["pnl"] > 0)
        losses = sum(1 for x in trades if x["pnl"] < 0)

        return (
            "📊 DAILY PAPER REPORT\n\n"
            f"Tanggal: {datetime.now():%d-%m-%Y}\n"
            f"Pair: {PAIR.upper()}\n"
            f"Saldo: Rp{balance:,.0f}\n"
            f"PnL hari ini: Rp{pnl:,.0f} ({pct:+.2f}%)\n"
            f"Trade: {len(trades)}\n"
            f"Win: {wins}\n"
            f"Loss: {losses}\n"
            f"Status: {'⏸ PAUSED' if paused else '🟢 RUNNING'}\n"
            "Mode: DEMO / PAPER TRADING"
        )


def handle_command(chat_id, text):
    global paused

    if not authorized(chat_id):
        send_telegram("⛔ Chat ID ini tidak diizinkan.", chat_id)
        return

    command = text.strip().split()[0].lower().split("@")[0]

    if command == "/start":
        send_telegram(
            "🤖 INDODAX PAPER BOT AKTIF\n\n"
            "/status - status bot\n"
            "/balance - saldo virtual\n"
            "/trades - statistik transaksi\n"
            "/report - laporan hari ini\n"
            "/pause - jeda entry\n"
            "/resume - lanjutkan entry",
            chat_id,
        )
    elif command == "/status":
        send_telegram(status_text(), chat_id)
    elif command == "/balance":
        with state_lock:
            send_telegram(
                f"💰 SALDO VIRTUAL\n\n"
                f"Saldo: Rp{balance:,.0f}\n"
                f"PnL total: Rp{balance-START_BALANCE:,.0f}",
                chat_id,
            )
    elif command == "/trades":
        with state_lock:
            wins = sum(1 for x in trades if x["pnl"] > 0)
            losses = sum(1 for x in trades if x["pnl"] < 0)
            send_telegram(
                f"📈 TRANSAKSI HARI INI\n\n"
                f"Total: {len(trades)}\n"
                f"Win: {wins}\n"
                f"Loss: {losses}",
                chat_id,
            )
    elif command == "/report":
        send_telegram(daily_report(), chat_id)
    elif command == "/pause":
        paused = True
        send_telegram("⏸ Paper trading dijeda. Posisi terbuka tidak dipaksa ditutup.", chat_id)
    elif command == "/resume":
        paused = False
        send_telegram("▶️ Paper trading dilanjutkan.", chat_id)
    else:
        send_telegram("Perintah tidak dikenal. Gunakan /status.", chat_id)


def telegram_polling():
    offset = None

    while True:
        params = {"timeout": 20}
        if offset is not None:
            params["offset"] = offset

        result = telegram_api("getUpdates", params)

        if not result or not result.get("ok"):
            time.sleep(3)
            continue

        for update in result.get("result", []):
            offset = update["update_id"] + 1

            message = update.get("message") or {}
            chat = message.get("chat") or {}
            text = message.get("text")

            if text and chat.get("id") is not None:
                handle_command(chat["id"], text)


# ============================================================
# PAPER TRADING
# ============================================================
def open_position(price):
    global position

    with state_lock:
        if position is not None:
            return

        size_idr = balance * 0.50
        if size_idr < 10000:
            return

        tp_pct = random.uniform(MIN_TAKE_PROFIT, MAX_TAKE_PROFIT)

        position = {
            "entry": price,
            "cost": size_idr,
            "qty": size_idr / price,
            "tp_pct": tp_pct,
            "tp": price * (1 + tp_pct),
            "sl": price * (1 - STOP_LOSS),
        }

        text = (
            "🟢 DEMO ENTRY\n\n"
            f"Pair: {PAIR.upper()}\n"
            f"Entry: Rp{price:,.0f}\n"
            f"Size: Rp{size_idr:,.0f}\n"
            f"Random TP: +{tp_pct*100:.2f}%\n"
            f"TP: Rp{position['tp']:,.0f}\n"
            f"SL: Rp{position['sl']:,.0f}"
        )

    send_telegram(text)


def close_position(price, reason):
    global position, balance

    with state_lock:
        if not position:
            return

        gross = position["qty"] * (price - position["entry"])
        fees = (
            position["cost"] * FEE_RATE
            + (position["qty"] * price) * FEE_RATE
        )
        pnl = gross - fees

        balance += pnl
        trades.append(
            {
                "time": datetime.now().isoformat(),
                "entry": position["entry"],
                "exit": price,
                "pnl": pnl,
                "reason": reason,
            }
        )

        entry = position["entry"]
        position = None
        current_balance = balance

    send_telegram(
        f"{'🟢' if pnl >= 0 else '🔴'} DEMO EXIT {reason}\n\n"
        f"Entry: Rp{entry:,.0f}\n"
        f"Exit: Rp{price:,.0f}\n"
        f"PnL: Rp{pnl:,.0f}\n"
        f"Saldo: Rp{current_balance:,.0f}"
    )


def process_price(price):
    global paused

    with state_lock:
        prices.append(price)

        current_position = position
        is_paused = paused

        # Daily loss guard.
        if (
            day_start_balance > 0
            and day_start_balance - balance
            >= day_start_balance * DAILY_LOSS_LIMIT
        ):
            if not paused:
                paused = True
                is_paused = True
                guard_message = True
            else:
                guard_message = False
        else:
            guard_message = False

        if current_position:
            tp = current_position["tp"]
            sl = current_position["sl"]
        else:
            tp = sl = None

    if guard_message:
        send_telegram(
            "🛑 DAILY LOSS LIMIT TERCAPAI\n"
            f"Batas: {DAILY_LOSS_LIMIT*100:.1f}%\n"
            "Bot dijeda sampai /resume."
        )

    if current_position:
        if price >= tp:
            close_position(price, "TAKE PROFIT")
        elif price <= sl:
            close_position(price, "STOP LOSS")
        return

    if is_paused:
        return

    # Simple paper-only trigger:
    # once enough prices exist, enter when current price is
    # 0.5% below the rolling average.
    with state_lock:
        if len(prices) < max(10, WINDOW_SIZE // 3):
            return

        average = sum(prices) / len(prices)

    if price < average * 0.995:
        open_position(price)


# ============================================================
# INDODAX MARKET DATA WEBSOCKET
# ============================================================
def parse_price(message):
    """
    Official chart:tick channel returns data arrays.
    Expected:
    result.data.data = [[timestamp, sequence, price, volume], ...]
    """
    try:
        result = message.get("result") or {}
        channel = result.get("channel", "")

        if not channel.startswith("chart:tick-"):
            return None

        data = (result.get("data") or {}).get("data") or []

        if not data:
            return None

        latest = data[-1]
        if len(latest) < 3:
            return None

        return float(latest[2])
    except (TypeError, ValueError, IndexError):
        return None


class MarketSocket:
    def __init__(self):
        self.ws = None
        self.running = True

    def on_open(self, ws):
        print("WebSocket connected:", WS_URL)

        # Authentication is required by the official Market Data WS.
        # If no custom token is supplied, the server may reject auth;
        # the error will be visible in Railway logs.
        if WS_TOKEN:
            ws.send(
                json.dumps(
                    {
                        "params": {"token": WS_TOKEN},
                        "id": 1,
                    }
                )
            )

        # Subscription is sent after authentication succeeds.
        send_telegram(
            "🟢 MARKET DATA SOCKET CONNECTED\n"
            f"Pair: {PAIR.upper()}\n"
            "Waiting for market stream..."
        )

    def on_message(self, ws, raw):
        try:
            message = json.loads(raw)

            if "error" in message:
                print("Indodax WS error:", message["error"])
                return

            # Authentication response: id=1.
            # Only subscribe after authentication is accepted.
            if message.get("id") == 1 and message.get("result"):
                self.ws.send(
                    json.dumps(
                        {
                            "method": 1,
                            "params": {
                                "channel": f"chart:tick-{PAIR}",
                            },
                            "id": 2,
                        }
                    )
                )
                print("Subscribed:", f"chart:tick-{PAIR}")

            price = parse_price(message)
            if price is not None:
                process_price(price)

        except Exception as exc:
            print("Message error:", repr(exc))

    def on_error(self, ws, error):
        print("WebSocket error:", repr(error))

    def on_close(self, ws, code, reason):
        print("WebSocket closed:", code, reason)

    def run_forever(self):
        while self.running:
            try:
                self.ws = websocket.WebSocketApp(
                    WS_URL,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                )

                self.ws.run_forever(
                    ping_interval=20,
                    ping_timeout=10,
                    suppress_origin=True,
                )

            except Exception as exc:
                print("WebSocket connection error:", repr(exc))

            if self.running:
                print("Reconnecting in 5 seconds...")
                time.sleep(5)


# ============================================================
# DAILY REPORT / MAIN
# ============================================================
def daily_monitor():
    global day_start_balance, last_report_date

    while True:
        today = datetime.now().date()

        if today != last_report_date:
            send_telegram(daily_report())

            with state_lock:
                day_start_balance = balance
                trades.clear()

            last_report_date = today

        time.sleep(30)


def main():
    print("==========================================")
    print(" INDODAX PAPER TRADING BOT")
    print(" DEMO ONLY - NO REAL ORDERS")
    print("==========================================")
    print("Pair:", PAIR)
    print("WebSocket:", WS_URL)
    print("Balance:", START_BALANCE)
    print("TP:", MIN_TAKE_PROFIT, "to", MAX_TAKE_PROFIT)
    print("SL:", STOP_LOSS)
    print("Daily loss limit:", DAILY_LOSS_LIMIT)

    send_telegram(
        "🟢 INDODAX PAPER BOT ONLINE\n\n"
        f"Modal virtual: Rp{START_BALANCE:,.0f}\n"
        f"Pair: {PAIR.upper()}\n"
        f"TP random: {MIN_TAKE_PROFIT*100:.0f}%–{MAX_TAKE_PROFIT*100:.0f}%\n"
        f"SL: {STOP_LOSS*100:.0f}%\n"
        f"Daily loss limit: {DAILY_LOSS_LIMIT*100:.0f}%\n"
        "Data: Indodax Market Data WebSocket"
    )

    threading.Thread(target=telegram_polling, daemon=True).start()
    threading.Thread(target=daily_monitor, daemon=True).start()

    MarketSocket().run_forever()


if __name__ == "__main__":
    main()
