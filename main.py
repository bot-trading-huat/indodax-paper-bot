import os
import time
import json
import urllib.request
import urllib.parse

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


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
            print(method, result)
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
        },
    )


def is_allowed(chat_id):
    # Kalau TELEGRAM_CHAT_ID masih kosong,
    # semua chat boleh menggunakan bot sementara.
    if not ALLOWED_CHAT_ID:
        return True

    return str(chat_id) == str(ALLOWED_CHAT_ID)


def handle_message(message):
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return

    command = text.split()[0].lower().split("@")[0]

    # ==========================================
    # /id SELALU BOLEH DIGUNAKAN
    # ==========================================

    if command == "/id":
        send_message(
            chat_id,
            "🆔 TELEGRAM CHAT ID\n\n"
            f"{chat_id}\n\n"
            "Copy angka di atas ke Railway:\n\n"
            "TELEGRAM_CHAT_ID"
        )
        return

    # ==========================================
    # COMMAND LAIN
    # ==========================================

    if not is_allowed(chat_id):
        send_message(
            chat_id,
            "⛔ Chat ID ini belum diizinkan."
        )
        return

    if command == "/start":

        send_message(
            chat_id,
            "🤖 INDODAX PAPER BOT\n\n"
            "Telegram berhasil terhubung.\n\n"
            "/id - melihat Chat ID\n"
            "/status - status bot\n"
            "/balance - saldo demo\n"
            "/report - laporan demo"
        )

    elif command == "/status":

        send_message(
            chat_id,
            "🟢 BOT ONLINE\n\n"
            "Telegram: CONNECTED\n"
            "Mode: PAPER TRADING"
        )

    elif command == "/balance":

        send_message(
            chat_id,
            "💰 SALDO DEMO\n\n"
            "Rp100.000"
        )

    elif command == "/report":

        send_message(
            chat_id,
            "📊 DEMO REPORT\n\n"
            "Telegram berhasil menerima command."
        )

    else:

        send_message(
            chat_id,
            "❓ Command tidak dikenal.\n\n"
            "Gunakan /id atau /start"
        )


def polling():

    offset = None

    # Menghapus webhook agar getUpdates bisa digunakan.
    result = telegram(
        "deleteWebhook",
        {
            "drop_pending_updates": "false"
        }
    )

    print("Webhook reset:", result)

    while True:

        try:

            params = {
                "timeout": 25,
                "allowed_updates": json.dumps(
                    ["message"]
                ),
            }

            if offset is not None:
                params["offset"] = offset

            result = telegram(
                "getUpdates",
                params
            )

            if not result or not result.get("ok"):
                print("getUpdates gagal.")
                time.sleep(3)
                continue

            updates = result.get("result", [])

            for update in updates:

                offset = update["update_id"] + 1

                message = update.get("message")

                if message:
                    print("MESSAGE:", message)

                    handle_message(message)

        except Exception as error:

            print(
                "POLLING ERROR:",
                repr(error)
            )

            time.sleep(5)


if __name__ == "__main__":

    print("==============================")
    print(" TELEGRAM TEST BOT")
    print("==============================")
    print("Bot started.")

    polling()
