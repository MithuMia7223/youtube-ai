#!/bin/bash

# Navigate to project directory
cd /Users/mdmithumia/other_projects/youtube-ai

# Keep Mac awake during execution using caffeinate
# -d: prevents display sleep, -i: prevents system idle sleep, -s: prevents system sleep
caffeinate -dis .venv/bin/python -u bot.py

