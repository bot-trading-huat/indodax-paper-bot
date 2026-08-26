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

# ==========================================
# KONFIGURASI API & BOT (DIUBAH KE USDT)
# ==========================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8604634624:AAHKJaVhA3b7fGqOy66yxP9cOkehqwMbn5U")
INDODAX_API_KEY = os.getenv("INDODAX_API_KEY", "FHKI0WWQ-CREFEVQM-4NYKVNHQ-1HAGNSL4-EL9NWIEK").strip()
INDODAX_SECRET_KEY = os.getenv("INDODAX_SECRET_KEY", "431cdf95bf07326082fa4a271bd120b600f0cc13b4beca9248320a69de1ea3cec7e3961016f17d1b").strip()
PAIR = "btcusdt"  # Diubah dari btcidr ke btcusdt

state = {
    "is_running": False,
    "in_position": False,
    "buy_price": 0.0,
    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,
    
    "last_market_price": 0.0,
    "price_trend": "⏺",
    
    # Sesi per 1 menit
    "minute_start_equity": 0.0,
    "minute_wins": 0,
    "minute_losses": 0,
    "minute_logs": deque(["Bot siap, cek saldo..."], maxlen=8),
    
    # Dashboard Tracking
    "dashboard_chat_id": None,
    "dashboard_msg_id": None,
    "last_rendered_text": ""
}

chart_chars = deque(maxlen=10)

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

def add_log(text):
    timestamp = get_wib_time()
    log_line = f"[{timestamp}] {text}"
    state["minute_logs"].append(log_line)

def get_indodax_price():
    try:
        ts = int(time.time() * 1000)
        url = f"https://indodax.com/api/ticker/{PAIR}?ts={ts}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            price = float(data.get("ticker", {}).get("last", 0))
            
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
                    
                chart_chars.append(char)
                state["last_market_price"] = price
                
            return price
    except Exception:
        if state["last_market_price"] > 0:
            return state["last_market_price"]
        return 0.0

def generate_block_chart():
    if not chart_chars:
        return "——"
    return "".join(chart_chars)

def fetch_realtime_account():
    price = get_indodax_price()
    
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
                
                # Mengambil saldo USDT
                usdt_cash = float(balances.get("usdt", 0))
                usdt_hold = float(balances_hold.get("usdt", 0))
                total_usdt = usdt_cash + usdt_hold
                
                btc_amt = float(balances.get("btc", 0)) + float(balances_hold.get("btc", 0))
                btc_val_usdt = btc_amt * price
                grand_total = total_usdt + btc_val_usdt
                
                return True, usdt_cash, btc_amt, grand_total, price, "OK"
            else:
                return False, 0.0, 0.0, 0.0, price, res.get("error", "API Error")
    except Exception as e:
        return False, 0.0, 0.0, 0.0, price, str(e)

# ==========================================
# KEYBOARDS
# ==========================================
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
            [{"text": "💰 Cek Saldo Akun", "callback_data": "btn_balance"}],
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

# ==========================================
# DASHBOARD TEXT BUILDER
# ==========================================
def get_home_text(is_final=False):
    success, usdt_bal, btc_amt, total_equity, price, err = fetch_realtime_account()
    if not success:
        return f"❌ *GAGAL KONEKSI API INDODAX:* `{err}`"

    status_str = "🟢 Aktif 🔘" if state["is_running"] else "🔴 Berhenti 🔘"
    now_wib = get_wib_time()

    pos_info = f"• Posisi: Memegang Aset ({btc_amt:.6f} BTC)" if state["in_position"] else f"• Posisi: USDT Ready ($ {usdt_bal:,.2f})"
    chart_str = generate_block_chart()
    asset_val = btc_amt * price

    if state["minute_logs"]:
        logs_str = "\n".join(state["minute_logs"])
        block_text = f"```\n{logs_str}\n```"
    else:
        block_text = "```\nMemantau pergerakan market...\n```"

    if is_final:
        profit_loss_minute = total_equity - state["minute_start_equity"]
        profit_str = f"$ {profit_loss_minute:+,.2f}"

        return (
            f"🔹 *BTC/USDT* {status_str} {state['price_trend']}\n"
            f"• Harga BTC: $ {price:,.2f}\n"
            f"• Saldo USDT Tunai: $ {usdt_bal:,.2f}\n"
            f"• Nilai Aset BTC: $ {asset_val:,.2f} ({btc_amt:.8f} BTC)\n"
            f"• *Total Keseluruhan (Equity): $ {total_equity:,.2f}*\n"
            f"• Grafik: `{chart_str}`\n"
            f"{pos_info}\n"
            f"⏱ _Waktu Selesai: {now_wib} WIB_\n\n"
            f"📋 *KOTAK HITAM (LOG AKTIVITAS):*\n{block_text}\n\n"
            f"📊 *RINGKASAN SESI 1 MENIT:*\n"
            f"• Profit: {state['minute_wins']}x | Loss: {state['minute_losses']}x\n"
            f"• PnL Sesi Ini: {profit_str}\n"
            f"• Total Win Global: {state['winning_trades']} | Total Lose Global: {state['losing_trades']}"
        )

    return (
        f"🔹 *BTC/USDT* {status_str} {state['price_trend']}\n"
        f"• Harga BTC: $ {price:,.2f}\n"
        f"• Saldo USDT Tunai: $ {usdt_bal:,.2f}\n"
        f"• Nilai Aset BTC: $ {asset_val:,.2f} ({btc_amt:.8f} BTC)\n"
        f"• *Total Keseluruhan (Equity): $ {total_equity:,.2f}*\n"
        f"• Grafik: `{chart_str}`\n"
        f"{pos_info}\n\n"
        f"📊 *REKAP PERFORMA:*\n"
        f"• Total Trade: {state['total_trades']}x\n"
        f"• Total Win: {state['winning_trades']} | Total Lose: {state['losing_trades']}\n\n"
        f"📋 *KOTAK HITAM (LOG AKTIVITAS):*\n{block_text}"
    )

# ==========================================
# AUTO-REFRESH LIVE DASHBOARD
# ==========================================
def auto_refresh_dashboard_loop():
    while True:
        try:
            get_indodax_price()
            if state["dashboard_chat_id"] and state["dashboard_msg_id"]:
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
        time.sleep(3)

# ==========================================
# LAPORAN PER 1 MENIT & HARIAN (00.00)
# ==========================================
def minutely_reset_loop():
    while True:
        time.sleep(60)
        try:
            if state["dashboard_chat_id"] and state["dashboard_msg_id"]:
                old_msg_id = state["dashboard_msg_id"]
                final_text = get_home_text(is_final=True)
                
                state["dashboard_msg_id"] = None
                
                telegram("editMessageText", {
                    "chat_id": str(state["dashboard_chat_id"]),
                    "message_id": old_msg_id,
                    "text": final_text,
                    "parse_mode": "Markdown"
                })

                success, _, _, total_equity, _, _ = fetch_realtime_account()
                state["minute_start_equity"] = total_equity if success else 0.0
                state["minute_wins"] = 0
                state["minute_losses"] = 0
                state["minute_logs"].clear()
                add_log("Sesi 1 menit baru dimulai.")

                new_home_text = get_home_text()
                resp = telegram("sendMessage", {
                    "chat_id": str(state["dashboard_chat_id"]),
                    "text": new_home_text,
                    "parse_mode": "Markdown",
                    "reply_markup": get_main_keyboard()
                })
                if resp and resp.get("ok"):
                    state["dashboard_msg_id"] = resp["result"]["message_id"]
                    state["last_rendered_text"] = new_home_text

            now_dt = datetime.now(WIB)
            if now_dt.hour == 0 and now_dt.minute == 0:
                if state["dashboard_chat_id"]:
                    daily_report = (
                        f"🌙 *LAPORAN FINAL HARIAN (00:00 WIB)*\n\n"
                        f"• Total Trade Hari Ini: {state['total_trades']}x\n"
                        f"• Total Win: {state['winning_trades']} | Total Lose: {state['losing_trades']}\n"
                        f"Bot terus memantau untuk hari baru."
                    )
                    telegram("sendMessage", {
                        "chat_id": str(state["dashboard_chat_id"]),
                        "text": daily_report,
                        "parse_mode": "Markdown"
                    })
                time.sleep(70)
        except Exception as e:
            print("MINUTELY / DAILY RESET ERROR:", e)

# ==========================================
# ENGINE TRADING (JEDA 10 DETIK)
# ==========================================
def execute_real_order(side, amount_usdt=0, amount_btc=0):
    url = "https://indodax.com/tapi"
    nonce = str(int(time.time() * 1000))
    params = {
        "method": "trade",
        "pair": PAIR,
        "type": side,
        "nonce": nonce
    }
    if side == "buy":
        params["usdt"] = f"{amount_usdt:.8f}"
    else:
        params["btc"] = f"{amount_btc:.8f}"

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

def trading_loop():
    print("Engine Real Trading Aktif (Interval 10 Detik)...")
    highest_price = 0.0

    while True:
        try:
            if state["is_running"]:
                success, usdt_cash, btc_amt, total_equity, current_price, err = fetch_realtime_account()

                if success and current_price > 0:
                    if not state["in_position"]:
                        if usdt_cash >= 1:  # Minimal threshold $1 USDT
                            buy_usdt = usdt_cash * 0.995 
                            add_log(f"Mencoba BUY BTC dg $ {buy_usdt:,.2f}...")
                            success_order, res_data = execute_real_order("buy", amount_usdt=buy_usdt)
                            
                            if success_order:
                                state["buy_price"] = current_price
                                highest_price = current_price
                                state["in_position"] = True
                                add_log(f"BUY BERHASIL @ $ {current_price:,.2f}")
                            else:
                                add_log(f"Gagal BUY: {res_data}")
                        else:
                            warning_msg = f"USDT Tunai $ {usdt_cash:,.2f} (< $1)"
                            if not any(warning_msg in log for log in state["minute_logs"]):
                                add_log(f"Peringatan: Saldo USDT Tunai kurang.")

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
                            _, _, current_btc_amt, _, _, _ = fetch_realtime_account()
                            if current_btc_amt > 0.00001:
                                add_log(f"Mencoba SELL {current_btc_amt:.6f} BTC...")
                                success_order, res_data = execute_real_order("sell", amount_btc=current_btc_amt)
                                
                                if success_order:
                                    pnl_usdt = (current_btc_amt * current_price) - (current_btc_amt * state["buy_price"])
                                    state["in_position"] = False
                                    state["total_trades"] += 1
                                    highest_price = 0.0

                                    if pnl_usdt > 0:
                                        state["winning_trades"] += 1
                                        state["minute_wins"] += 1
                                        add_log(f"SELL PROFIT 🔺 @ $ {current_price:,.2f} (+$ {pnl_usdt:,.2f})")
                                    else:
                                        state["losing_trades"] += 1
                                        state["minute_losses"] += 1
                                        add_log(f"SELL LOSS 🔻 @ $ {current_price:,.2f} (-$ {abs(pnl_usdt):,.2f})")
                                else:
                                    add_log(f"Gagal SELL: {res_data}")

        except Exception as e:
            print("ENGINE ERROR:", e)

        time.sleep(10)

# ==========================================
# TELEGRAM HANDLER
# ==========================================
def get_status_text():
    success, usdt_bal, btc_amt, _, price, _ = fetch_realtime_account()
    status_str = "🟢 Aktif 🔘" if state["is_running"] else "🔴 Berhenti 🔘"
    pos = f"Memegang Aset ({btc_amt:.6f} BTC)" if state["in_position"] else f"USDT Ready ($ {usdt_bal:,.2f})"
    return f"📊 *STATUS BOT*\n\n• Mode Bot: {status_str}\n• Pair: BTC/USDT\n• Harga BTC saat ini: $ {price:,.2f}\n• USDT Tunai: $ {usdt_bal:,.2f}\n• Posisi: {pos}"

def get_balance_text():
    success, usdt_bal, btc_amt, equity, price, _ = fetch_realtime_account()
    asset_val = btc_amt * price
    return f"💰 *SALDO AKUN INDODAX*\n\n• Saldo USDT Tunai: $ {usdt_bal:,.2f}\n• Nilai Aset BTC: $ {asset_val:,.2f} ({btc_amt:.8f} BTC)\n• Total Keseluruhan (Equity): $ {equity:,.2f}"

def get_report_text():
    success, _, _, equity, price, _ = fetch_realtime_account()
    return f"📈 *LAPORAN PERFORMA*\n\n• Total Keseluruhan (Equity): $ {equity:,.2f}\n• Total Trade: {state['total_trades']}x\n• Total Win: {state['winning_trades']} | Total Lose: {state['losing_trades']}"

def answer_callback(cb_id, text=""):
    telegram("answerCallbackQuery", {"callback_query_id": cb_id, "text": text, "show_alert": False})

def update_menu(chat_id, msg_id, text, is_home=False):
    markup = get_main_keyboard() if is_home else get_back_keyboard()
    res = telegram("editMessageText", {
        "chat_id": str(chat_id),
        "message_id": msg_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": markup
    })
    if is_home and res and res.get("ok"):
        state["dashboard_chat_id"] = chat_id
        state["dashboard_msg_id"] = msg_id
        state["last_rendered_text"] = text

def send_menu(chat_id, text):
    res = telegram("sendMessage", {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": get_main_keyboard()
    })
    if res and res.get("ok"):
        state["dashboard_chat_id"] = chat_id
        state["dashboard_msg_id"] = res["result"]["message_id"]
        state["last_rendered_text"] = text

def handle_update(update):
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        data = cb.get("data", "")

        if data == "btn_start":
            state["is_running"] = True
            success, _, _, total_equity, _, _ = fetch_realtime_account()
            state["minute_start_equity"] = total_equity if success else 0.0
            add_log("Bot diaktifkan user.")
            answer_callback(cb_id, "▶️ Bot dijalankan.")
            update_menu(chat_id, msg_id, get_home_text(), is_home=True)
        elif data == "btn_stop":
            state["is_running"] = False
            add_log("Bot dihentikan user.")
            answer_callback(cb_id, "⏹ Bot dihentikan.")
            update_menu(chat_id, msg_id, get_home_text(), is_home=True)
        elif data == "btn_home":
            answer_callback(cb_id)
            update_menu(chat_id, msg_id, get_home_text(), is_home=True)
        elif data == "btn_status":
            answer_callback(cb_id)
            update_menu(chat_id, msg_id, get_status_text(), is_home=False)
        elif data == "btn_balance":
            answer_callback(cb_id)
            update_menu(chat_id, msg_id, get_balance_text(), is_home=False)
        elif data == "btn_report":
            answer_callback(cb_id)
            update_menu(chat_id, msg_id, get_report_text(), is_home=False)
        elif data == "btn_price":
            answer_callback(cb_id)
            price = get_indodax_price() or 0
            update_menu(chat_id, msg_id, f"⚡ *HARGA REAL-TIME*\n\nBTC/USDT: $ {price:,.2f}", is_home=False)
        else:
            answer_callback(cb_id)
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
    print("Polling Telegram Real Trading dimulai...")
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
