#!/bin/bash
# 🚀 লোকাল Telegram Bot API সার্ভার — ২ GB আপলোডের জন্য
#
# কেন: Bot API-র ক্লাউড সার্ভারে বট সর্বোচ্চ ৫০ MB পাঠাতে পারে।
# নিজের মেশিনে telegram-bot-api সার্ভার চালালে বট **২০০০ MB (২ GB)** পর্যন্ত
# একটাই ফাইলে পাঠাতে পারে — কোনো ভাগ, কোনো কম্প্রেশন ছাড়া।
#
# ব্যবহার:
#   ./tools/local_bot_api.sh setup     # প্রথমবার: api_id/api_hash বসানো + চালু + বট রিস্টার্ট
#   ./tools/local_bot_api.sh start     # চালু (launchd, অটো-রিস্টার্ট সহ)
#   ./tools/local_bot_api.sh stop      # বন্ধ
#   ./tools/local_bot_api.sh status    # অবস্থা
#   ./tools/local_bot_api.sh logs      # লগ
#
# আগে শর্ত: .env-এ TELEGRAM_API_ID ও TELEGRAM_API_HASH থাকতে হবে
# (https://my.telegram.org → API development tools)
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

PORT="${TGBOT_API_PORT:-8081}"
LOG="$HOME/tgbuild/tgbotapi.log"
PLIST="$HOME/Library/LaunchAgents/com.youtube.ai.tgbotapi.plist"
LABEL="com.youtube.ai.tgbotapi"
SERVICE="gui/$(id -u)/$LABEL"

ok()   { echo "✅ $*"; }
bad()  { echo "❌ $*"; }
info() { echo "   $*"; }

running() {
  launchctl print "$SERVICE" >/dev/null 2>&1
}

healthy() {
  curl -s --max-time 3 "http://127.0.0.1:$PORT/" -o /dev/null -w "%{http_code}" 2>/dev/null | grep -qE "^(200|404|401)$"
}

write_plist() {
  mkdir -p "$(dirname "$PLIST")"
  cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string><string>$ROOT/tools/tgbotapi_daemon.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/Users/mdmithumia/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>HOME</key><string>$HOME</string>
    <key>TGBOT_API_PORT</key><string>$PORT</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST_EOF
}

start() {
  write_plist
  if running; then
    launchctl kickstart -k "$SERVICE" >/dev/null 2>&1
  else
    launchctl bootstrap "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || launchctl load "$PLIST" >/dev/null 2>&1
  fi
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    healthy && break
    sleep 1
  done
  if healthy; then
    ok "লোকাল Bot API সার্ভার চালু → http://127.0.0.1:$PORT (সীমা ২০০০ MB)"
    info "বট এর মধ্য দিয়েই চলবে (run_bot.sh নিজেই TELEGRAM_API_URL বসায়)"
  else
    bad "চালু হয়নি — লগ দেখো: ./tools/local_bot_api.sh logs"
    tail -12 "$LOG" 2>/dev/null | sed 's/^/   /'
    return 1
  fi
}

stop() {
  if running; then
    launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || launchctl unload "$PLIST" >/dev/null 2>&1
    ok "বন্ধ করা হলো"
  else
    pkill -f "telegram-bot-api --api-id" >/dev/null 2>&1 && ok "বন্ধ করা হলো" || info "চলছিল না"
  fi
}

status_cmd() {
  if running; then
    ok "launchd সার্ভিস লোডেড ($LABEL)"
  else
    bad "launchd সার্ভিস লোড হয়নি"
  fi
  if healthy; then
    ok "HTTP ঠিক আছে → http://127.0.0.1:$PORT"
  else
    bad "HTTP সাড়া দিচ্ছে না (পোর্ট $PORT)"
  fi
  if [ -n "$(env_get TELEGRAM_API_ID)" ] && [ -n "$(env_get TELEGRAM_API_HASH)" ]; then
    ok ".env-এ api_id/api_hash আছে"
  else
    bad ".env-এ api_id/api_hash নেই → ./tools/local_bot_api.sh setup"
  fi
  if curl -s --max-time 2 "http://127.0.0.1:$PORT/" >/dev/null 2>&1; then :; fi
}

env_get() {
  [ -f "$ROOT/.env" ] || return 1
  grep -E "^$1=" "$ROOT/.env" | head -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^"//' -e 's/"$//'
}

set_env() {  # set_env KEY VALUE
  local k="$1" v="$2" tmp
  tmp="$(mktemp)"
  grep -vE "^$k=" "$ROOT/.env" > "$tmp" 2>/dev/null || true
  printf '%s=%s\n' "$k" "$v" >> "$tmp"
  mv "$tmp" "$ROOT/.env"
}

setup() {
  echo "──────────────────────────────────────────────"
  echo " ২ GB আপলোড সেটআপ (একবারই লাগবে)"
  echo "──────────────────────────────────────────────"
  echo "১) ব্রাউজারে খোলো: https://my.telegram.org/apps"
  echo "২) अपने ফোন নম্বর দিয়ে লগইন → 'API development tools'"
  echo "৩) App title যা খুশি দাও (যেমন: youtube-bot) → Create app"
  echo "৪) ওখানে দেখাবে: api_id (সংখ্যা) আর api_hash (৩২ অক্ষরের হেক্স)"
  echo
  read -r -p "api_id  : " API_ID
  read -r -s -p "api_hash: " API_HASH; echo
  API_ID="$(echo "${API_ID:-}" | tr -d ' \r\n')"
  API_HASH="$(echo "${API_HASH:-}" | tr -d ' \r\n')"

  if ! [[ "$API_ID" =~ ^[0-9]{5,12}$ ]]; then
    bad "api_id সংখ্যা হবে (যেমন 12345678) — আবার চালাও"; exit 1
  fi
  if ! [[ "$API_HASH" =~ ^[0-9a-fA-F]{32}$ ]]; then
    bad "api_hash ৩২ অক্ষরের হেক্স হবে (0-9, a-f) — আবার চালাও"; exit 1
  fi

  [ -f "$ROOT/.env" ] || : > "$ROOT/.env"
  set_env TELEGRAM_API_ID "$API_ID"
  set_env TELEGRAM_API_HASH "$API_HASH"
  ok ".env আপডেট হলো (api_id/api_hash)"

  start || exit 1

  echo
  echo "🔄 বট রিস্টার্ট করছি যাতে সে লোকাল সার্ভার দিয়ে চলে..."
  ./control_bot.sh restart >/dev/null 2>&1 || true
  sleep 3
  if ./control_bot.sh status | grep -q RUNNING; then
    ok "বট চলছে — এখন ২ GB পর্যন্ত ফাইল সোজা চ্যাটে যাবে"
  else
    bad "বট চালু হয়নি — ./control_bot.sh logs দেখো"
  fi
  echo
  echo "যাচাই: ./tools/local_bot_api.sh status"
}

case "${1:-status}" in
  setup)  setup ;;
  start)  start ;;
  stop)   stop ;;
  status) status_cmd ;;
  logs)   tail -40 "$LOG" 2>/dev/null || info "লগ নেই" ;;
  *) echo "ব্যবহার: $0 {setup|start|stop|status|logs}"; exit 1 ;;
esac
