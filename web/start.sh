#!/bin/zsh
# 🌐 ভিডিও ভল্ট চালু করে (ব্রাউজারও খোলে)
cd "$(dirname "$0")/.." || exit 1
exec ./.venv/bin/python web/app.py --open
