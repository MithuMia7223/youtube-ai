#!/bin/bash
# 🚀 লোকাল Bot API সার্ভার — ২ GB আপলোডের জন্য
#
# কেন: Bot API-র ক্লাউড সার্ভারে বট সর্বোচ্চ ৫০ MB পাঠাতে পারে।
# এই সার্ভার নিজের মেশিনে চলে → বট ২০০০ MB (২ GB) পর্যন্ত পাঠাতে পারে।
#
# ব্যবহার:
#   ./tools/local_bot_api.sh start     # চালু
#   ./tools/local_bot_api.sh stop      # বন্ধ
#   ./tools/local_bot_api.sh status    # অবস্থা
#   ./tools/local_bot_api.sh logs      # লগ
#
# আগে শর্ত: .env-এ TELEGRAM_API_ID ও TELEGRAM_API_HASH থাকতে হবে
# (https://my.telegram.org → API development tools)
set -e
cd "$(dirname "$0")/.."

BIN="/Users/mdmithumia/tgbuild/telegram-bot-api/build/telegram-bot-api"
PORT="${TGBOT_API_PORT:-8081}"
WORKDIR="/Users/mdmithumia/tgbuild/tgbotapi-data"
LOG="/Users/mdmithumia/tgbuild/tgbotapi.log"
PIDF="/Users/mdmithumia/tgbuild/tgbotapi.pid"

start() {
  if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
    echo "✅ আগেই চলছে (PID $(cat "$PIDF"))"; return
  fi
  [ -x "$BIN" ] || { echo "❌ বাইনারি নেই: $BIN"; exit 1; }
  # .env থেকে কী পড়ি
  API_ID=$(grep -E '^TELEGRAM_API_ID=' .env | cut -d= -f2 | tr -d ' \r')
  API_HASH=$(grep -E '^TELEGRAM_API_HASH=' .env | cut -d= -f2 | tr -d ' \r')
  if [ -z "$API_ID" ] || [ -z "$API_HASH" ]; then
    echo "❌ .env-এ TELEGRAM_API_ID / TELEGRAM_API_HASH নেই"
    echo "   https://my.telegram.org → API development tools থেকে নাও"
    exit 1
  fi
  mkdir -p "$WORKDIR"
  nohup "$BIN" --api-id="$API_ID" --api-hash="$API_HASH" \
        --http-port="$PORT" --dir="$WORKDIR" --files-dir="$WORKDIR" \
        >> "$LOG" 2>&1 &
  echo $! > "$PIDF"
  sleep 4
  if kill -0 "$(cat "$PIDF")" 2>/dev/null; then
    echo "✅ লোকাল Bot API সার্ভার চালু → http://127.0.0.1:$PORT (PID $(cat "$PIDF"))"
    echo "   বটে ব্যবহার: .env-এ  TELEGRAM_API_URL=http://127.0.0.1:$PORT"
    echo "   ⚠️ একই টোকেনে দুই জায়গায় polling চললে Conflict হবে —"
    echo "      তাই এই সার্ভার চালু রেখে বট রিস্টার্ট করো (TELEGRAM_API_URL সহ)।"
  else
    echo "❌ চালু হয়নি — লগ দেখো: $LOG"; tail -5 "$LOG"
  fi
}

stop() {
  if [ -f "$PIDF" ]; then
    kill "$(cat "$PIDF")" 2>/dev/null || true
    rm -f "$PIDF"
    echo "🛑 বন্ধ করা হলো"
  else
    pkill -f "telegram-bot-api --api-id" 2>/dev/null && echo "🛑 বন্ধ করা হলো" || echo "চলছিল না"
  fi
}

status() {
  if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
    echo "✅ চলছে (PID $(cat "$PIDF")) · পোর্ট $PORT"
    curl -s --max-time 3 "http://127.0.0.1:$PORT/" -o /dev/null -w "   HTTP: %{http_code}\n" || true
  else
    echo "⏹️ বন্ধ"
  fi
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  logs) tail -40 "$LOG" ;;
  *) echo "ব্যবহার: $0 {start|stop|status|logs}"; exit 1 ;;
esac
