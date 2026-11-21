#!/bin/bash
# ২ GB ভিডিও আপলোড সেটআপ (Telethon — নিজের Telegram অ্যাকাউন্ট দিয়ে)
#
# কেন দরকার: Bot API-র ক্লাউড সার্ভারে বট **সর্বোচ্চ ৫০ MB** আপলোড করতে পারে।
# (ব্যবহারকারী ২ GB নামাতে পারে — কিন্তু বট পাঠাতে পারে না।)
# Telethon নিজের অ্যাকাউন্ট দিয়ে পাঠায় → ২ GB (Premium হলে ৪ GB)।
#
# আগে যা লাগবে: https://my.telegram.org → API development tools → api_id + api_hash
# .env ফাইলে যোগ করো:
#     TELEGRAM_API_ID=1234567
#     TELEGRAM_API_HASH=abcdef0123456789abcdef0123456789
#
# তারপর চালাও:  ./tools/setup_2gb.sh
set -e
cd "$(dirname "$0")/.."

if ! grep -q "^TELEGRAM_API_ID=" .env 2>/dev/null || ! grep -q "^TELEGRAM_API_HASH=" .env 2>/dev/null; then
  echo "❌ .env-এ TELEGRAM_API_ID / TELEGRAM_API_HASH নেই।"
  echo "   ১) https://my.telegram.org → API development tools"
  echo "   ২) api_id + api_hash কপি করে .env-এ বসাও"
  echo "   ৩) আবার এই স্ক্রিপ্ট চালাও"
  exit 1
fi

echo "🔐 Telegram অ্যাকাউন্টে লগইন (ফোন নম্বর + কোড চাইবে)..."
./.venv/bin/python tools/tele_upload.py --login

echo
echo "✅ সেশন তৈরি: tele_session.session"
echo "   এখন ২ GB পর্যন্ত ভিডিও সোজা চ্যাটে যাবে।"
