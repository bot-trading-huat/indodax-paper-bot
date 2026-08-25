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
# KONFIGURASI API & MULTI-PAIR BOT
# ==========================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8604634624:AAHKJaVhA3b7fGqOy66yxP9cOkehqwMbn5U")
INDODAX_API_KEY = os.getenv("INDODAX_API_KEY", "FHKI0WWQ-CREFEVQM-4NYKVNHQ-1HAGNSL4-EL9NWIEK").strip()
INDODAX_SECRET_KEY = os.getenv("INDODAX_SECRET_KEY", "431cdf95bf07326082fa4a271bd120b600f0cc13b4beca9248320a69de1ea3cec7e3961016f17d1b").strip()

# Daftar pair yang dipantau secara bersamaan
PAIRS = ["solidr", "usdtidr"]

# State per pair & global
state = {
    "is_running": False,
    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,
    
    # Data per pair
    "pairs_data": {
        "solidr": {
            "name": "SOL/IDR",
            "base": "sol",
            "last_price": 0.0,
            "trend": "⏺",
            "in_position": False,
            "buy_price": 0.0,
            "chart": deque(["—"] * 10, maxlen=10)
        },
        "usdtidr": {
            "name": "USDT/IDR",
            "base": "usdt",
            "last_price": 0.0,
            "trend": "⏺",
            "in_position": False,
            "buy_price": 0.0,
            "chart": deque(["—"] * 10, maxlen=10)
        }
    },
    
    "minute_start_equity": 0.0,
    "minute_wins": 0,
    "minute_losses": 0,
    "minute_logs": deque(["Bot multi-pair disiapkan..."], maxlen=8),
    
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

def add_log(text):
    timestamp = get_wib_time()
    log_line = f"[{timestamp}] {text}"
    state["minute_logs"].append(log_line)

def update_market_data():
    """Mengambil harga dan memperbarui grafik/tren untuk semua pair"""
    ts = int(time.time() * 1000)
    for pair_key, pdata in state["pairs_data"].items():
        try:
            url = f"https://indodax.com/api/ticker/{pair_key}?ts={ts}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                price = float(data.get("ticker", {}).get("last", 0))
                
                if price > 0:
                    old_price = pdata["last_price"]
                    if old_price > 0:
                        if price > old_price:
                            pdata["trend"] = "🔺"
                            char = "▇"
                        elif price < old_price:
                            pdata["trend"] = "🔻"
                            char = "▂"
                        else:
                            pdata["trend"] = "⏺"
                            char = "—"
                    else:
                        char = "—"
                    
                    pdata["chart"].append(char)
                    pdata["last_price"] = price
        except Exception:
            pass

def fetch_realtime_account():
    update_market_data()
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
                
                total_asset_val = idr_cash
                for pair_key, pdata in state["pairs_data"].items():
                    base = pdata["base"]
                    amt = float(balances.get(base, 0)) + float(balances_hold.get(base, 0))
                    total_asset_val += amt * pdata["last_price"]
                
                return True, idr_cash, total_asset_val, res.get("return", {}), "OK"
            else:
                return False, 0.0, 0.0, {}, res.get("error", "API Error")
    except Exception as e:
        return False, 0.0, 0.0, {}, str(e)

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
            [play_stop_btn, {"text": "🔄 Refresh Manual", "callback_data": "btn_refresh"}],
            [{"text": "📊 Status Bot & Posisi", "callback_data": "btn_status"}],
            [{"text": "📈 Laporan PnL & WinRate", "callback_data": "btn_report"}],
            [{"text": "⚡ Cek Harga Real-Time", "callback_data": "btn_price"}]
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
def get_home_text(is_final=False, is_daily_recap=False):
    success, idr_cash, total_equity, balances, err = fetch_realtime_account()
    if not success:
        return f"❌ *GAGAL KONEKSI API INDODAX:* `{err}`"

    now_wib = get_wib_time()
    total_wins = state["winning_trades"]
    total_losses = state["losing_trades"]
    stats_line = f"📈 *Statistik:* 🟢 {total_wins} Win | 🔴 {total_losses} Loss"

    pairs_display = ""
    for pair_key, pdata in state["pairs_data"].items():
        base = pdata["base"]
        amt = float(balances.get("balance", {}).get(base, 0)) + float(balances.get("balance_hold", {}).get(base, 0))
        val = amt * pdata["last_price"]
        chart_str = "".join(pdata["chart"])
        status_aktif = "Aktif ⚪" if state["is_running"] else "Berhenti ⚪"
        pos_str = f"Memegang Aset ({amt:.4f} {base.upper()})" if amt > 0 else f"IDR Ready (Rp {idr_cash:,.0f})"
        
        pairs_display += (
            f"♦️ *{pdata['name']}* 🟢 {status_aktif}\n"
            f"• Harga: Rp {pdata['last_price']:,.2f}\n"
            f"• Nilai: Rp {val:,.2f}\n"
            f"• Grafik: `{chart_str}`\n"
            f"• Posisi: {pos_str}\n\n"
        )

    if state["minute_logs"]:
        logs_str = "\n".join(state["minute_logs"])
        block_text = f"```\n{logs_str}\n```"
    else:
        block_text = "```\nMemantau market multi-pair...\n```"

    if is_daily_recap:
        return (
            f"🌙 *REKAP HARIAN OTOMATIS (00:00 WIB)*\n\n"
            f"💰 *Total Equity:* Rp {total_equity:,.2f} (IDR Tunai: Rp {idr_cash:,.2f})\n\n"
            f"{pairs_display}"
            f"{stats_line}\n"
            f"⏱ _Waktu Rekap: {now_wib} WIB_\n\n"
            f"📋 *RIWAYAT TRANSAKSI:*\n{block_text}"
        )

    if is_final:
        return (
            f"🤖 *BOT MULTI-PAIR INDODAX*\n\n"
            f"🏁 *REKAP SESI (SELESAI)*\n"
            f"💰 *Total Equity:* Rp {total_equity:,.2f}\n\n"
            f"{pairs_display}"
            f"{stats_line}\n"
            f"⏱ _Selesai: {now_wib} WIB_\n\n"
            f"📋 *RIWAYAT:*\n{block_text}"
        )

    return (
        f"{pairs_display}"
        f"{stats_line}\n"
        f"⏱ _Live Update: {now_wib} WIB_\n\n"
        f"📋 *RIWAYAT TRANSAKSI (SESI INI):*\n{block_text}\n\n"
        f"Pilih menu di bawah untuk mengelola bot:"
    )

# ==========================================
# LOOPS (AUTO-REFRESH & REKAP)
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

def daily_reset_loop():
    while True:
        now = get_wib_datetime()
        target = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        time.sleep((target - now).total_seconds())
        try:
            if state["dashboard_chat_id"]:
                recap_text = get_home_text(is_daily_recap=True)
                telegram("sendMessage", {
                    "chat_id": str(state["dashboard_chat_id"]),
                    "text": recap_text,
                    "parse_mode": "Markdown"
                })
        except Exception as e:
            print("DAILY RESET ERROR:", e)

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

                success, _, total_equity, _, _ = fetch_realtime_account()
                state["minute_start_equity"] = total_equity if success else 0.0
                state["minute_wins"] = 0
                state["minute_losses"] = 0
                state["minute_logs"].clear()
                add_log("Sesi baru dimulai.")

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
        except Exception as e:
            print("MINUTELY RESET ERROR:", e)

# ==========================================
# TRADING ENGINE
# ==========================================
def execute_real_order(pair, side, amount_idr=0, amount_base=0):
    url = "https://indodax.com/tapi"
    nonce = str(int(time.time() * 1000))
    params = {"method": "trade", "pair": pair, "type": side, "nonce": nonce}
    if side == "buy":
        params["idr"] = int(amount_idr)
    else:
        params[pair.replace("idr", "")] = f"{amount_base:.8f}"

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
    print("Engine Multi-Pair Trading Aktif...")
    while True:
        try:
            if state["is_running"]:
                success, idr_cash, total_equity, balances_data, err = fetch_realtime_account()
                if success:
                    balance_dict = balances_data.get("balance", {})
                    for pair_key, pdata in state["pairs_data"].items():
                        current_price = pdata["last_price"]
                        base = pdata["base"]
                        base_amt = float(balance_dict.get(base, 0))
                        
                        # Contoh logik sederhana per pair
                        if not pdata["in_position"] and base_amt * current_price < 10000:
                            if idr_cash > 50000:
                                add_log(f"[{pdata['name']}] Memantau peluang beli...")
                        elif base_amt > 0:
                            pdata["in_position"] = True
        except Exception as e:
            print("ENGINE ERROR:", e)
        time.sleep(3)

# ==========================================
# TELEGRAM HANDLERS
# ==========================================
def get_status_text():
    success, idr_cash, total_equity, _, _ = fetch_realtime_account()
    status_str = "Berjalan 🟢" if state["is_running"] else "Berhenti 🔴"
    return (
        f"📊 *STATUS BOT MULTI-PAIR*\n\n"
        f"• Status: {status_str}\n"
        f"• Total Equity: Rp {total_equity:,.2f}\n"
        f"• Saldo IDR Tunai: Rp {idr_cash:,.2f}\n"
        f"• Statistik: 🟢 {state['winning_trades']} Win | 🔴 {state['losing_trades']} Loss"
    )

def get_report_text():
    success, _, total_equity, _, _ = fetch_realtime_account()
    return (
        f"📈 *LAPORAN PERFORMA*\n\n"
        f"• Total Equity: Rp {total_equity:,.2f}\n"
        f"• Total Trade: {state['total_trades']}x\n"
        f"• Statistik: 🟢 {state['winning_trades']} Win | 🔴 {state['losing_trades']} Loss"
    )

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
            success, _, total_equity, _, _ = fetch_realtime_account()
            state["minute_start_equity"] = total_equity if success else 0.0
            add_log("Bot multi-pair diaktifkan.")
            answer_callback(cb_id, "▶️ Bot dijalankan.")
            update_menu(chat_id, msg_id, get_home_text(), is_home=True)
        elif data == "btn_stop":
            state["is_running"] = False
            add_log("Bot dihentikan.")
            answer_callback(cb_id, "⏹ Bot dihentikan.")
            update_menu(chat_id, msg_id, get_home_text(), is_home=True)
        elif data == "btn_refresh":
            answer_callback(cb_id, "🔄 Dashboard direfresh.")
            update_menu(chat_id, msg_id, get_home_text(), is_home=True)
        elif data == "btn_home":
            answer_callback(cb_id)
            update_menu(chat_id, msg_id, get_home_text(), is_home=True)
        elif data == "btn_status":
            answer_callback(cb_id)
            update_menu(chat_id, msg_id, get_status_text(), is_home=False)
        elif data == "btn_report":
            answer_callback(cb_id)
            update_menu(chat_id, msg_id, get_report_text(), is_home=False)
        elif data == "btn_price":
            answer_callback(cb_id)
            prices_text = "⚡ *HARGA REAL-TIME*\n\n"
            for pk, pd in state["pairs_data"].items():
                prices_text += f"• {pd['name']}: Rp {pd['last_price']:,.2f}\n"
            update_menu(chat_id, msg_id, prices_text, is_home=False)
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
    print("Polling Telegram Multi-Pair dimulai...")
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
    threading.Thread(target=daily_reset_loop, daemon=True).start()
    polling()
