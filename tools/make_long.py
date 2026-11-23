#!/usr/bin/env python3
"""
🎬 লং কম্পাইলেশন বানাও — ১২-১৫ মিনিট · ১:১ (১০৮০×১০৮০) · অরিজিনাল কণ্ঠ · নিজের গান BGM

বটের "📺 লং ভিডিও ক্লিপ" বাটনের মতোই কাজ করে, কিন্তু টার্মিনাল থেকে চালানো যায়
(বট ব্যস্ত থাকলেও চলবে — আলাদা প্রসেস)।

ব্যবহার:
    ./.venv/bin/python tools/make_long.py <youtube-url>
    ./.venv/bin/python tools/make_long.py <youtube-url> --chat 7425534011   # চ্যাটেও পাঠাবে
    ./.venv/bin/python tools/make_long.py <youtube-url> --minutes 15 --segments 10

যা লাগবে: GEMINI_API_KEY (.env) — সেরা দৃশ্য বাছতে। কী না থাকলে সমান ভাগে ভাগ করে নেয়।
"""
from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from youtube_processor import (  # noqa: E402
    extract_video_id, get_video_transcript, get_video_duration,
    find_best_segments_with_gemini, download_youtube_clip,
    process_clip_copyright_bypass, mix_bgm_on_merged_video,
    format_seconds, parse_time, probe_size,
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def fallback_segments(duration: int, count: int, seg_len: int) -> list[dict]:
    """Gemini না পেলে: পুরো নাটকজুড়ে সমান ফাঁকে ফাঁকে সেগমেন্ট।"""
    out = []
    for i in range(count):
        frac = 0.04 + (0.92 - 0.04) * (i / max(1, count - 1))
        start = int(max(0, min(duration - seg_len - 2, duration * frac)))
        out.append({"start_time": format_seconds(start), "duration": min(seg_len, duration - start)})
    return out


def send_to_chat(path: Path, chat_id: str, caption: str) -> bool:
    """লোকাল Bot API দিয়ে ফাইলটা টেলিগ্রাম চ্যাটে পাঠাই (২ GB পর্যন্ত)।"""
    token = ""
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            token = line.split("=", 1)[1].strip()
            break
    if not token:
        log("❌ TELEGRAM_BOT_TOKEN নেই")
        return False
    port = os.environ.get("TGBOT_API_PORT", "8081")
    api = f"http://127.0.0.1:{port}"
    try:
        subprocess.run(["curl", "-s", "--max-time", "5", "-o", "/dev/null", f"{api}/"], check=True)
    except Exception:
        log("❌ লোকাল Bot API সার্ভার চলছে না — ./tools/local_bot_api.sh start")
        return False
    log(f"📤 পাঠাচ্ছি → chat {chat_id} ({path.stat().st_size / 1048576:.0f} MB)")
    t0 = time.time()
    r = subprocess.run(
        ["curl", "-s", "--max-time", "3600",
         "-F", f"chat_id={chat_id}",
         "-F", f"document=@{path}",
         "-F", f"caption={caption}",
         f"{api}/bot{token}/sendDocument"],
        capture_output=True, text=True)
    if '"ok":true' in (r.stdout or ""):
        log(f"✅ চ্যাটে পাঠানো হয়েছে ({time.time() - t0:.0f}s)")
        return True
    log(f"❌ পাঠানো যায়নি: {(r.stdout or r.stderr)[:300]}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--chat", default="", help="Telegram chat_id — দিলে ফাইলে পাঠিয়ে দেবে")
    ap.add_argument("--minutes", type=int, default=13, help="মোট দৈর্ঘ্য (ডিফল্ট ১৩ মিনিট)")
    ap.add_argument("--segments", type=int, default=9, help="কতগুলো দৃশ্য (ডিফল্ট ৯)")
    args = ap.parse_args()

    t_start = time.time()
    duration, title = get_video_duration(args.url)
    log(f"🎥 {title}")
    log(f"   দৈর্ঘ্য {format_seconds(duration)} · টার্গেট ~{args.minutes} মিনিট")

    video_id = extract_video_id(args.url)
    segments: list[dict] = []
    transcript = ""
    if video_id:
        log("🤖 ট্রান্সক্রিপ্ট আনা হচ্ছে…")
        try:
            transcript = get_video_transcript(video_id) or ""
        except Exception as e:
            log(f"   ট্রান্সক্রিপ্ট ব্যর্থ: {e}")
    if transcript:
        log("🤖 Gemini দিয়ে সেরা দৃশ্য বাছা হচ্ছে…")
        try:
            res = find_best_segments_with_gemini(transcript, duration, False) or {}
            segments = res.get("segments") or []
        except Exception as e:
            log(f"   Gemini ব্যর্থ: {e}")
    if not segments:
        seg_len = max(45, int(args.minutes * 60 / args.segments))
        segments = fallback_segments(duration, args.segments, seg_len)
        log(f"   ⚠️ Gemini সেগমেন্ট দেয়নি — সমান ভাগে {len(segments)}টা নিচ্ছি ({seg_len}s করে)")

    segs = []
    for s in segments:
        st = parse_time(str(s.get("start_time", "0")))
        if st >= duration:
            continue
        dl = int(s.get("duration") or 60)
        dl = min(dl, max(5, duration - st))
        segs.append((st, dl))
    log(f"📋 {len(segs)}টা দৃশ্য · মোট {sum(d for _, d in segs)}s")

    raws, procs = [], []
    try:
        for i, (st, dl) in enumerate(segs):
            raw = ROOT / f"long_raw_{i}.mp4"
            proc = ROOT / f"long_proc_{i}.mp4"
            raws.append(raw)
            log(f"📥 [{i+1}/{len(segs)}] ডাউনলোড {format_seconds(st)} + {dl}s …")
            download_youtube_clip(args.url, format_seconds(st), dl, str(raw))
            if not raw.exists() or raw.stat().st_size < 50_000:
                log(f"   ⚠️ ডাউনলোড খালি — বাদ")
                continue
            log(f"⚙️ [{i+1}/{len(segs)}] প্রসেস (১:১ · ১০৮০ · অরিজিনাল কণ্ঠ) …")
            process_clip_copyright_bypass(str(raw), str(proc), is_short=False, mix_bgm=False)
            procs.append(proc)
            try:  # ডিস্ক বাঁচাতে raw সাথে সাথে মুছি
                raw.unlink()
            except Exception:
                pass

        if not procs:
            log("❌ কোনো দৃশ্য প্রসেস হয়নি")
            return 1

        list_file = ROOT / "long_concat.txt"
        list_file.write_text("".join(f"file '{p}'\n" for p in procs), encoding="utf-8")
        merged = ROOT / "long_merged.mp4"
        log(f"🔗 {len(procs)}টা দৃশ্য জোড়া লাগাচ্ছি…")
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(list_file), "-c", "copy", str(merged)],
                       check=True, capture_output=True)
        for p in procs:
            try: p.unlink()
            except Exception: pass

        out = ROOT / "deliver" / f"long_{video_id or int(time.time())}.mp4"
        out.parent.mkdir(exist_ok=True)
        log("🎵 নিজের গান BGM মিক্স হচ্ছে…")
        mix_bgm_on_merged_video(str(merged), str(out))
        try: merged.unlink()
        except Exception: pass

        size_mb = out.stat().st_size / 1048576
        log(f"✅ তৈরি: {out} · {probe_size(out)} · {size_mb:.0f} MB · {(time.time()-t_start)/60:.1f} মিনিট")

        if args.chat:
            send_to_chat(out, args.chat,
                         f"🎬 {title[:80]} · লং কম্পাইলেশন · ১:১ ১০৮০ · {size_mb:.0f} MB")
        return 0
    finally:
        for f in raws + procs:
            try: f.unlink()
            except Exception: pass
        for extra in ("long_concat.txt", "long_merged.mp4"):
            try: (ROOT / extra).unlink()
            except Exception: pass


if __name__ == "__main__":
    sys.exit(main())
