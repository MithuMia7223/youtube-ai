#!/bin/bash

# Navigate to project directory
cd /Users/mdmithumia/other_projects/youtube-ai || exit 1

# ── ২ GB আপলোড: লোকাল Telegram Bot API সার্ভার ─────────────────────────────
# সার্ভার চললে বট তার মধ্য দিয়ে চলে → আপলোড সীমা ৫০ MB থেকে ২০০০ MB হয়।
# creds (.env) না থাকলে বা সার্ভার বন্ধ থাকলে ক্লাউড API-তেই চলে (৫০ MB)।
TGAPI_PORT="${TGBOT_API_PORT:-8081}"
TGAPI_URL="http://127.0.0.1:$TGAPI_PORT"
has_creds=0
if grep -qE '^TELEGRAM_API_ID=[0-9]+' .env 2>/dev/null && \
   grep -qE '^TELEGRAM_API_HASH=[0-9a-fA-F]{32}' .env 2>/dev/null; then
  has_creds=1
fi

if [ "$has_creds" = "1" ]; then
  # সার্ভার উঠতে ২-৩ সেকেন্ড লাগে — বুটের সময় একটু অপেক্ষা করি
  for _ in $(seq 1 20); do
    if curl -s --max-time 2 -o /dev/null "$TGAPI_URL/" 2>/dev/null; then
      export TELEGRAM_API_URL="$TGAPI_URL"
      break
    fi
    sleep 1
  done
fi

if [ -n "${TELEGRAM_API_URL:-}" ]; then
  echo "[run_bot] লোকাল Bot API সার্ভার → $TELEGRAM_API_URL (আপলোড সীমা ২ GB)"
else
  echo "[run_bot] ক্লাউড Bot API (আপলোড সীমা ৫০ MB) — ২ GB চাইলে: ./tools/local_bot_api.sh setup"
fi

# Keep Mac awake during execution using caffeinate
# -d: prevents display sleep, -i: prevents system idle sleep, -s: prevents system sleep
caffeinate -dis .venv/bin/python -u bot.py
