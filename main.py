import os
import time
import threading
import urllib.request
import urllib.parse
import json
import hmac
import hashlib
from datetime import datetime, timezone, timedelta

import sys
sys.stdout.reconfigure(line_buffering=True)

WIB = timezone(timedelta(hours=7))

def get_wib_time():
    return datetime.now(WIB).strftime("%H:%M:%S")

def get_wib_datetime():
    return datetime.now(WIB)

# ==========================================
# CONFIGURATION
# ==========================================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8604634624:AAHKJaVhA3b7fGqOy66yxP9cOkehqwMbn5U")
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8026634236")

INDODAX_API_KEY = os.getenv("INDODAX_API_KEY", "JCHAJJYO-GERKVM4O-2IJLK5QY-2KO7MPFL-UOJTQD5S")
INDODAX_SECRET_KEY = os.getenv("INDODAX_SECRET_KEY", "6eecb43aefbf4796227bc664286d9a8c802698da9c316a1decef6f59ca9c5c5a6030cf3406cb6377")

FEE_RATE = float(os.getenv("FEE_RATE", 0.0021)) 
PAIRS = ["solidr", "usdtidr"]

# Global variable untuk menyimpan saldo utama asli dari Indodax
wallet_main_state = {
    "idr_balance": 0.0,
    "total_asset_equity": 0.0
}

coins_state = {}
for p in PAIRS:
    coins_state[p] = {
        "is_running": True,
        "asset_balance": 0.0,
        "in_position": False,
        "buy_price": 0.0,
        "winning_trades": 0,
        "losing_trades": 0,
        "total_profit_idr": 0.0,
        "total_loss_idr": 0.0,
        "logs": ["Bot diinisialisasi & terhubung ke Indodax."],
        "last_market_price": 0.0,
        "price_trend": "⏺",
        "chart_history": ["—", "—", "—", "—", "—", "—", "—", "—"]
    }

global_state = {
    "dashboard_msg_id": None,
    "dashboard_chat_id": ALLOWED_CHAT_ID if ALLOWED_CHAT_ID else None,
    "last_rendered_text": ""
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

def indodax_private_request(method_name, extra_params=None):
    """Menggunakan API V1 Indodax standar yang kompatibel untuk getInfo"""
    if not INDODAX_API_KEY or not INDODAX_SECRET_KEY:
        return None
    url = "https://indodax.com/tapi"
    nonce = str(int(time.time() * 1000))
    params = {
        "method": method_name,
        "nonce": nonce
    }
    if extra_params: 
        params.update(extra_params)
        
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
            raw_response = resp.read().decode("utf-8")
            return json.loads(raw_response)
    except Exception as e:
        print(f"API Error ({method_name}):", e)
        return None

def sync_real_wallet_balance():
    """Mengambil saldo utama IDR dan aset koin langsung dari akun Indodax"""
    res = indodax_private_request("getInfo")
    print("DEBUG RESPON INDODAX:", res)
    
    if res and res.get("success") == 1:
        ret = res.get("return", {})
        balances = ret.get("balance", {}) # Saldo IDR utama
        funds = ret.get("funds", {})      # Saldo koin
        
        # Ambil total saldo IDR utama (misal: 88,982)
        idr_total = float(balances.get("idr", 0))
        wallet_main_state["idr_balance"] = idr_total
        
        total_coins_val = 0.0
        for p in PAIRS:
            base_coin = p.replace("idr", "") # 'sol' atau 'usdt'
            coin_bal = float(funds.get(base_coin, 0))
            
            if coin_bal > 0:
                coins_state[p]["asset_balance"] = coin_bal
                coins_state[p]["in_position"] = True
            else:
                coins_state[p]["asset_balance"] = 0.0
                coins_state[p]["in_position"] = False
                
            total_coins_val += coins_state[p]["asset_balance"] * coins_state[p]["last_market_price"]
        
        # Total Estimasi Aset = Saldo IDR Utama + Nilai Aset Koin yang sedang di-hold
        wallet_main_state["total_asset_equity"] = idr_total + total_coins_val
        print(f"Sinkronisasi Berhasil! Saldo IDR Utama: Rp {idr_total:,.2f}")
    else:
        print("Gagal mengambil saldo dari Indodax, periksa izin API Key / Secret Key.")

def get_main_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "🔄 Refresh Dashboard", "callback_data": "btn_refresh"},
                {"text": "💰 Cek Saldo & P/L", "callback_data": "btn_check_pl"}
            ]
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
        global_state["dashboard_msg_id"] = res["result"]["message_id"]
        global_state["dashboard_chat_id"] = chat_id
        global_state["last_rendered_text"] = text
    return res

def update_menu(chat_id, message_id, text):
    global_state["dashboard_chat_id"] = chat_id
    global_state["last_rendered_text"] = text
    res = telegram("editMessageText", {
        "chat_id": str(chat_id),
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": get_main_keyboard()
    })
    if not res or not res.get("ok"):
        send_menu(chat_id, text)

def send_message_with_keyboard(chat_id, text):
    return telegram("sendMessage", {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": get_main_keyboard()
    })

def answer_callback(cb_id, text=None):
    payload = {"callback_query_id": cb_id}
    if text: payload["text"] = text
    return telegram("answerCallbackQuery", payload)

def fetch_price(pair):
    url = f"https://indodax.com/api/ticker/{pair}"
    st = coins_state[pair]
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "ticker" in data and "last" in data["ticker"]:
                new_price = float(data["ticker"]["last"])
                if new_price > 0:
                    if st["last_market_price"] > 0:
                        if new_price > st["last_market_price"]:
                            st["price_trend"] = "🔺"
                            char = "▇"
                        elif new_price < st["last_market_price"]:
                            st["price_trend"] = "🔻"
                            char = "▂"
                        else:
                            st["price_trend"] = "⏺"
                            char = "—"
                        st["chart_history"].append(char)
                        if len(st["chart_history"]) > 6: st["chart_history"].pop(0)
                    
                    st["last_market_price"] = new_price
                    return new_price
    except Exception as e:
        print(f"Fetch price error for {pair}:", e)
    return st["last_market_price"]

def get_indodax_style_dashboard():
    # Perbarui total nilai aset berdasarkan saldo utama + nilai koin
    total_coins_val = sum(st["asset_balance"] * st["last_market_price"] for st in coins_state.values())
    total_equity = wallet_main_state["idr_balance"] + total_coins_val
    
    total_wins = sum(st["winning_trades"] for st in coins_state.values())
    total_losses = sum(st["losing_trades"] for st in coins_state.values())
    now_wib = get_wib_time()

    text_blocks = [
        f"📊 *INDODAX LIVE DASHBOARD* 📊\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Estimasi Total Aset:* *Rp {total_equity:,.2f}*\n"
        f"📈 *Statistik:* 🟢 {total_wins} Win | 🔴 {total_losses} Loss\n\n"
        f"📦 *Rincian Pasar & Saldo (Real-Sync):*"
    ]

    for p in PAIRS:
        st = coins_state[p]
        price = st["last_market_price"]
        asset_val = st["asset_balance"] * price
        
        pair_display = "SOL/IDR" if p == "solidr" else ("USDT/IDR" if p == "usdtidr" else p.upper())
        pos_str = f"Hold ({st['asset_balance']:,.4f})" if st["in_position"] else f"IDR Ready (Rp {wallet_main_state['idr_balance']:,.0f})"
        chart_vis = "".join(st["chart_history"])

        text_blocks.append(
            f"\n🔹 *{pair_display}* [🟢 Aktif {st['price_trend']}]\n"
            f"   • Harga: Rp {price:,.2f}\n"
            f"   • Nilai: Rp {asset_val:,.2f}\n"
            f"   • Grafik: `{chart_vis}`\n"
            f"   • Posisi: {pos_str}"
        )

    all_logs = [f"[{p.upper()}] {lg}" for p in PAIRS for lg in coins_state[p]["logs"][-2:]]
    logs_str = "\n".join(all_logs) if all_logs else "Memantau pergerakan market..."

    text_blocks.append(f"\n📋 *LOG AKTIVITAS:*\n```{logs_str}```")
    text_blocks.append(f"━━━━━━━━━━━━━━━━━━━\n⏱ *Live Sync:* `{now_wib} WIB`")

    return "\n".join(text_blocks)

def get_pl_report_text():
    total_coins_val = sum(st["asset_balance"] * st["last_market_price"] for st in coins_state.values())
    total_equity = wallet_main_state["idr_balance"] + total_coins_val
    
    total_wins = sum(st["winning_trades"] for st in coins_state.values())
    total_losses = sum(st["losing_trades"] for st in coins_state.values())
    total_profit = sum(st["total_profit_idr"] for st in coins_state.values())
    total_loss = sum(st["total_loss_idr"] for st in coins_state.values())
    net_pl = total_profit - total_loss
    net_sign = "+" if net_pl >= 0 else ""

    return (
        f"💰 *LAPORAN SALDO & PROFIT/LOSS* 💰\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"• *Total Estimasi Saldo/Aset:* Rp {total_equity:,.2f}\n"
        f"• *Total Win:* {total_wins} Kali\n"
        f"• *Total Loss:* {total_losses} Kali\n"
        f"• *Akumulasi Profit:* +Rp {total_profit:,.2f}\n"
        f"• *Akumulasi Loss:* -Rp {total_loss:,.2f}\n"
        f"• *Net Result (P/L):* *{net_sign}Rp {net_pl:,.2f}*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ _Waktu Cek: {get_wib_time()} WIB_"
    )

def background_market_worker():
    while True:
        for p in PAIRS:
            fetch_price(p)
        
        if global_state["dashboard_chat_id"] and global_state["dashboard_msg_id"]:
            try:
                update_menu(global_state["dashboard_chat_id"], global_state["dashboard_msg_id"], get_indodax_style_dashboard())
            except Exception:
                pass
        time.sleep(5)

def daily_reset_worker():
    while True:
        now = get_wib_datetime()
        if now.hour == 0 and now.minute == 0 and now.second <= 5:
            if global_state["dashboard_chat_id"]:
                report = "🌙 *REKAP HARIAN OTOMATIS (00:00 WIB)* 🌙\n\n" + get_pl_report_text()
                send_message_with_keyboard(global_state["dashboard_chat_id"], report)
                
                for p in PAIRS:
                    coins_state[p]["winning_trades"] = 0
                    coins_state[p]["losing_trades"] = 0
                    coins_state[p]["total_profit_idr"] = 0.0
                    coins_state[p]["total_loss_idr"] = 0.0
            time.sleep(70)
        time.sleep(1)

def handle_update(update):
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        data = cb.get("data", "")

        if data == "btn_refresh":
            sync_real_wallet_balance()
            answer_callback(cb_id, "🔄 Saldo utama berhasil disinkronkan!")
            update_menu(chat_id, msg_id, get_indodax_style_dashboard())
        elif data == "btn_check_pl":
            answer_callback(cb_id, "Menampilkan Laporan...")
            send_message_with_keyboard(chat_id, get_pl_report_text())
        return

    if "message" in update:
        msg = update["message"]
        chat_id = msg.get("chat", {}).get("id")
        text = (msg.get("text") or "").strip()
        if not chat_id: return

        if text.startswith("/start") or text.startswith("/menu"):
            sync_real_wallet_balance()
            send_menu(chat_id, get_indodax_style_dashboard())
        elif text.startswith("/saldo") or text.startswith("/pl"):
            sync_real_wallet_balance()
            send_message_with_keyboard(chat_id, get_pl_report_text())

def polling():
    offset = None
    telegram("deleteWebhook", {"drop_pending_updates": "false"})
    print("Bot Telegram Berjalan dengan Saldo Utama Real-Sync...")
    while True:
        try:
            params = {"timeout": 20, "allowed_updates": json.dumps(["message", "callback_query"])}
            if offset is not None: params["offset"] = offset
            res = telegram("getUpdates", params)
            if res and res.get("ok"):
                for upd in res.get("result", []):
                    offset = upd["update_id"] + 1
                    handle_update(upd)
        except Exception as e:
            print("Polling Error:", e)
            time.sleep(2)

if __name__ == "__main__":
    sync_real_wallet_balance()
    for p in PAIRS:
        fetch_price(p)

    threading.Thread(target=background_market_worker, daemon=True).start()
    threading.Thread(target=daily_reset_worker, daemon=True).start()
    polling()
