# Indodax Paper Trading Bot — WebSocket + Telegram

DEMO/PAPER TRADING ONLY. Bot ini tidak membuat order nyata di Indodax.

Railway Variables:
START_BALANCE=100000
PAIR=btcidr
FEE_RATE=0.002
MIN_TAKE_PROFIT=0.02
MAX_TAKE_PROFIT=0.30
STOP_LOSS=0.05
DAILY_LOSS_LIMIT=0.10
INTERVAL_SECONDS=5
WINDOW_SIZE=60
TELEGRAM_BOT_TOKEN=TOKEN_BOTFATHER
TELEGRAM_CHAT_ID=CHAT_ID_KAMU

Optional:
INDODAX_WS_URL=wss://ws3.indodax.com/ws/
INDODAX_WS_TOKEN=official_static_token

Telegram commands:
/start
/status
/balance
/trades
/report
/pause
/resume

Market data uses the official Indodax Market Data WebSocket.
The demo does not use an Indodax trading API key/secret and does not place real orders.
