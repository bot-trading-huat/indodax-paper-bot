import os
import time
import urllib.request
import urllib.parse
import json
import hmac
import hashlib
import threading
from datetime import datetime, timezone, timedelta
from collections import deque

import sys
sys.stdout.reconfigure(line_buffering=True)

WIB = timezone(timedelta(hours=7))

def get_wib_time():
    return datetime.now(WIB).strftime("%H:%M:%S")

def get_wib_datetime():
    return datetime.now(WIB)

# ==========================================
# KONFIGURASI API & DAFTAR PASAR
# ==========================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8604634624:AAHKJaVhA3b7fGqOy66yxP9cOkehqwMbn5U")
INDODAX_API_KEY = os.getenv("INDODAX_API_KEY", "FHKI0WWQ-CREFEVQM-4NYKVNHQ-1HAGNSL4-EL9NWIEK").strip()
INDODAX_SECRET_KEY = os.getenv("INDODAX_SECRET_KEY", "431cdf95bf07326082fa4a271bd120b600f0cc13b4beca9248320a69de1ea3cec7e3961016f17d1b").strip()

# Menggunakan format resmi Indodax dengan garis bawah (btc_idr)
ACTIVE_PAIRS = ["btc_idr"] 

# State terpisah untuk setiap pair agar tidak saling gabung/tercampur
market_states = {}
for pair in ACTIVE_PAIRS:
    market_states[pair] = {
        "pair": pair,
        "is_running": False,
        "in_position": False,
        "buy_price": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "last_market_price": 0.0,
        "price_trend": "⏺",
        "minute_start_equity": 0.0,
        "minute_wins": 0,
        "minute_losses": 0,
        "minute_logs": deque([f"Bot {pair.upper()} disiapkan, menunggu start..."], maxlen=8),
        "chart_chars": deque(maxlen=10),
        "dashboard_chat_id": None,
        "dashboard_msg_id": None,
        "last_rendered_text": ""
    }

def telegram(method, params=None):
    if not TOKEN: return None
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    try:
        data = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

def add_log(pair, text):
    timestamp = get_wib_time()
    log_line = f"[{timestamp}] {text}"
    market_states[pair]["minute_logs"].append(log_line)

def get_indodax_price(pair):
    """Mengambil harga spesifik untuk satu pair pasar tertentu"""
    try:
        ts = int(time.time() * 1000)
        url = f"https://indodax.com/api/ticker/{pair}?ts={ts}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            price = float(data.get("ticker", {}).get("last", 0))
            
            state = market_states[pair]
            if price > 0:
                if state["last_market_price"] > 0:
                    if price > state["last_market_price"]:
                        state["price_trend"] = "🔺"
                        char = "▇"
                    elif price < state["last_market_price"]:
                        state["price_trend"] = "🔻"
                        char = "▂"
                    else:
                        state["price_trend"] = "⏺"
                        char = "—"
                else:
                    char = "—"
                state["chart_chars"].append(char)
                state["last_market_price"] = price
            return price
    except Exception:
        return market_states[pair]["last_market_price"]

def generate_block_chart(pair):
    chars = market_states[pair]["chart_chars"]
    if not chars:
        return "——————————"
    return "".join(chars)

def fetch_realtime_account():
    """Mengambil informasi saldo akun secara keseluruhan dari Indodax dalam IDR"""
    url = "https://indodax.com/tapi"
    nonce = str(int(time.time() * 1000))
    params = {"method": "getInfo", "nonce": nonce}
    
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
        with urllib.request.urlopen(req, timeout=3) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            if res.get("success") == 1:
                balances = res.get("return", {}).get("balance", {})
                balances_hold = res.get("return", {}).get("balance_hold", {})
                
                idr_cash = float(balances.get("idr", 0)) + float(balances_hold.get("idr", 0))
                btc_amt = float(balances.get("btc", 0)) + float(balances_hold.get("btc", 0))
                
                btc_price = get_indodax_price("btc_idr")
                
                btc_val = btc_amt * btc_price
                grand_total = idr_cash + btc_val
                
                return True, idr_cash, btc_amt, grand_total, "OK"
            else:
                return False, 0.0, 0.0, 0.0, res.get("error", "API Error")
    except Exception as e:
        return False, 0.0, 0.0, 0.0, str(e)

# ==========================================
# KEYBOARDS PER PASAR
# ==========================================
def get_main_keyboard(pair):
    state = market_states[pair]
    play_stop_btn = (
        {"text": f"⏹ Hentikan {pair.upper()}", "callback_data": f"stop_{pair}"}
        if state["is_running"]
        else {"text": f"▶️ Jalankan {pair.upper()}", "callback_data": f"start_{pair}"}
    )
    return {
        "inline_keyboard": [
            [play_stop_btn, {"text": "🔄 Refresh", "callback_data": f"refresh_{pair}"}],
            [{"text": "📊 Status & Posisi", "callback_data": f"status_{pair}"}],
            [{"text": "💰 Cek Saldo Akun", "callback_data": f"balance_{pair}"}],
            [{"text": "📈 Laporan PnL", "callback_data": f"report_{pair}"}],
            [{"text": "⚡ Cek Harga Real-Time", "callback_data": f"price_{pair}"}]
        ]
    }

def get_back_keyboard(pair):
    return {
        "inline_keyboard": [
            [{"text": "🏠 Kembali ke Dashboard", "callback_data": f"home_{pair}"}]
        ]
    }

# ==========================================
# DASHBOARD TEXT BUILDER PER PASAR
# ==========================================
def get_home_text(pair):
    state = market_states[pair]
    current_price = get_indodax_price(pair)
    success, idr_cash, btc_amt, total_equity, err = fetch_realtime_account()
    
    if not success and current_price == 0:
        return f"❌ *GAGAL KONEKSI PASAR {pair.upper()}*"

    status_str = f"Aktif {state['price_trend']}" if state["is_running"] else f"Berhenti {state['price_trend']}"
    now_wib = get_wib_time()

    coin_name = pair.split("_")[0].upper() # Menjadi BTC
    pos_info = f"⚡ *Posisi:* Scalping (Holding {coin_name})" if state["in_position"] else "💵 *Posisi:* Standby (Persiapan Beli)"
    chart_str = generate_block_chart(pair)

    if state["minute_logs"]:
        logs_str = "\n".join(state["minute_logs"])
        block_text = f"```\n{logs_str}\n```"
    else:
        block_text = "```\nMemantau pergerakan market...\n```"

    stats_line = f"📈 *Statistik:* 🟢 {state['winning_trades']} Win | 🔴 {state['losing_trades']} Loss"

    return (
        f"🤖 *BOT TRADING INDODAX ({pair.upper()})*\n\n"
        f"Status Bot: {status_str}\n"
        f"💰 *Harga {pair.upper()}:* Rp {current_price:,.0f}\n"
        f"{pos_info}\n"
        f"📈 Grafik: `{chart_str}`\n"
        f"{stats_line}\n"
        f"⏱ _Live Update: {now_wib} WIB_\n\n"
        f"📋 *RIWAYAT TRANSAKSI:*\n{block_text}\n\n"
        f"Pilih menu untuk mengelola pasar ini:"
    )

# ==========================================
# ENGINE TRADING INDEPENDEN PER PASAR
# ==========================================
def execute_real_order(pair, side, amount_idr=0, amount_coin=0):
    url = "https://indodax.com/tapi"
    nonce = str(int(time.time() * 1000))
    params = {
        "method": "trade",
        "pair": pair,
        "type": side,
        "nonce": nonce
    }
    coin_key = pair.split("_")[0]
    if side == "buy":
        params["idr"] = f"{amount_idr:.0f}"
    else:
        params[coin_key] = f"{amount_coin:.8f}"

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
            res = json.loads(resp.read().decode("utf-8"))
            if res.get("success") == 1:
                return True, res.get("return", {})
            return False, res.get("error", "Unknown Error")
    except Exception as e:
        return False, str(e)

def market_trading_worker(pair):
    """Worker thread terpisah untuk setiap pasar/pair agar berjalan sendiri-sendiri"""
    print(f"Engine Trading untuk pasar {pair.upper()} aktif...")
    highest_price = 0.0

    while True:
        try:
            state = market_states[pair]
            if state["is_running"]:
                current_price = get_indodax_price(pair)
                success, idr_cash, btc_amt, total_equity, err = fetch_realtime_account()

                if current_price > 0:
                    # 1. KONDISI BELI (ENTRY)
                    if not state["in_position"]:
                        if idr_cash > 10000:
                            buy_idr = idr_cash * 0.995 
                            add_log(pair, f"Mencoba BUY {pair.upper()} dg Rp {buy_idr:,.0f}...")
                            success_order, res_data = execute_real_order(pair, "buy", amount_idr=buy_idr)
                            
                            if success_order:
                                state["buy_price"] = current_price
                                highest_price = current_price
                                state["in_position"] = True
                                add_log(pair, f"BUY BERHASIL @ Rp {current_price:,.0f}")
                            else:
                                add_log(pair, f"Gagal BUY: {res_data}")
                        else:
                            if not any("Saldo IDR < Min Order" in log for log in state["minute_logs"]):
                                add_log(pair, "Peringatan: Saldo IDR Tunai kurang.")

                    # 2. KONDISI KELOLA POSISI (SELL)
                    elif state["in_position"]:
                        if current_price > highest_price:
                            highest_price = current_price

                        price_change_pct = (current_price - state["buy_price"]) / state["buy_price"]
                        drop_from_peak = (highest_price - current_price) / highest_price if highest_price > 0 else 0

                        is_profit_safe = price_change_pct >= 0.006
                        is_trailing_triggered = (highest_price >= state["buy_price"] * 1.01) and (drop_from_peak >= 0.003)
                        is_big_target = price_change_pct >= 0.03
                        is_stop_loss = price_change_pct <= -0.02

                        if (is_profit_safe and is_trailing_triggered) or is_big_target or (is_profit_safe and drop_from_peak >= 0.002) or is_stop_loss:
                            success_acc, _, current_btc_amt, _, _ = fetch_realtime_account()
                            coin_amount = current_btc_amt if success_acc else 0.001
                            add_log(pair, f"Mencoba SELL {pair.upper()}...")
                            success_order, res_data = execute_real_order(pair, "sell", amount_coin=coin_amount)
                            
                            if success_order:
                                state["in_position"] = False
                                state["total_trades"] += 1
                                highest_price = 0.0
                                state["winning_trades"] += 1
                                state["minute_wins"] += 1
                                add_log(pair, f"SELL PROFIT 🔺 @ Rp {current_price:,.0f}")
                            else:
                                add_log(pair, f"Gagal SELL: {res_data}")

        except Exception as e:
            print(f"ENGINE ERROR [{pair}]:", e)

        time.sleep(3)

# ==========================================
# TELEGRAM HANDLER
# ==========================================
def answer_callback(cb_id, text=""):
    telegram("answerCallbackQuery", {"callback_query_id": cb_id, "text": text, "show_alert": False})

def handle_update(update):
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        data = cb.get("data", "")

        parts = data.split("_")
        # Menangani callback pair yang mengandung underscore seperti btc_idr
        if len(parts) >= 2:
            action = parts[0]
            pair = "_".join(parts[1:])
            if pair in market_states:
                state = market_states[pair]
                
                if action == "start":
                    state["is_running"] = True
                    add_log(pair, "Bot diaktifkan user.")
                    answer_callback(cb_id, f"▶️ Bot {pair.upper()} dijalankan.")
                elif action == "stop":
                    state["is_running"] = False
                    add_log(pair, "Bot dihentikan user.")
                    answer_callback(cb_id, f"⏹ Bot {pair.upper()} dihentikan.")
                elif action == "refresh":
                    answer_callback(cb_id, "🔄 Diperbarui.")
                elif action == "status":
                    answer_callback(cb_id)
                    text = f"📊 *STATUS {pair.upper()}*\n• Berjalan: {state['is_running']}\n• Win/Loss: {state['winning_trades']}/{state['losing_trades']}"
                    telegram("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "Markdown", "reply_markup": get_back_keyboard(pair)})
                    return
                elif action == "balance":
                    answer_callback(cb_id)
                    success, idr_bal, btc_amt, equity, _ = fetch_realtime_account()
                    text = f"💰 *SALDO AKUN*\n• IDR: Rp {idr_bal:,.0f}\n• Total Equity: Rp {equity:,.0f}"
                    telegram("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "Markdown", "reply_markup": get_back_keyboard(pair)})
                    return
                elif action == "price":
                    answer_callback(cb_id)
                    p = get_indodax_price(pair)
                    text = f"⚡ *HARGA {pair.upper()}*\n• Rp {p:,.0f}"
                    telegram("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "Markdown", "reply_markup": get_back_keyboard(pair)})
                    return
                elif action == "home":
                    answer_callback(cb_id)

                new_text = get_home_text(pair)
                telegram("editMessageText", {
                    "chat_id": str(chat_id),
                    "message_id": msg_id,
                    "text": new_text,
                    "parse_mode": "Markdown",
                    "reply_markup": get_main_keyboard(pair)
                })
        return

    if "message" in update:
        msg = update["message"]
        chat_id = msg.get("chat", {}).get("id")
        text = (msg.get("text") or "").strip()
        if not chat_id: return

        if text.startswith("/start") or text.startswith("/menu"):
            for pair in ACTIVE_PAIRS:
                telegram("sendMessage", {
                    "chat_id": str(chat_id),
                    "text": get_home_text(pair),
                    "parse_mode": "Markdown",
                    "reply_markup": get_main_keyboard(pair)
                })

def polling():
    offset = None
    telegram("deleteWebhook", {"drop_pending_updates": "false"})
    print("Polling Telegram Multi-Market dimulai...")
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
    for pair in ACTIVE_PAIRS:
        threading.Thread(target=market_trading_worker, args=(pair,), daemon=True).start()
    
    polling()
