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
# KONFIGURASI API & TOKEN
# ==========================================
TOKEN = "8604634624:AAHKJaVhA3b7fGqOy66yxP9cOkehqwMbn5U"
INDODAX_API_KEY = "FHKI0WWQ-CREFEVQM-4NYKVNHQ-1HAGNSL4-EL9NWIEK".strip()
INDODAX_SECRET_KEY = "431cdf95bf07326082fa4a271bd120b600f0cc13b4beca9248320a69de1ea3cec7e3961016f17d1b".strip()

pairs_state = {
    "btcidr": {
        "name": "BTC/IDR",
        "symbol": "btc",
        "is_running": False,
        "in_position": False,
        "buy_price": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "last_market_price": 0.0,
        "price_trend": "⏺",
        "chart_chars": deque(["—"]*10, maxlen=10),
        "minute_logs": deque(["SEMOGA GACOR !!"], maxlen=4),
    },
    "usdtidr": {
        "name": "USDT/IDR",
        "symbol": "usdt",
        "is_running": False,
        "in_position": False,
        "buy_price": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "last_market_price": 0.0,
        "price_trend": "⏺",
        "chart_chars": deque(["—"]*10, maxlen=10),
        "minute_logs": deque(["SEMOGA GACOR !!"], maxlen=4),
    }
}

global_state = {
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

def add_log(pair_key, text):
    timestamp = get_wib_time()
    # Pastikan SEMOGA GACOR !! tetap di awal, log baru masuk di bawahnya
    p_logs = pairs_state[pair_key]["minute_logs"]
    if "SEMOGA GACOR !!" not in p_logs:
        p_logs.appendleft("SEMOGA GACOR !!")
    p_logs.append(f"[{timestamp}] {text}")

def update_market_prices():
    for pair_key, p_data in pairs_state.items():
        try:
            ts = int(time.time() * 1000)
            url = f"https://indodax.com/api/ticker/{pair_key}?ts={ts}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                price = float(data.get("ticker", {}).get("last", 0))
                
                if price > 0:
                    old_price = p_data["last_market_price"]
                    if old_price > 0:
                        if price > old_price:
                            p_data["price_trend"] = "🔺"
                            char = "▇"
                        elif price < old_price:
                            p_data["price_trend"] = "🔻"
                            char = "▂"
                        else:
                            p_data["price_trend"] = "⏺️"
                            char = "—"
                    else:
                        char = "—"
                    
                    p_data["chart_chars"].append(char)
                    p_data["last_market_price"] = price
        except Exception:
            pass

def fetch_realtime_account():
    update_market_prices()
    
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
                usdt_amt = float(balances.get("usdt", 0)) + float(balances_hold.get("usdt", 0))
                
                btc_val = btc_amt * pairs_state["btcidr"]["last_market_price"]
                usdt_val = usdt_amt * pairs_state["usdtidr"]["last_market_price"]
                
                grand_total = idr_cash + btc_val + usdt_val
                return True, idr_cash, btc_amt, usdt_amt, grand_total, "OK"
            else:
                return False, 0.0, 0.0, 0.0, 0.0, res.get("error", "API Error")
    except Exception as e:
        return False, 0.0, 0.0, 0.0, 0.0, str(e)

def execute_real_order(pair_key, side, amount_idr=0, amount_coin=0):
    url = "https://indodax.com/tapi"
    nonce = str(int(time.time() * 1000))
    params = {
        "method": "trade",
        "pair": pair_key,
        "type": side,
        "nonce": nonce
    }
    if side == "buy":
        params["idr"] = int(amount_idr)
    else:
        symbol = pairs_state[pair_key]["symbol"]
        params[symbol] = f"{amount_coin:.8f}"

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

def auto_split_and_convert_balance():
    time.sleep(2)
    success, idr_cash, _, usdt_amt, _, err = fetch_realtime_account()
    if not success:
        return

    if usdt_amt < 1.0 and idr_cash > 50000:
        target_conversion_idr = (idr_cash / 2) * 0.995
        add_log("usdtidr", f"Otomatis membagi & menukar separuh IDR ke USDT...")
        success_order, res_data = execute_real_order("usdtidr", "buy", amount_idr=target_conversion_idr)
        if success_order:
            add_log("usdtidr", "Pembagian saldo ke USDT Berhasil!")
        else:
            add_log("usdtidr", f"Gagal konversi: {res_data}")

def get_main_keyboard():
    btc_running = pairs_state["btcidr"]["is_running"]
    usdt_running = pairs_state["usdtidr"]["is_running"]
    
    return {
        "inline_keyboard": [
            [
                {"text": f"{'⏹ Hentikan BTC' if btc_running else '▶️ Jalankan BTC'}", "callback_data": "toggle_btcidr"},
                {"text": f"{'⏹ Hentikan USDT' if usdt_running else '▶️ Jalankan USDT'}", "callback_data": "toggle_usdtidr"}
            ],
            [{"text": "🔄 Bagi/Pindahkan Saldo ke USDT", "callback_data": "btn_split_usdt"}],
            [{"text": "📊 Status Lengkap & Saldo", "callback_data": "btn_status"}],
            [{"text": "📈 Laporan Performa Global", "callback_data": "btn_report"}]
        ]
    }

def get_back_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🏠 Kembali ke Dashboard", "callback_data": "btn_home"}]
        ]
    }

def get_home_text():
    success, idr_bal, btc_amt, usdt_amt, total_equity, err = fetch_realtime_account()
    if not success:
        return f"❌ *GAGAL KONEKSI API INDODAX:* `{err}`"

    now_wib = get_wib_time()

    # 1. DATA BTC
    btc_p = pairs_state["btcidr"]
    btc_status = "🟢 Aktif" if btc_p["is_running"] else "🔴 Berhenti"
    btc_price = btc_p["last_market_price"]
    btc_chart = "".join(btc_p["chart_chars"])
    btc_val = btc_amt * btc_price
    btc_pos = f"Memegang Aset ({btc_amt:.6f} BTC)" if btc_p["in_position"] else f"IDR Ready (Rp {idr_bal:,.0f})"
    btc_logs = "\n".join(btc_p["minute_logs"])

    # 2. DATA USDT
    usdt_p = pairs_state["usdtidr"]
    usdt_status = "🟢 Aktif" if usdt_p["is_running"] else "🔴 Berhenti"
    usdt_price = usdt_p["last_market_price"]
    usdt_chart = "".join(usdt_p["chart_chars"])
    usdt_val = usdt_amt * usdt_price
    usdt_pos = f"Memegang Aset ({usdt_amt:,.2f} USDT)" if usdt_p["in_position"] else f"USDT Ready ({usdt_amt:,.2f} USDT)"
    usdt_logs = "\n".join(usdt_p["minute_logs"])

    return (
        f"💰 TOTAL EQUITY: Rp {total_equity:,.2f}\n"
        f"Jam : ⏱ {now_wib}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"1️⃣ BTC/IDR | {btc_p['price_trend']}\n"
        f"Status: {btc_status}\n"
        f"• Harga: Rp {btc_price:,.2f}\n"
        f"• Aset: Rp {btc_val:,.2f} ({btc_amt:.6f} BTC)\n"
        f"• Grafik: {btc_chart}\n"
        f"• Posisi: {btc_pos}\n"
        f"📊 REKAP BTC: Trade: {btc_p['total_trades']}x | Win: {btc_p['winning_trades']} | Lose: {btc_p['losing_trades']}\n"
        f"📋 LOG BTC:\n"
        f"```{btc_logs}```\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"2️⃣ USDT/IDR | {usdt_p['price_trend']}\n"
        f"Status: {usdt_status}\n"
        f"• Harga: Rp {usdt_price:,.2f}\n"
        f"• Aset: {usdt_amt:,.2f} USDT (Rp {usdt_val:,.2f})\n"
        f"• Grafik: {usdt_chart}\n"
        f"• Posisi: {usdt_pos}\n"
        f"📊 REKAP USDT: Trade: {usdt_p['total_trades']}x | Win: {usdt_p['winning_trades']} | Lose: {usdt_p['losing_trades']}\n"
        f"📋 LOG USDT:\n"
        f"```{usdt_logs}```"
    )

def auto_refresh_dashboard_loop():
    while True:
        try:
            update_market_prices()
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
        time.sleep(1)

def pair_trading_worker(pair_key):
    p_data = pairs_state[pair_key]
    highest_price = 0.0

    while True:
        try:
            if p_data["is_running"]:
                success, idr_cash, btc_amt, usdt_amt, _, err = fetch_realtime_account()
                current_price = p_data["last_market_price"]

                if success and current_price > 0:
                    if not p_data["in_position"]:
                        if pair_key == "btcidr" and idr_cash >= 20000:
                            buy_idr = (idr_cash / 2) * 0.995
                            add_log(pair_key, f"Mencoba BUY BTC dg Rp {buy_idr:,.0f}...")
                            success_order, res_data = execute_real_order(pair_key, "buy", amount_idr=buy_idr)
                            if success_order:
                                p_data["buy_price"] = current_price
                                highest_price = current_price
                                p_data["in_position"] = True
                                add_log(pair_key, f"BUY BERHASIL @ Rp {current_price:,.0f}")
                        elif pair_key == "usdtidr" and usdt_amt >= 2.0:
                            add_log(pair_key, f"Bot USDT siap bekerja...")

                    elif p_data["in_position"]:
                        if current_price > highest_price:
                            highest_price = current_price

                        price_change_pct = (current_price - p_data["buy_price"]) / p_data["buy_price"]
                        if price_change_pct >= 0.008 or price_change_pct <= -0.015:
                            success, _, current_btc, current_usdt, _, _ = fetch_realtime_account()
                            target_amt = current_btc if pair_key == "btcidr" else current_usdt
                            
                            if target_amt > 0.0001:
                                success_order, res_data = execute_real_order(pair_key, "sell", amount_coin=target_amt)
                                if success_order:
                                    p_data["in_position"] = False
                                    p_data["total_trades"] += 1
                                    if price_change_pct > 0:
                                        p_data["winning_trades"] += 1
                                        add_log(pair_key, f"SELL PROFIT 🔺 (+{price_change_pct*100:.2f}%)")
                                    else:
                                        p_data["losing_trades"] += 1
                                        add_log(pair_key, f"SELL LOSS 🔻 ({price_change_pct*100:.2f}%)")
                                    highest_price = 0.0
        except Exception as e:
            print(f"ENGINE ERROR {pair_key}:", e)
        time.sleep(5)

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
        global_state["dashboard_chat_id"] = chat_id
        global_state["dashboard_msg_id"] = msg_id
        global_state["last_rendered_text"] = text

def send_menu(chat_id, text):
    res = telegram("sendMessage", {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": get_main_keyboard()
    })
    if res and res.get("ok"):
        global_state["dashboard_chat_id"] = chat_id
        global_state["dashboard_msg_id"] = res["result"]["message_id"]
        global_state["last_rendered_text"] = text

def handle_update(update):
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        data = cb.get("data", "")

        if data == "toggle_btcidr":
            p = pairs_state["btcidr"]
            p["is_running"] = not p["is_running"]
            add_log("btcidr", f"Bot BTC {'diaktifkan' if p['is_running'] else 'dihentikan'}.")
            answer_callback(cb_id, f"BTC Bot: {'Aktif' if p['is_running'] else 'Berhenti'}")
            update_menu(chat_id, msg_id, get_home_text(), is_home=True)
            
        elif data == "toggle_usdtidr":
            p = pairs_state["usdtidr"]
            p["is_running"] = not p["is_running"]
            add_log("usdtidr", f"Bot USDT {'diaktifkan' if p['is_running'] else 'dihentikan'}.")
            answer_callback(cb_id, f"USDT Bot: {'Aktif' if p['is_running'] else 'Berhenti'}")
            update_menu(chat_id, msg_id, get_home_text(), is_home=True)

        elif data == "btn_split_usdt":
            answer_callback(cb_id, "Memproses pemindahan saldo ke USDT...")
            success, idr_cash, _, _, _, _ = fetch_realtime_account()
            if idr_cash > 20000:
                half_idr = (idr_cash / 2) * 0.995
                success_order, res_data = execute_real_order("usdtidr", "buy", amount_idr=half_idr)
                if success_order:
                    add_log("usdtidr", f"Sukses memindahkan saldo ke USDT!")
                else:
                    add_log("usdtidr", f"Gagal pindah saldo: {res_data}")
            update_menu(chat_id, msg_id, get_home_text(), is_home=True)
            
        elif data == "btn_home":
            answer_callback(cb_id)
            update_menu(chat_id, msg_id, get_home_text(), is_home=True)
            
        elif data == "btn_status":
            answer_callback(cb_id)
            success, idr, btc, usdt, eq, _ = fetch_realtime_account()
            status_text = (
                f"📊 *STATUS & SALDO AKUN LENGKAP*\n\n"
                f"• IDR Tunai: Rp {idr:,.2f}\n"
                f"• Saldo BTC: {btc:.6f} BTC\n"
                f"• Saldo USDT: {usdt:,.2f} USDT\n"
                f"• **TOTAL KESELURUHAN (EQUITY): Rp {eq:,.2f}**"
            )
            update_menu(chat_id, msg_id, status_text, is_home=False)
            
        elif data == "btn_report":
            answer_callback(cb_id)
            b = pairs_state["btcidr"]
            u = pairs_state["usdtidr"]
            report_text = (
                f"📈 *LAPORAN PERFORMA GLOBAL*\n\n"
                f"**BTC/IDR:**\n- Total Trade: {b['total_trades']}\n- Win: {b['winning_trades']} | Lose: {b['losing_trades']}\n\n"
                f"**USDT/IDR:**\n- Total Trade: {u['total_trades']}\n- Win: {u['winning_trades']} | Lose: {u['losing_trades']}"
            )
            update_menu(chat_id, msg_id, report_text, is_home=False)
        else:
            answer_callback(cb_id)
        return

    if "message" in update:
        msg = update["message"]
        chat_id = msg.get("chat", {}).get("id")
        text = (msg.get("text") or "").strip()
        if chat_id and (text.startswith("/start") or text.startswith("/menu")):
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
    threading.Thread(target=auto_split_and_convert_balance, daemon=True).start()
    threading.Thread(target=pair_trading_worker, args=("btcidr",), daemon=True).start()
    threading.Thread(target=pair_trading_worker, args=("usdtidr",), daemon=True).start()
    threading.Thread(target=auto_refresh_dashboard_loop, daemon=True).start()
    polling()
