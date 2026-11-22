#!/bin/bash
# 🧪 ২ GB আপলোড পরীক্ষা — লোকাল Bot API সার্ভার দিয়ে সত্যি পাঠিয়ে দেখি
#
# ব্যবহার:
#   ./tools/test_2gb_upload.sh              # chat_id নিজেই খুঁজে নেবে
#   ./tools/test_2gb_upload.sh <chat_id> [ফাইল]
#
# ডিফল্ট ফাইল: deliver/longtest_169.mp4 (৫৬ MB — ক্লাউড API-তে পাঠানোই যেত না)
set -uo pipefail
cd "$(dirname "$0")/.."; ROOT="$(pwd)"
PORT="${TGBOT_API_PORT:-8081}"
API="http://127.0.0.1:$PORT"

TOKEN="$(grep -E '^TELEGRAM_BOT_TOKEN=' .env | head -1 | cut -d= -f2- | tr -d '\r')"
[ -n "$TOKEN" ] || { echo "❌ .env-এ TELEGRAM_BOT_TOKEN নেই"; exit 1; }

if ! curl -s --max-time 3 -o /dev/null "$API/"; then
  echo "❌ লোকাল Bot API সার্ভার চলছে না → ./tools/local_bot_api.sh start"; exit 1
fi

CHAT_ID="${1:-}"
FILE="${2:-$(ls -S deliver/*.mp4 2>/dev/null | head -1)}"
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
  echo "❌ ফাইল পাওয়া গেল না"; exit 1
fi

if [ -z "$CHAT_ID" ]; then
  # বটের কাছে আসা সর্বশেষ মেসেজ থেকে chat_id বের করি
  CHAT_ID="$(curl -s --max-time 10 "$API/bot$TOKEN/getUpdates?limit=100" \
    | .venv/bin/python -c "
import sys, json
d = json.load(sys.stdin)
ids = []
for u in d.get('result', []):
    m = u.get('message') or u.get('edited_message') or {}
    c = m.get('chat') or {}
    if c.get('id'):
        ids.append(c['id'])
print(ids[-1] if ids else '')
")"
fi

if [ -z "$CHAT_ID" ]; then
  echo "❌ chat_id পাওয়া গেল না — বটকে Telegram-এ একটা মেসেজ পাঠাও, তারপর আবার চালাও"
  echo "   অথবা: $0 <chat_id>"
  exit 1
fi

SIZE_MB="$(du -m "$FILE" | cut -f1)"
echo "📤 পাঠাচ্ছি: $FILE (${SIZE_MB} MB) → chat $CHAT_ID"
echo "   (৫০ MB-র বেশি — তাই এটা প্রমাণ করবে সীমা তুলে গেছে)"

START=$(date +%s)
RESP="$(curl -s --max-time 1800 -F "chat_id=$CHAT_ID" \
        -F "document=@$FILE" \
        -F "caption=🧪 ২GB সাপোর্ট টেস্ট · ${SIZE_MB} MB · লোকাল Bot API" \
        "$API/bot$TOKEN/sendDocument")"
END=$(date +%s)

echo "$RESP" | head -c 400; echo
if echo "$RESP" | grep -q '"ok":true'; then
  echo "✅ সফল! $((END-START)) সেকেন্ডে ${SIZE_MB} MB গেল — টেলিগ্রাম চ্যাটে দেখো"
else
  echo "❌ ব্যর্থ — উপরের এরর দেখো"; exit 1
fi
