#!/bin/bash

# Navigate to project directory
cd /Users/mdmithumia/youtube-ai

# Keep Mac awake during execution using caffeinate
# -d: prevents display sleep, -i: prevents system idle sleep, -s: prevents system sleep
caffeinate -dis /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -u bot.py

# Fallback: if caffeinate is interrupted, run normal loop
while true; do
    echo "Starting YouTube AI Bot..."
    /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -u bot.py
    echo "Bot crashed or exited. Restarting in 5 seconds..."
    sleep 5
done
