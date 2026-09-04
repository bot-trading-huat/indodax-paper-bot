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
TOKEN = "8867024450:AAGaZU1bZgT7RQZLS9SRvUJr6wxTpUFinGs"
INDODAX_API_KEY = "FHKI0WWQ-CREFEVQM-4NYKVNHQ-1HAGNSL4-EL9NWIEK".strip()
INDODAX_SECRET_KEY = "431cdf95bf07326082fa4a271bd120b600f0cc13b4beca9248320a69de1ea3cec7e3961016f17d1b".strip()

# TARGET HARIAN & SAFETY LIMIT
DAILY_PROFIT_TARGET = 200000.0
MAX_DRAWDOWN_PCT = 0.03  
MIN_IDR_RESERVE = 15000.0 

global_state = {
    "dashboard_chat_id": None,
    "last_active_msg_id": None,
    "last_rendered_text": "",
    "is_resting": False,
    "rest_until": 0.0,
    "peak_equity": 0.0
}

pairs_state = {
    "bonkidr": {
        "name": "BONK/IDR",
        "symbol": "bonk",
        "is_running": True,
        "in_position": False,
        "buy_price": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "daily_profit_idr": 0.0,
        "last_market_price": 0.0,
        "price_trend": "⏺",
        "chart_chars": deque(["—"]*10, maxlen=10),
        "minute_logs": deque(["🔥 MODE BOT INDODAX AKTIF !!"], maxlen=4),
    },
    "usdtidr": {
        "name": "USDT/IDR",
        "symbol": "usdt",
        "is_running": True,
        "in_position": False,
        "buy_price": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "daily_profit_idr": 0.0,
        "last_market_price": 0.0,
        "price_trend": "⏺",
        "chart_chars": deque(["—"]*10, maxlen=10),
        "minute_logs": deque(["🔥 MODE BOT INDODAX AKTIF !!"], maxlen=4),
    }
}

def telegram(method, params=None):
    if not TOKEN: return None
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    try:
        data = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

def add_log(pair_key, text):
    timestamp = get_wib_time()
    p_logs = pairs_state[pair_key]["minute_logs"]
    if len(p_logs) == 0 or "MODE BOT" in p_logs[0]:
        p_logs.appendleft("MONITORING PASAR & EKSEKUSI TRADING...")
    p_logs.append(f"[{timestamp}] {text}")

def get_coin_price_in_idr(coin_symbol):
    pair = f"{coin_symbol.lower()}idr"
    try:
        ts = int(time.time() * 1000)
        url = f"https://indodax.com/api/ticker/{pair}?ts={ts}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return float(data.get("ticker", {}).get("last", 0))
    except Exception:
        return 0.0

def update_market_prices():
    for pair_key, p_data in pairs_state.items():
        try:
            price = get_coin_price_in_idr(p_data["symbol"])
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
                bonk_amt = float(balances.get("bonk", 0)) + float(balances_hold.get("bonk", 0))
                usdt_amt = float(balances.get("usdt", 0)) + float(balances_hold.get("usdt", 0))
                
                bonk_val = bonk_amt * pairs_state["bonkidr"]["last_market_price"]
                usdt_val = usdt_amt * pairs_state["usdtidr"]["last_market_price"]
                
                # Menghitung estimasi Rupiah untuk koin lain secara otomatis
                other_balances_list = []
                other_coins_total_val = 0.0

                all_keys = set(list(balances.keys()) + list(balances_hold.keys()))
                for coin in all_keys:
                    if coin in ["idr", "bonk", "usdt"]:
                        continue
                    total_coin = float(balances.get(coin, 0)) + float(balances_hold.get(coin, 0))
                    if total_coin > 0:
                        coin_price = get_coin_price_in_idr(coin)
                        coin_val_idr = total_coin * coin_price
                        other_coins_total_val += coin_val_idr
                        
                        if coin_val_idr > 0:
                            other_balances_list.append(f"{coin.upper()}: {total_coin:,.4f} (~Rp {coin_val_idr:,.0f})")
                        else:
                            other_balances_list.append(f"{coin.upper()}: {total_coin:,.4f}")

                # Total Estimasi Keseluruhan Aset
                grand_total = idr_cash + bonk_val + usdt_val + other_coins_total_val
                
                if grand_total > 1000:
                    if global_state["peak_equity"] == 0.0 or grand_total > global_state["peak_equity"]:
                        global_state["peak_equity"] = grand_total
                    
                return True, idr_cash, bonk_amt, usdt_amt, bonk_val, usdt_val, other_balances_list, grand_total, "OK"
            else:
                return False, 0.0, 0.0, 0.0, 0.0, 0.0, [], 0.0, res.get("error", "API Error")
    except Exception as e:
        return False, 0.0, 0.0, 0.0, 0.0, 0.0, [], 0.0, str(e)

def check_initial_positions():
    success, _, bonk_amt, usdt_amt, _, _, _, _, _ = fetch_realtime_account()
    if success:
        if bonk_amt > 1.0:
            pairs_state["bonkidr"]["in_position"] = True
            if pairs_state["bonkidr"]["buy_price"] == 0.0:
                pairs_state["bonkidr"]["buy_price"] = pairs_state["bonkidr"]["last_market_price"]
            add_log("bonkidr", f"Terdeteksi saldo BONK awal ({bonk_amt:,.2f}), posisi diset aktif.")
        
        if usdt_amt > 0.1:
            pairs_state["usdtidr"]["in_position"] = True
            if pairs_state["usdtidr"]["buy_price"] == 0.0:
                pairs_state["usdtidr"]["buy_price"] = pairs_state["usdtidr"]["last_market_price"]
            add_log("usdtidr", f"Terdeteksi saldo USDT awal ({usdt_amt:.2f}), posisi diset aktif.")

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
        params[symbol] = f"{amount_coin:.8f}" if symbol != "bonk" else f"{amount_coin:.2f}"

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
        with urllib.request.urlopen(req, timeout=4) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            if res.get("success") == 1:
                return True, res.get("return", {})
            return False, res.get("error", "Unknown Error")
    except Exception as e:
        return False, str(e)

def get_main_keyboard():
    bonk_running = pairs_state["bonkidr"]["is_running"]
    usdt_running = pairs_state["usdtidr"]["is_running"]
    
    return {
        "inline_keyboard": [
            [
                {"text": f"{'⏹ Hentikan BONK' if bonk_running else '▶️ Jalankan BONK'}", "callback_data": "toggle_bonkidr"},
                {"text": f"{'⏹ Hentikan USDT' if usdt_running else '▶️ Jalankan USDT'}", "callback_data": "toggle_usdtidr"}
            ],
            [{"text": "🔄 Paksa Sell/Cairkan Aset ke IDR", "callback_data": "btn_liquidate"}],
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

def get_home_text(is_final=False):
    success, idr_bal, bonk_amt, usdt_amt, bonk_val, usdt_val, other_list, total_equity, err = fetch_realtime_account()
    if not success:
        return f"❌ *GAGAL KONEKSI API INDODAX:* `{err}`"

    now_wib = get_wib_time()
    
    if global_state["is_resting"]:
        sisa_waktu = int(global_state["rest_until"] - time.time())
        if sisa_waktu > 0:
            header_status = f"☕ ISTIRAHAT COOLING DOWN ({sisa_waktu}s)"
        else:
            global_state["is_resting"] = False
            header_status = "🔥 BOT TRADING INDODAX AKTIF"
    else:
        header_status = "🏁 FINAL" if is_final else "🔥 BOT TRADING INDODAX AKTIF"

    total_prof_today = pairs_state["bonkidr"]["daily_profit_idr"] + pairs_state["usdtidr"]["daily_profit_idr"]
    target_progress = f"🎯 Profit Hari Ini: Rp {total_prof_today:,.0f} / Rp {DAILY_PROFIT_TARGET:,.0f}"

    other_text = f"\n • 📦 Koin Lain : {', '.join(other_list)}" if other_list else ""

    bonk_p = pairs_state["bonkidr"]
    bonk_status = "🟢 Aktif" if bonk_p["is_running"] else "🔴 Berhenti"
    bonk_price = bonk_p["last_market_price"]
    bonk_chart = "".join(bonk_p["chart_chars"])
    bonk_pos = f"Aset Koin ({bonk_amt:,.2f} BONK)" if bonk_p["in_position"] else f"IDR Ready (Rp {idr_bal:,.0f})"
    bonk_logs = "\n".join(bonk_p["minute_logs"])

    usdt_p = pairs_state["usdtidr"]
    usdt_status = "🟢 Aktif" if usdt_p["is_running"] else "🔴 Berhenti"
    usdt_price = usdt_p["last_market_price"]
    usdt_chart = "".join(usdt_p["chart_chars"])
    usdt_pos = f"Aset Koin ({usdt_amt:,.2f} USDT)" if usdt_p["in_position"] else f"USDT Ready ({usdt_amt:,.2f} USDT)"
    usdt_logs = "\n".join(usdt_p["minute_logs"])

    return (
        f"{header_status}\n"
        f"💰 **TOTAL ESTIMASI SALDO INDODAX:** Rp {total_equity:,.2f}\n"
        f"💼 **RINCIAN SELURUH ASET:**\n"
        f" • 💵 Saldo IDR Tunai : Rp {idr_bal:,.2f}\n"
        f" • 🪙 Aset BONK       : Rp {bonk_val:,.2f} ({bonk_amt:,.2f} BONK)\n"
        f" • 💵 Aset USDT       : Rp {usdt_val:,.2f} ({usdt_amt:,.2f} USDT)"
        f"{other_text}\n"
        f"{target_progress}\n"
        f"Jam : ⏱ {now_wib}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"1️⃣ BONK/IDR | {bonk_p['price_trend']}\n"
        f"Status: {bonk_status}\n"
        f"• Harga: Rp {bonk_price:,.4f}\n"
        f"• Aset: Rp {bonk_val:,.2f} ({bonk_amt:,.2f} BONK)\n"
        f"• Grafik: {bonk_chart}\n"
        f"• Posisi: {bonk_pos}\n"
        f"📊 REKAP BONK: Trade: {bonk_p['total_trades']}x | Win: {bonk_p['winning_trades']} | Lose: {bonk_p['losing_trades']}\n"
        f"📋 LOG BONK:\n"
        f"```text\n{bonk_logs}\n```\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"2️⃣ USDT/IDR | {usdt_p['price_trend']}\n"
        f"Status: {usdt_status}\n"
        f"• Harga: Rp {usdt_price:,.2f}\n"
        f"• Aset: {usdt_amt:,.2f} USDT (Rp {usdt_val:,.2f})\n"
        f"• Grafik: {usdt_chart}\n"
        f"• Posisi: {usdt_pos}\n"
        f"📊 REKAP USDT: Trade: {usdt_p['total_trades']}x | Win: {usdt_p['winning_trades']} | Lose: {usdt_p['losing_trades']}\n"
        f"📋 LOG USDT:\n"
        f"```text\n{usdt_logs}\n```"
    )

def auto_refresh_dashboard_loop():
    while True:
        try:
            update_market_prices()
            if global_state["is_resting"]:
                time.sleep(5)
                continue

            if global_state["dashboard_chat_id"] and global_state["last_active_msg_id"]:
                new_text = get_home_text(is_final=False)
                if new_text != global_state["last_rendered_text"]:
                    res = telegram("editMessageText", {
                        "chat_id": str(global_state["dashboard_chat_id"]),
                        "message_id": global_state["last_active_msg_id"],
                        "text": new_text,
                        "parse_mode": "Markdown",
                        "reply_markup": get_main_keyboard()
                    })
                    if res and res.get("ok"):
                        global_state["last_rendered_text"] = new_text
        except Exception as e:
            print("Auto Refresh Error:", e)
        time.sleep(2)

def minute_report_worker():
    while True:
        time.sleep(60)
        if global_state["is_resting"]:
            continue

        if global_state["dashboard_chat_id"] and global_state["last_active_msg_id"]:
            try:
                final_text = get_home_text(is_final=True)
                telegram("editMessageText", {
                    "chat_id": str(global_state["dashboard_chat_id"]),
                    "message_id": global_state["last_active_msg_id"],
                    "text": final_text,
                    "parse_mode": "Markdown"
                })

                new_live_text = get_home_text(is_final=False)
                res = telegram("sendMessage", {
                    "chat_id": str(global_state["dashboard_chat_id"]),
                    "text": new_live_text,
                    "parse_mode": "Markdown",
                    "reply_markup": get_main_keyboard()
                })
                if res and res.get("ok"):
                    global_state["last_active_msg_id"] = res["result"]["message_id"]
                    global_state["last_rendered_text"] = new_live_text
            except Exception as e:
                print("Minute Report Worker Error:", e)

def daily_midnight_report_worker():
    while True:
        now = datetime.now(WIB)
        if now.hour == 0 and now.minute == 0:
            if global_state["dashboard_chat_id"]:
                b = pairs_state["bonkidr"]
                u = pairs_state["usdtidr"]
                total_win = b['winning_trades'] + u['winning_trades']
                total_lose = b['losing_trades'] + u['losing_trades']
                total_trades = b['total_trades'] + u['total_trades']
                total_daily_profit = b['daily_profit_idr'] + u['daily_profit_idr']

                status_target = "✅ TARGET HARI INI TERCAPAI!" if total_daily_profit >= DAILY_PROFIT_TARGET else "⚠️ BELUM MENCAPAI TARGET"

                report_msg = (
                    f"🌙 *REKAP HARIAN (00:00 WIB)*\n"
                    f"📅 Tanggal: {now.strftime('%d-%m-%Y')}\n\n"
                    f"• Total Trade: {total_trades}x\n"
                    f"• Win: {total_win} | Lose: {total_lose}\n"
                    f"• **Total Profit: Rp {total_daily_profit:,.2f}**\n"
                    f"• Status: {status_target}\n\n"
                    f"_Bot mereset siklus profit untuk hari baru! Gas terus!_"
                )
                telegram("sendMessage", {
                    "chat_id": str(global_state["dashboard_chat_id"]),
                    "text": report_msg,
                    "parse_mode": "Markdown"
                })
                b['daily_profit_idr'] = 0.0
                u['daily_profit_idr'] = 0.0
                b['total_trades'] = 0; b['winning_trades'] = 0; b['losing_trades'] = 0
                u['total_trades'] = 0; u['winning_trades'] = 0; u['losing_trades'] = 0
                global_state["peak_equity"] = 0.0
            time.sleep(65)
        time.sleep(15)

def pair_trading_worker(pair_key):
    p_data = pairs_state[pair_key]

    while True:
        try:
            if global_state["is_resting"]:
                if time.time() >= global_state["rest_until"]:
                    global_state["is_resting"] = False
                    add_log(pair_key, "Selesai istirahat 2 menit. Bot aktif kembali!")
                    success, _, _, _, _, _, _, current_eq, _ = fetch_realtime_account()
                    if success and current_eq > 1000:
                        global_state["peak_equity"] = current_eq
                else:
                    time.sleep(5)
                    continue

            if p_data["is_running"]:
                success, idr_cash, bonk_amt, usdt_amt, _, _, _, current_equity, err = fetch_realtime_account()
                current_price = p_data["last_market_price"]

                if global_state["peak_equity"] > 1000 and current_equity > 1000:
                    if current_equity < global_state["peak_equity"]:
                        drawdown = (global_state["peak_equity"] - current_equity) / global_state["peak_equity"]
                        if drawdown >= MAX_DRAWDOWN_PCT:
                            global_state["is_resting"] = True
                            global_state["rest_until"] = time.time() + 120  
                            
                            if p_data["in_position"]:
                                target_amt = bonk_amt if pair_key == "bonkidr" else usdt_amt
                                min_check = 1.0 if pair_key == "bonkidr" else 0.00001
                                if target_amt > min_check:
                                    execute_real_order(pair_key, "sell", amount_coin=target_amt)
                                    p_data["in_position"] = False
                            
                            add_log(pair_key, f"⚠️ DRAWDOWN {drawdown*100:.2f}%! Istirahat 2 menit.")
                            time.sleep(5)
                            continue

                if success and current_price > 0:
                    if not p_data["in_position"]:
                        allowed_buy_idr = idr_cash - MIN_IDR_RESERVE
                        if allowed_buy_idr >= 10000:
                            add_log(pair_key, f"BUY dengan dana Rp {allowed_buy_idr:,.0f}...")
                            success_order, res_data = execute_real_order(pair_key, "buy", amount_idr=allowed_buy_idr)
                            if success_order:
                                p_data["buy_price"] = current_price
                                p_data["in_position"] = True
                                add_log(pair_key, f"BUY SUKSES @ Rp {current_price:,.4f}")
                            else:
                                add_log(pair_key, f"Gagal Buy: {res_data}")

                    elif p_data["in_position"]:
                        if p_data["buy_price"] <= 0:
                            p_data["buy_price"] = current_price

                        price_change_pct = (current_price - p_data["buy_price"]) / p_data["buy_price"]

                        if price_change_pct >= 0.003 or price_change_pct <= -0.005:
                            success, _, current_bonk, current_usdt, _, _, _, _, _ = fetch_realtime_account()
                            target_amt = current_bonk if pair_key == "bonkidr" else current_usdt
                            min_check = 1.0 if pair_key == "bonkidr" else 0.00001
                            
                            if target_amt > min_check:
                                add_log(pair_key, f"Mencoba SELL ({price_change_pct*100:.2f}%)")
                                success_order, res_data = execute_real_order(pair_key, "sell", amount_coin=target_amt)
                                if success_order:
                                    p_data["in_position"] = False
                                    p_data["total_trades"] += 1
                                    
                                    trade_profit = (current_price - p_data["buy_price"]) * target_amt
                                    if price_change_pct > 0:
                                        p_data["winning_trades"] += 1
                                        p_data["daily_profit_idr"] += abs(trade_profit)
                                        add_log(pair_key, f"SELL PROFIT 🔺 (+{price_change_pct*100:.2f}%)")
                                    else:
                                        p_data["losing_trades"] += 1
                                        p_data["daily_profit_idr"] -= abs(trade_profit)
                                        add_log(pair_key, f"SELL LOSS 🔻 ({price_change_pct*100:.2f}%)")
                                else:
                                    add_log(pair_key, f"Gagal Sell: {res_data}")
        except Exception as e:
            print(f"ENGINE ERROR {pair_key}:", e)
        time.sleep(2)

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
        global_state["last_active_msg_id"] = msg_id
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
        global_state["last_active_msg_id"] = res["result"]["message_id"]
        global_state["last_rendered_text"] = text

def handle_update(update):
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        data = cb.get("data", "")

        if data == "toggle_bonkidr":
            p = pairs_state["bonkidr"]
            p["is_running"] = not p["is_running"]
            add_log("bonkidr", f"Bot BONK {'diaktifkan' if p['is_running'] else 'dihentikan'}.")
            answer_callback(cb_id, f"BONK Bot: {'Aktif' if p['is_running'] else 'Berhenti'}")
            update_menu(chat_id, msg_id, get_home_text(is_final=False), is_home=True)
            
        elif data == "toggle_usdtidr":
            p = pairs_state["usdtidr"]
            p["is_running"] = not p["is_running"]
            add_log("usdtidr", f"Bot USDT {'diaktifkan' if p['is_running'] else 'dihentikan'}.")
            answer_callback(cb_id, f"USDT Bot: {'Aktif' if p['is_running'] else 'Berhenti'}")
            update_menu(chat_id, msg_id, get_home_text(is_final=False), is_home=True)

        elif data == "btn_liquidate":
            answer_callback(cb_id, "Memaksa cairkan seluruh aset ke IDR...")
            success, _, bonk_amt, usdt_amt, _, _, _, _, _ = fetch_realtime_account()
            if bonk_amt > 1.0:
                execute_real_order("bonkidr", "sell", amount_coin=bonk_amt)
            if usdt_amt > 0.00001:
                execute_real_order("usdtidr", "sell", amount_coin=usdt_amt)
            update_menu(chat_id, msg_id, get_home_text(is_final=False), is_home=True)
            
        elif data == "btn_home":
            global_state["is_resting"] = False
            answer_callback(cb_id, "Dashboard diperbarui!")
            update_menu(chat_id, msg_id, get_home_text(is_final=False), is_home=True)
            
        elif data == "btn_status":
            answer_callback(cb_id)
            success, idr, bonk, usdt, bonk_val, usdt_val, other_list, eq, _ = fetch_realtime_account()
            other_str = f"\n• Koin Lain: {', '.join(other_list)}" if other_list else ""
            status_text = (
                f"📊 *STATUS & SALDO AKUN LENGKAP*\n\n"
                f"• IDR Tunai: Rp {idr:,.2f}\n"
                f"• Saldo BONK: {bonk:,.2f} BONK (Rp {bonk_val:,.2f})\n"
                f"• Saldo USDT: {usdt:,.2f} USDT (Rp {usdt_val:,.2f})"
                f"{other_str}\n\n"
                f"• **TOTAL ESTIMASI SALDO: Rp {eq:,.2f}**\n"
                f"• **Peak Equity Hari Ini:** Rp {global_state['peak_equity']:,.2f}"
            )
            update_menu(chat_id, msg_id, status_text, is_home=False)
            
        elif data == "btn_report":
            answer_callback(cb_id)
            b = pairs_state["bonkidr"]
            u = pairs_state["usdtidr"]
            total_prof = b['daily_profit_idr'] + u['daily_profit_idr']
            report_text = (
                f"📈 *LAPORAN TARGET PROFIT HARIAN*\n\n"
                f"• Target Wajib: Rp {DAILY_PROFIT_TARGET:,.2f}\n"
                f"• Profit Tercapai: Rp {total_prof:,.2f}\n"
                f"• Status: {'TERCAPAI 🎉' if total_prof >= DAILY_PROFIT_TARGET else 'BELUM TERCAPAI ⚠️'}\n\n"
                f"**BONK/IDR:** Trade: {b['total_trades']}x | Win: {b['winning_trades']} | Lose: {b['losing_trades']}\n"
                f"**USDT/IDR:** Trade: {u['total_trades']}x | Win: {u['winning_trades']} | Lose: {u['losing_trades']}"
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
            global_state["is_resting"] = False
            send_menu(chat_id, get_home_text(is_final=False))

def polling():
    offset = None
    telegram("deleteWebhook", {"drop_pending_updates": "false"})
    print("Bot Indodax Berjalan...")
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
            time.sleep(3)

if __name__ == "__main__":
    update_market_prices()
    check_initial_positions()

    threading.Thread(target=pair_trading_worker, args=("bonkidr",), daemon=True).start()
    threading.Thread(target=pair_trading_worker, args=("usdtidr",), daemon=True).start()
    threading.Thread(target=auto_refresh_dashboard_loop, daemon=True).start()
    threading.Thread(target=minute_report_worker, daemon=True).start()
    threading.Thread(target=daily_midnight_report_worker, daemon=True).start()
    polling()
