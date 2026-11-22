#!/bin/bash
# লোকাল Telegram Bot API সার্ভার — চালানোর আসল র‍্যাপার
# (launchd / nohup দুটোই এটাকে কল করে। .env থেকে creds পড়ে বাইনারি চালায়।)
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"

BIN="${TGBOTAPI_BIN:-$HOME/tgbuild/telegram-bot-api/build/telegram-bot-api}"
DATA="${TGBOTAPI_DATA:-$HOME/tgbuild/tgbotapi-data}"
PORT="${TGBOT_API_PORT:-8081}"

env_get() {
  [ -f "$ROOT/.env" ] || return 1
  grep -E "^$1=" "$ROOT/.env" | head -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

API_ID="$(env_get TELEGRAM_API_ID)"
API_HASH="$(env_get TELEGRAM_API_HASH)"

if [ -z "$API_ID" ] || [ -z "$API_HASH" ]; then
  echo "❌ .env-এ TELEGRAM_API_ID / TELEGRAM_API_HASH নেই — সার্ভার চালু হবে না।"
  echo "   ঠিক করতে: ./tools/local_bot_api.sh setup"
  exit 2
fi

if [ ! -x "$BIN" ]; then
  echo "❌ বাইনারি নেই: $BIN"
  exit 3
fi

mkdir -p "$DATA"

# বিল্ডের ওপেন-এসএসএল লাইব্রেরি (থাকলে)
if [ -d "$HOME/tgbuild/openssl-inst/lib" ]; then
  export DYLD_LIBRARY_PATH="$HOME/tgbuild/openssl-inst/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
fi

exec "$BIN" \
  --api-id="$API_ID" \
  --api-hash="$API_HASH" \
  --http-ip-address=127.0.0.1 \
  --http-port="$PORT" \
  --dir="$DATA" \
  --files-dir="$DATA" \
  --log="$DATA/log"
