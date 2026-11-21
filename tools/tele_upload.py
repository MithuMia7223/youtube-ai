#!/usr/bin/env python3
"""
📤 আনলিমিটেড আপলোডার — তোমার নিজের টেলিগ্রাম অ্যাকাউন্ট দিয়ে ফাইল পাঠায়
==========================================================================

কেন দরকার: সাধারণ Bot API-তে বট **৫০ MB**-র বেশি পাঠাতে পারে না (ভিডিও/ফাইল
দুটোতেই)। তোমার নিজের অ্যাকাউন্ট (MTProto) দিয়ে সীমা **২ GB** (প্রিমিয়ামে ৪ GB)।
এতে ফাইলটা **চ্যাটেই** আসে, কোনো লিংক বা কম্প্রেশন ছাড়া — ১০৮০ অটুট।

প্রথমবার (একবারই):
    ./.venv/bin/python tools/tele_upload.py --login

তারপর বট নিজেই ব্যবহার করবে:
    ./.venv/bin/python tools/tele_upload.py 7425534011 /path/video.mp4

.env-এ যা লাগবে:
    TELEGRAM_API_ID=1234567
    TELEGRAM_API_HASH=abcdef0123456789abcdef0123456789
    # (api_id/api_hash নাও: https://my.telegram.org → API development tools)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSION = ROOT / "tele_session"


def load_env() -> None:
    """প্রজেক্টের .env পড়ে environment-এ বসায় (আগে থেকে সেট থাকলে ছোঁয় না)।"""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def creds() -> tuple[int, str]:
    api_id = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    if not api_id.isdigit() or not api_hash:
        print("❌ TELEGRAM_API_ID / TELEGRAM_API_HASH নেই।")
        print("   ১) https://my.telegram.org → API development tools")
        print("   ২) .env-এ TELEGRAM_API_ID ও TELEGRAM_API_HASH বসাও")
        sys.exit(2)
    return int(api_id), api_hash


def client():
    from telethon import TelegramClient

    api_id, api_hash = creds()
    return TelegramClient(str(SESSION), api_id, api_hash)


def do_login() -> None:
    api_id, api_hash = creds()
    from telethon import TelegramClient

    print("🔑 প্রথমবার লগইন — ফোনে কোড আসবে।")
    with TelegramClient(str(SESSION), api_id, api_hash) as c:
        me = c.loop.run_until_complete(c.get_me())
        print(f"✅ লগইন হয়েছে: {me.first_name or ''} (@{me.username or me.id})")
        print(f"   সেশন ফাইল: {SESSION}.session — এটা কারো সঙ্গে শেয়ার করো না।")


def send(chat_id: str, file_path: str, caption: str = "") -> int:
    """ফাইলটা chat_id-তে ডকুমেন্ট হিসেবে পাঠায়। সফল হলে 0 ফেরত দেয়।"""
    from telethon.tl.types import DocumentAttributeVideo

    p = Path(file_path)
    if not p.exists():
        print(f"❌ ফাইল নেই: {p}")
        return 1
    size_mb = p.stat().st_size / (1024 * 1024)
    print(f"📤 পাঠাচ্ছি: {p.name} ({size_mb:.1f} MB) → chat {chat_id}")

    with client() as c:
        target = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
        # force_document=True → রিকম্প্রেস হবে না, ১০৮০ অটুট
        c.loop.run_until_complete(
            c.send_file(
                target, str(p),
                caption=(caption or p.name),
                force_document=True,
                attributes=[DocumentAttributeVideo(0, 0, 0, supports_streaming=True)],
                part_size_kb=512,
            )
        )
    print(f"✅ চ্যাটে পাঠানো হয়েছে ({size_mb:.1f} MB) — কোয়ালিটি অটুট")
    return 0


def main() -> int:
    load_env()
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if args[0] == "--login":
        do_login()
        return 0
    if len(args) < 2:
        print("ব্যবহার: tele_upload.py <chat_id> <file> [caption]")
        return 2
    return send(args[0], args[1], args[2] if len(args) > 2 else "")


if __name__ == "__main__":
    sys.exit(main())
