#!/bin/bash
# বট নিয়ন্ত্রণ — কাজ নষ্ট না করে গ্রেসফুল রিস্টার্ট
#
#   ./control_bot.sh start           # চালু
#   ./control_bot.sh stop            # কাজ শেষ হওয়ার পরে বন্ধ
#   ./control_bot.sh restart         # কাজ শেষ হওয়ার পরে রিস্টার্ট  ← নিরাপদ
#   ./control_bot.sh restart --force # সাথে সাথে (কাজ হারাবে!)
#   ./control_bot.sh status          # অবস্থা + চলতি কাজ
#   ./control_bot.sh jobs            # শুধু চলতি কাজের তালিকা
#   ./control_bot.sh wait            # কাজ শেষ হওয়া পর্যন্ত অপেক্ষা
#   ./control_bot.sh logs            # শেষ লগ
#
# অপেক্ষার সময় বদলাতে: GB_WAIT=1800 ./control_bot.sh restart
set -uo pipefail

PLIST_PATH="$HOME/Library/LaunchAgents/com.youtube.ai.bot.plist"
PROJECT_DIR="/Users/mdmithumia/other_projects/youtube-ai"
LABEL="com.youtube.ai.bot"
DOMAIN="gui/$(id -u)"
JOBS_FILE="$PROJECT_DIR/.job_state.json"
MAX_WAIT="${GB_WAIT:-2700}"     # ডিফল্ট ৪৫ মিনিট
FORCE=0
[ "${2:-}" = "--force" ] && FORCE=1

# ── এই প্রজেক্টের বট প্রসেসগুলো ───────────────────────────────────────────
bot_pids() {
    local out=""
    for pid in $(pgrep -f "bot\.py" 2>/dev/null); do
        cwd=$(lsof -a -d cwd -p "$pid" -Fn 2>/dev/null | tail -n 1 | sed 's/^n//')
        [ "$cwd" = "$PROJECT_DIR" ] && out="$out $pid"
    done
    echo "$out" | xargs 2>/dev/null
}

# ── চলতি কাজের তথ্য (.job_state.json) ────────────────────────────────────
jobs_text() {
    [ -f "$JOBS_FILE" ] || return 0
    /usr/bin/python3 - "$JOBS_FILE" <<'PY' 2>/dev/null
import json, sys, time
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    sys.exit(0)
jobs = d.get("jobs") or {}
if not jobs:
    sys.exit(0)
for j in jobs.values():
    el = int(time.time() - float(j.get("started") or 0))
    kind = {"youtube": "লিংক", "faceless": "টপিক"}.get(j.get("kind"), j.get("kind"))
    step = (j.get("step") or "")[:40]
    label = str(j.get("label") or "")[:70]
    print(f"{kind} · {el//60}m{el%60:02d}s · {label}" + (f" · {step}" if step and step != "শুরু" else ""))
if d.get("draining"):
    print("(রিস্টার্টের অপেক্ষায় — নতুন কাজ নিচ্ছে না)")
PY
}

jobs_count() { jobs_text | wc -l | tr -d ' '; }

# ── বন্ধ (গ্রেসফুল) ──────────────────────────────────────────────────────
stop_bot() {
    local pids; pids=$(bot_pids)
    if [ -z "$pids" ]; then
        launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
        echo "বট চলছিল না।"
        return 0
    fi

    if [ "$FORCE" = "1" ]; then
        launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
        kill -9 $pids 2>/dev/null
        echo "⚡ জোর করে বন্ধ করা হলো (চলতি কাজ হারানো গেল)"
        return 0
    fi

    local info; info=$(jobs_text)
    if [ -n "$info" ]; then
        echo "🔎 চলতি কাজ পাওয়া গেছে — শেষ হওয়া পর্যন্ত অপেক্ষা করব:"
        echo "$info" | sed 's/^/   /'
        echo "   (বাতিল করতে: ./control_bot.sh stop --force)"
    fi

    # launchd যাতে সাথে সাথে আবার চালু না করে — আগে সার্ভিস থামিয়ে দিই
    # (plist-এ ExitTimeOut=3600, তাই launchd নিজেই কাজ শেষ হওয়া পর্যন্ত অপেক্ষা করে)
    launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
    kill -TERM $pids 2>/dev/null || true

    local waited=0
    while :; do
        pids=$(bot_pids)
        [ -z "$pids" ] && break
        if [ "$waited" -ge "$MAX_WAIT" ]; then
            echo "⚠️ ${MAX_WAIT}s পরও শেষ হয়নি — জোর করে বন্ধ করছি"
            kill -9 $pids 2>/dev/null
            break
        fi
        if [ $((waited % 30)) -eq 0 ] && [ "$waited" -gt 0 ]; then
            local now; now=$(jobs_text)
            if [ -n "$now" ]; then
                echo "⏳ ${waited}s — $(echo "$now" | head -1)"
            else
                echo "⏳ ${waited}s — বন্ধ হচ্ছে…"
            fi
        fi
        sleep 5
        waited=$((waited + 5))
    done
    echo "✅ বট বন্ধ (${waited}s)"
}

start_bot() {
    if [ -n "$(bot_pids)" ]; then
        echo "⚠️ আগেই চলছে (PID:$(bot_pids))"
        return 0
    fi
    launchctl bootstrap "$DOMAIN" "$PLIST_PATH" >/dev/null 2>&1 \
        || launchctl load "$PLIST_PATH" >/dev/null 2>&1
    sleep 3
    if [ -n "$(bot_pids)" ]; then
        echo "✅ বট চালু (PID:$(bot_pids))"
    else
        echo "❌ চালু হয়নি — ./control_bot.sh logs দেখো"
        return 1
    fi
}

status_bot() {
    local pids; pids=$(bot_pids)
    if [ -n "$pids" ]; then
        echo "🟢 বট চলছে (PID:$pids)"
        ps -p "$(echo $pids | tr ' ' ',')" -o pid,%cpu,%mem,etime,command 2>/dev/null | tail -n +2
    else
        echo "🔴 বট বন্ধ"
    fi
    local info; info=$(jobs_text)
    if [ -n "$info" ]; then
        echo "🔎 চলতি কাজ:"
        echo "$info" | sed 's/^/   /'
    else
        echo "💤 চলতি কাজ নেই (idle)"
    fi
    launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 && echo "launchd: লোডেড (KeepAlive ±)" || echo "launchd: লোড হয়নি"
}

wait_jobs() {
    local waited=0
    while [ "$(jobs_count)" != "0" ]; do
        [ $((waited % 30)) -eq 0 ] && echo "⏳ $(jobs_text | head -1)"
        sleep 5; waited=$((waited + 5))
    done
    echo "✅ সব কাজ শেষ (${waited}s)"
}

show_logs() {
    echo "--- bot_stdout.log (শেষ ২০) ---"; tail -n 20 "$PROJECT_DIR/bot_stdout.log" | strings
    echo ""
    echo "--- bot_stderr.log (শেষ ১০) ---"; tail -c 3000 "$PROJECT_DIR/bot_stderr.log" | strings | tail -n 10
}

case "${1:-status}" in
    start)          start_bot ;;
    stop)           stop_bot ;;
    restart)        stop_bot; sleep 1; start_bot ;;
    status)         status_bot ;;
    jobs)           jobs_text || true; [ "$(jobs_count)" = "0" ] && echo "চলতি কাজ নেই" ;;
    wait)           wait_jobs ;;
    logs)           show_logs ;;
    *) echo "ব্যবহার: $0 {start|stop|restart|status|jobs|wait|logs} [--force]"; exit 1 ;;
esac
