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

class IndodaxScalpingBot:
    def __init__(self, pair="btcidr", coin_symbol="btc"):
        # ==========================================
        # KONFIGURASI PASAR & API
        # ==========================================
        self.TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8604634624:AAHKJaVhA3b7fGqOy66yxP9cOkehqwMbn5U")
        self.INDODAX_API_KEY = os.getenv("INDODAX_API_KEY", "FHKI0WWQ-CREFEVQM-4NYKVNHQ-1HAGNSL4-EL9NWIEK").strip()
        self.INDODAX_SECRET_KEY = os.getenv("INDODAX_SECRET_KEY", "431cdf95bf07326082fa4a271bd120b600f0cc13b4beca9248320a69de1ea3cec7e3961016f17d1b").strip()
        
        self.PAIR = pair          # contoh: "btcidr" atau "ethidr"
        self.COIN_SYMBOL = coin_symbol # contoh: "btc" atau "eth"

        self.state = {
            "is_running": False,
            "in_position": False,
            "buy_price": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            
            # Grafik & Tren
            "last_market_price": 0.0,
            "price_trend": "⏺",
            
            # Sesi per 1 menit
            "minute_start_equity": 0.0,
            "minute_wins": 0,
            "minute_losses": 0,
            "minute_logs": deque([f"Bot {self.PAIR.upper()} disiapkan, menunggu start..."], maxlen=8),
            
            # Dashboard Tracking
            "dashboard_chat_id": None,
            "dashboard_msg_id": None,
            "last_rendered_text": ""
        }

        self.chart_chars = deque(maxlen=10)

    def telegram(self, method, params=None):
        if not self.TOKEN: return None
        url = f"https://api.telegram.org/bot{self.TOKEN}/{method}"
        try:
            data = json.dumps(params or {}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def add_log(self, text):
        timestamp = get_wib_time()
        log_line = f"[{timestamp}] {text}"
        self.state["minute_logs"].append(log_line)

    def get_market_price(self):
        """Mengambil harga pasar spesifik untuk bot ini"""
        price = 0.0
        try:
            ts = int(time.time() * 1000)
            url = f"https://indodax.com/api/ticker/{self.PAIR}?ts={ts}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                price = float(data.get("ticker", {}).get("last", 0))

            if price > 0:
                if self.state["last_market_price"] > 0:
                    if price > self.state["last_market_price"]:
                        self.state["price_trend"] = "🔺"
                        char = "▇"
                    elif price < self.state["last_market_price"]:
                        self.state["price_trend"] = "🔻"
                        char = "▂"
                    else:
                        self.state["price_trend"] = "⏺"
                        char = "—"
                else:
                    char = "—"
                self.chart_chars.append(char)
                self.state["last_market_price"] = price
        except Exception:
            if self.state["last_market_price"] > 0:
                price = self.state["last_market_price"]
        return price

    def generate_block_chart(self):
        if not self.chart_chars:
            return "——————————"
        return "".join(self.chart_chars)

    def fetch_realtime_account(self):
        current_price = self.get_market_price()
        
        url = "https://indodax.com/tapi"
        nonce = str(int(time.time() * 1000))
        params = {"method": "getInfo", "nonce": nonce}
        
        post_data = urllib.parse.urlencode(params).encode("utf-8")
        sign = hmac.new(self.INDODAX_SECRET_KEY.encode('utf-8'), post_data, hashlib.sha512).hexdigest()
        headers = {
            "Key": self.INDODAX_API_KEY,
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
                    coin_amt = float(balances.get(self.COIN_SYMBOL, 0)) + float(balances_hold.get(self.COIN_SYMBOL, 0))
                    
                    coin_val = coin_amt * current_price
                    grand_total = idr_cash + coin_val
                    
                    return True, idr_cash, coin_amt, coin_val, grand_total, current_price, "OK"
                else:
                    return False, 0.0, 0.0, 0.0, 0.0, current_price, res.get("error", "API Error")
        except Exception as e:
            return False, 0.0, 0.0, 0.0, 0.0, current_price, str(e)

    # ==========================================
    # KEYBOARDS
    # ==========================================
    def get_main_keyboard(self):
        play_stop_btn = (
            {"text": f"⏹ Hentikan Bot {self.PAIR.upper()}", "callback_data": "btn_stop"}
            if self.state["is_running"]
            else {"text": f"▶️ Jalankan Bot {self.PAIR.upper()}", "callback_data": "btn_start"}
        )
        return {
            "inline_keyboard": [
                [play_stop_btn, {"text": "🔄 Refresh", "callback_data": "btn_refresh"}],
                [{"text": "📊 Status & Posisi", "callback_data": "btn_status"}],
                [{"text": "💰 Cek Saldo", "callback_data": "btn_balance"}],
                [{"text": "📈 Laporan PnL", "callback_data": "btn_report"}],
                [{"text": f"⚡ Cek Harga {self.PAIR.upper()}", "callback_data": "btn_price"}]
            ]
        }

    def get_back_keyboard(self):
        return {
            "inline_keyboard": [
                [{"text": "🏠 Kembali ke Dashboard", "callback_data": "btn_home"}]
            ]
        }

    # ==========================================
    # DASHBOARD TEXT BUILDER
    # ==========================================
    def get_home_text(self, is_final=False, is_daily_recap=False):
        success, idr_bal, coin_amt, coin_val, total_equity, price, err = self.fetch_realtime_account()
        if not success:
            return f"❌ *GAGAL KONEKSI API INDODAX ({self.PAIR.upper()}):* `{err}`"

        status_str = f"Aktif {self.state['price_trend']}" if self.state["is_running"] else f"Berhenti {self.state['price_trend']}"
        now_wib = get_wib_time()

        pos_info = f"⚡ *Posisi:* Scalping (Holding {coin_amt:.6f} {self.COIN_SYMBOL.upper()})" if self.state["in_position"] else "💵 *Posisi:* Standby (Persiapan Beli)"
        chart_str = self.generate_block_chart()

        if self.state["minute_logs"]:
            logs_str = "\n".join(self.state["minute_logs"])
            block_text = f"```\n{logs_str}\n```"
        else:
            block_text = "```\nMemantau pergerakan market...\n```"

        total_wins = self.state["winning_trades"]
        total_losses = self.state["losing_trades"]
        stats_line = f"📈 *Statistik:* 🟢 {total_wins} Win | 🔴 {total_losses} Loss"

        if is_daily_recap:
            return (
                f"🌙 *REKAP HARIAN OTOMATIS ({self.PAIR.upper()}) [00:00 WIB]*\n\n"
                f"💰 *Total Aset:* Rp {total_equity:,.2f}\n"
                f"• IDR Tunai: Rp {idr_bal:,.2f}\n"
                f"• Aset {self.COIN_SYMBOL.upper()}: {coin_amt:,.8f} (Rp {coin_val:,.2f})\n\n"
                f"{stats_line}\n"
                f"⏱ _Waktu Rekap: {now_wib} WIB_\n\n"
                f"📋 *RIWAYAT TRANSAKSI:*\n{block_text}"
            )

        if is_final:
            profit_loss_minute = total_equity - self.state["minute_start_equity"]
            profit_str = f"Rp {profit_loss_minute:+,.2f}"

            return (
                f"🤖 *BOT TRADING INDODAX ({self.PAIR.upper()})*\n\n"
                f"Status Bot: 🏁 *REKAP SESI (1 MENIT SELESAI)*\n"
                f"💰 *Saldo Akhir:* Rp {total_equity:,.2f}\n"
                f"{pos_info}\n"
                f"📈 Grafik: `{chart_str}`\n"
                f"{stats_line}\n"
                f"⏱ _Waktu Selesai: {now_wib} WIB_\n\n"
                f"📋 *RIWAYAT SESI INI:*\n{block_text}\n\n"
                f"📊 *RINGKASAN SESI:*\n"
                f"• Profit: {self.state['minute_wins']}x\n"
                f"• Loss: {self.state['minute_losses']}x\n"
                f"• Hasil PnL Sesi: {profit_str}"
            )

        return (
            f"🤖 *BOT TRADING INDODAX ({self.PAIR.upper()})*\n\n"
            f"Status Bot: {status_str}\n"
            f"💰 *Total Aset:* Rp {total_equity:,.2f} (IDR: Rp {idr_bal:,.0f} | {self.COIN_SYMBOL.upper()}: {coin_amt:.4f})\n"
            f"{pos_info}\n"
            f"📈 Grafik: `{chart_str}`\n"
            f"{stats_line}\n"
            f"⏱ _Live Update: {now_wib} WIB_\n\n"
            f"📋 *RIWAYAT TRANSAKSI (SESI INI):*\n{block_text}\n\n"
            f"Pilih menu di bawah:"
        )

    # ==========================================
    # BACKGROUND LOOPS
    # ==========================================
    def auto_refresh_dashboard_loop(self):
        while True:
            try:
                if self.state["is_running"] and self.state["dashboard_chat_id"] and self.state["dashboard_msg_id"]:
                    new_text = self.get_home_text()
                    if new_text != self.state["last_rendered_text"]:
                        res = self.telegram("editMessageText", {
                            "chat_id": str(self.state["dashboard_chat_id"]),
                            "message_id": self.state["dashboard_msg_id"],
                            "text": new_text,
                            "parse_mode": "Markdown",
                            "reply_markup": self.get_main_keyboard()
                        })
                        if res and res.get("ok"):
                            self.state["last_rendered_text"] = new_text
            except Exception as e:
                print(f"Auto Refresh Error [{self.PAIR}]:", e)
            time.sleep(1.5)

    def daily_reset_loop(self):
        while True:
            now = get_wib_datetime()
            target = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            sleep_seconds = (target - now).total_seconds()
            time.sleep(sleep_seconds)
            
            try:
                if self.state["dashboard_chat_id"]:
                    recap_text = self.get_home_text(is_daily_recap=True)
                    self.telegram("sendMessage", {
                        "chat_id": str(self.state["dashboard_chat_id"]),
                        "text": recap_text,
                        "parse_mode": "Markdown"
                    })
            except Exception as e:
                print(f"DAILY RESET ERROR [{self.PAIR}]:", e)

    def minutely_reset_loop(self):
        while True:
            time.sleep(60)
            try:
                if self.state["is_running"] and self.state["dashboard_chat_id"] and self.state["dashboard_msg_id"]:
                    old_msg_id = self.state["dashboard_msg_id"]
                    final_text = self.get_home_text(is_final=True)
                    
                    self.state["dashboard_msg_id"] = None
                    
                    self.telegram("editMessageText", {
                        "chat_id": str(self.state["dashboard_chat_id"]),
                        "message_id": old_msg_id,
                        "text": final_text,
                        "parse_mode": "Markdown"
                    })

                    success, _, _, _, total_equity, _, _ = self.fetch_realtime_account()
                    self.state["minute_start_equity"] = total_equity if success else 0.0
                    self.state["minute_wins"] = 0
                    self.state["minute_losses"] = 0
                    self.state["minute_logs"].clear()
                    self.add_log("Sesi baru dimulai.")

                    new_home_text = self.get_home_text()
                    resp = self.telegram("sendMessage", {
                        "chat_id": str(self.state["dashboard_chat_id"]),
                        "text": new_home_text,
                        "parse_mode": "Markdown",
                        "reply_markup": self.get_main_keyboard()
                    })
                    if resp and resp.get("ok"):
                        self.state["dashboard_msg_id"] = resp["result"]["message_id"]
                        self.state["last_rendered_text"] = new_home_text
            except Exception as e:
                print(f"MINUTELY RESET ERROR [{self.PAIR}]:", e)

    # ==========================================
    # TRADING ENGINE
    # ==========================================
    def execute_real_order(self, side, amount_idr=0, amount_coin=0):
        url = "https://indodax.com/tapi"
        nonce = str(int(time.time() * 1000))
        params = {
            "method": "trade",
            "pair": self.PAIR,
            "type": side,
            "nonce": nonce
        }
        if side == "buy":
            params["idr"] = int(amount_idr)
        else:
            params[self.COIN_SYMBOL] = f"{amount_coin:.8f}"

        post_data = urllib.parse.urlencode(params).encode("utf-8")
        sign = hmac.new(self.INDODAX_SECRET_KEY.encode('utf-8'), post_data, hashlib.sha512).hexdigest()
        headers = {
            "Key": self.INDODAX_API_KEY,
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

    def trading_loop(self):
        print(f"Engine Real Trading Aktif untuk {self.PAIR.upper()}...")
        highest_price = 0.0

        while True:
            try:
                if self.state["is_running"]:
                    success, idr_cash, coin_amt, coin_val, total_equity, current_price, err = self.fetch_realtime_account()

                    if success and current_price > 0:
                        # 1. KONDISI BELI (ENTRY)
                        if not self.state["in_position"]:
                            if idr_cash > 50000:
                                buy_idr = idr_cash * 0.995 
                                self.add_log(f"Mencoba BUY {self.COIN_SYMBOL.upper()} dg Rp {buy_idr:,.0f}...")
                                success_order, res_data = self.execute_real_order("buy", amount_idr=buy_idr)
                                
                                if success_order:
                                    self.state["buy_price"] = current_price
                                    highest_price = current_price
                                    self.state["in_position"] = True
                                    self.add_log(f"BUY BERHASIL @ Rp {current_price:,.0f}")
                                else:
                                    self.add_log(f"Gagal BUY: {res_data}")
                            else:
                                if not any("Saldo IDR < Min Order" in log for log in self.state["minute_logs"]):
                                    self.add_log(f"Peringatan: Saldo IDR kurang (Rp {idr_cash:,.0f}).")

                        # 2. KONDISI KELOLA POSISI (SELL)
                        elif self.state["in_position"]:
                            if current_price > highest_price:
                                highest_price = current_price

                            price_change_pct = (current_price - self.state["buy_price"]) / self.state["buy_price"]
                            drop_from_peak = (highest_price - current_price) / highest_price if highest_price > 0 else 0

                            is_profit_safe = price_change_pct >= 0.006
                            is_trailing_triggered = (highest_price >= self.state["buy_price"] * 1.01) and (drop_from_peak >= 0.003)
                            is_big_target = price_change_pct >= 0.03
                            is_stop_loss = price_change_pct <= -0.02

                            if (is_profit_safe and is_trailing_triggered) or is_big_target or (is_profit_safe and drop_from_peak >= 0.002) or is_stop_loss:
                                _, _, current_coin_amt, _, _, _, _ = self.fetch_realtime_account()
                                if current_coin_amt > 0.00001:
                                    self.add_log(f"Mencoba SELL {current_coin_amt:.6f} {self.COIN_SYMBOL.upper()}...")
                                    success_order, res_data = self.execute_real_order("sell", amount_coin=current_coin_amt)
                                    
                                    if success_order:
                                        pnl_idr = (current_coin_amt * current_price) - (current_coin_amt * self.state["buy_price"])
                                        self.state["in_position"] = False
                                        self.state["total_trades"] += 1
                                        highest_price = 0.0

                                        if pnl_idr > 0:
                                            self.state["winning_trades"] += 1
                                            self.state["minute_wins"] += 1
                                            self.add_log(f"SELL PROFIT 🔺 @ Rp {current_price:,.0f} (+Rp {pnl_idr:,.0f})")
                                        else:
                                            self.state["losing_trades"] += 1
                                            self.state["minute_losses"] += 1
                                            self.add_log(f"SELL LOSS 🔻 @ Rp {current_price:,.0f} (-Rp {abs(pnl_idr):,.0f})")
                                    else:
                                        self.add_log(f"Gagal SELL: {res_data}")

            except Exception as e:
                print(f"ENGINE ERROR [{self.PAIR}]:", e)

            time.sleep(3)

    # ==========================================
    # TELEGRAM HANDLER
    # ==========================================
    def get_status_text(self):
        success, idr_bal, coin_amt, _, _, price, _ = self.fetch_realtime_account()
        status_str = f"Berjalan {self.state['price_trend']}" if self.state["is_running"] else f"Berhenti {self.state['price_trend']}"
        pos = f"Memegang Aset ({coin_amt:.6f} {self.COIN_SYMBOL.upper()})" if self.state["in_position"] else "Standby (Persiapan Beli)"
        return f"📊 *STATUS BOT ({self.PAIR.upper()})*\n\n• Mode Bot: {status_str}\n• Pair: {self.PAIR.upper()}\n• Harga Saat Ini: Rp {price:,.0f}\n• Posisi: {pos}\n• Statistik: 🟢 {self.state['winning_trades']} Win | 🔴 {self.state['losing_trades']} Loss"

    def get_balance_text(self):
        success, idr_bal, coin_amt, coin_val, equity, price, _ = self.fetch_realtime_account()
        return (
            f"💰 *SALDO & ASET AKUN ({self.PAIR.upper()})*\n\n"
            f"• Saldo IDR Tunai: Rp {idr_bal:,.2f}\n"
            f"• Aset {self.COIN_SYMBOL.upper()}: {coin_amt:.8f} (Rp {coin_val:,.2f})\n\n"
            f"💵 *Total Equity Keseluruhan:* Rp {equity:,.2f}"
        )

    def get_report_text(self):
        success, _, _, _, equity, _, _ = self.fetch_realtime_account()
        return (
            f"📈 *LAPORAN PERFORMA ({self.PAIR.upper()})*\n\n"
            f"• Total Equity: Rp {equity:,.2f}\n"
            f"• Total Trade: {self.state['total_trades']}x\n"
            f"• Statistik: 🟢 {self.state['winning_trades']} Win | 🔴 {self.state['losing_trades']} Loss"
        )

    def update_menu(self, chat_id, msg_id, text, is_home=False):
        markup = self.get_main_keyboard() if is_home else self.get_back_keyboard()
        res = self.telegram("editMessageText", {
            "chat_id": str(chat_id),
            "message_id": msg_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": markup
        })
        if is_home and res and res.get("ok"):
            self.state["dashboard_chat_id"] = chat_id
            self.state["dashboard_msg_id"] = msg_id
            self.state["last_rendered_text"] = text

    def send_menu(self, chat_id, text):
        res = self.telegram("sendMessage", {
            "chat_id": str(chat_id),
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": self.get_main_keyboard()
        })
        if res and res.get("ok"):
            self.state["dashboard_chat_id"] = chat_id
            self.state["dashboard_msg_id"] = res["result"]["message_id"]
            self.state["last_rendered_text"] = text

    def handle_update(self, update):
        if "callback_query" in update:
            cb = update["callback_query"]
            cb_id = cb["id"]
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]
            data = cb.get("data", "")

            if data == "btn_start":
                self.state["is_running"] = True
                success, _, _, _, total_equity, _, _ = self.fetch_realtime_account()
                self.state["minute_start_equity"] = total_equity if success else 0.0
                self.add_log("Bot diaktifkan user.")
                self.telegram("answerCallbackQuery", {"callback_query_id": cb_id, "text": f"▶️ Bot {self.PAIR.upper()} dijalankan.", "show_alert": False})
                self.update_menu(chat_id, msg_id, self.get_home_text(), is_home=True)
            elif data == "btn_stop":
                self.state["is_running"] = False
                self.add_log("Bot dihentikan user.")
                self.telegram("answerCallbackQuery", {"callback_query_id": cb_id, "text": f"⏹ Bot {self.PAIR.upper()} dihentikan.", "show_alert": False})
                self.update_menu(chat_id, msg_id, self.get_home_text(), is_home=True)
            elif data == "btn_refresh":
                self.telegram("answerCallbackQuery", {"callback_query_id": cb_id, "text": "🔄 Dashboard direfresh.", "show_alert": False})
                self.update_menu(chat_id, msg_id, self.get_home_text(), is_home=True)
            elif data == "btn_home":
                self.telegram("answerCallbackQuery", {"callback_query_id": cb_id})
                self.update_menu(chat_id, msg_id, self.get_home_text(), is_home=True)
            elif data == "btn_status":
                self.telegram("answerCallbackQuery", {"callback_query_id": cb_id})
                self.update_menu(chat_id, msg_id, self.get_status_text(), is_home=False)
            elif data == "btn_balance":
                self.telegram("answerCallbackQuery", {"callback_query_id": cb_id})
                self.update_menu(chat_id, msg_id, self.get_balance_text(), is_home=False)
            elif data == "btn_report":
                self.telegram("answerCallbackQuery", {"callback_query_id": cb_id})
                self.update_menu(chat_id, msg_id, self.get_report_text(), is_home=False)
            elif data == "btn_price":
                self.telegram("answerCallbackQuery", {"callback_query_id": cb_id})
                p = self.get_market_price()
                self.update_menu(chat_id, msg_id, f"⚡ *HARGA REAL-TIME ({self.PAIR.upper()})*\n\n• {self.PAIR.upper()}: Rp {p:,.0f}", is_home=False)
            else:
                self.telegram("answerCallbackQuery", {"callback_query_id": cb_id})
            return

        if "message" in update:
            msg = update["message"]
            chat_id = msg.get("chat", {}).get("id")
            text = (msg.get("text") or "").strip()
            if not chat_id: return

            if text.startswith("/start") or text.startswith("/menu"):
                self.send_menu(chat_id, self.get_home_text())

    def polling(self):
        offset = None
        self.telegram("deleteWebhook", {"drop_pending_updates": "false"})
        print(f"Polling Telegram aktif untuk pasar {self.PAIR.upper()}...")
        while True:
            try:
                params = {"timeout": 25, "allowed_updates": json.dumps(["message", "callback_query"])}
                if offset is not None: params["offset"] = offset
                res = self.telegram("getUpdates", params)
                if res and res.get("ok"):
                    for upd in res.get("result", []):
                        offset = upd["update_id"] + 1
                        self.handle_update(upd)
            except Exception as e:
                print(f"POLLING ERROR [{self.PAIR}]:", e)
                time.sleep(5)

    def run(self):
        threading.Thread(target=self.trading_loop, daemon=True).start()
        threading.Thread(target=self.minutely_reset_loop, daemon=True).start()
        threading.Thread(target=self.auto_refresh_dashboard_loop, daemon=True).start()
        threading.Thread(target=self.daily_reset_loop, daemon=True).start()
        self.polling()

# ==========================================
# CARA MENJALANKAN 2 PASAR TERPISAH:
# ==========================================
# File 1 (Misal: bot_btc.py): 
# bot = IndodaxScalpingBot(pair="btcidr", coin_symbol="btc")
# bot.run()
#
# File 2 (Misal: bot_eth.py): 
# bot = IndodaxScalpingBot(pair="ethidr", coin_symbol="eth")
# bot.run()
