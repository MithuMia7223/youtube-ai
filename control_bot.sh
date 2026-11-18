#!/bin/bash

# Path to plist and directory
PLIST_PATH="$HOME/Library/LaunchAgents/com.youtube.ai.bot.plist"
PROJECT_DIR="/Users/mdmithumia/other_projects/youtube-ai"

stop_bot() {
    echo "Stopping bot background services..."
    # Unload launchd agent if loaded
    launchctl unload "$PLIST_PATH" 2>/dev/null
    
    # Find PIDs for run_bot.sh
    run_bot_pids=$(ps aux | grep 'run_bot.sh' | grep 'youtube-ai' | grep -v 'grep' | awk '{print $2}')
    
    # Find PIDs for bot.py running in this project directory by checking their working directories
    bot_pids=""
    pids=$(ps aux | grep 'bot.py' | grep -v 'grep' | awk '{print $2}')
    for pid in $pids; do
        cwd=$(lsof -a -d cwd -p "$pid" -Fn 2>/dev/null | tail -n 1 | sed 's/^n//')
        if [ "$cwd" = "$PROJECT_DIR" ]; then
            bot_pids="$bot_pids $pid"
        fi
    done
    
    if [ -n "$run_bot_pids" ] || [ -n "$bot_pids" ]; then
        echo "Killing running bot processes..."
        [ -n "$run_bot_pids" ] && kill -9 $run_bot_pids 2>/dev/null
        [ -n "$bot_pids" ] && kill -9 $bot_pids 2>/dev/null
    fi
    echo "Bot stopped successfully."
}

start_bot() {
    # Ensure it's not already running
    stop_bot
    echo "Starting bot in background..."
    launchctl load "$PLIST_PATH"
    echo "Bot started in background successfully."
}

status_bot() {
    echo "Checking bot status..."
    bot_pids=""
    pids=$(ps aux | grep 'bot.py' | grep -v 'grep' | awk '{print $2}')
    for pid in $pids; do
        cwd=$(lsof -a -d cwd -p "$pid" -Fn 2>/dev/null | tail -n 1 | sed 's/^n//')
        if [ "$cwd" = "$PROJECT_DIR" ]; then
            bot_pids="$bot_pids $pid"
        fi
    done
    
    if [ -n "$bot_pids" ]; then
        echo "Bot is currently RUNNING (PID: $bot_pids)."
        ps -p $(echo $bot_pids | tr ' ' ',') -o pid,ppid,%cpu,%mem,start,time,command
    else
        echo "Bot is STOPPED."
    fi
}

show_logs() {
    echo "--- Last 20 lines of bot_stdout.log ---"
    tail -n 20 "$PROJECT_DIR/bot_stdout.log"
    echo ""
    echo "--- Last 20 lines of bot_stderr.log ---"
    tail -n 20 "$PROJECT_DIR/bot_stderr.log"
}

case "$1" in
    start)
        start_bot
        ;;
    stop)
        stop_bot
        ;;
    restart)
        stop_bot
        sleep 2
        start_bot
        ;;
    status)
        status_bot
        ;;
    logs)
        show_logs
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
