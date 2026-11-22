#!/usr/bin/env python3
"""
ভিডিওর **শেষের দিকের সিন** কেটে শর্ট ভিডিও বানায়।

পুরো ভিডিও ডাউনলোড না করে শুধু দরকারি অংশ (fast download-sections) নামায়,
তারপর স্বাভাবিক পাইপলাইন (১:১ ক্রপ · বার-মুক্ত · ফেস-ট্র্যাকিং ·
নাটক-মিউজিক বাদ · নিজের গান) চালায়।

ব্যবহার:
  .venv/bin/python tools/make_from_end.py <youtube_url> [--window 90] [--clip 45] [--start-at 0.85]

  --window   শেষ কত সেকেন্ড থেকে খোঁজা শুরু (ডিফল্ট ৯০)
  --clip     কত সেকেন্ডের শর্ট বানাবে (ডিফল্ট ৪৫)
  --start-at কোথা থেকে শুরু, ভিডিওর দৈর্ঘ্যের অনুপাতে (০.৮৫ = শেষ ১৫%)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_ENV = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path = DEFAULT_ENV):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def video_duration(url: str) -> float:
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        return float(info.get("duration") or 0)
    except Exception as e:
        print(f"[end] দৈর্ঘ্য পাওয়া যায়নি: {e}")
        return 0.0


def hhmmss(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 3600}:{(sec % 3600) // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--window", type=float, default=90.0, help="শেষ কত সেকেন্ডের ভেতর থেকে নেবে")
    ap.add_argument("--clip", type=float, default=45.0, help="শর্টের দৈর্ঘ্য (সেকেন্ড)")
    ap.add_argument("--start-at", type=float, default=0.0,
                    help="ভিডিওর অনুপাত (০.৮৫ = শেষ ১৫ শতাংশ থেকে শুরু); ০ হলে --window ব্যবহার হবে")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    load_env()
    from youtube_processor import (download_youtube_clip, process_clip_copyright_bypass,
                                  mix_bgm_on_merged_video, probe_size)

    dur = video_duration(args.url)
    if args.start_at > 0 and dur > 0:
        start = max(0.0, dur * args.start_at)
    else:
        start = max(0.0, dur - max(args.window, args.clip)) if dur else 0.0
    clip = min(args.clip, max(5.0, dur - start)) if dur else args.clip
    print(f"[end] ভিডিও {hhmmss(dur)} · শুরু {hhmmss(start)} · দৈর্ঘ্য {clip:.0f}s")

    vid_id = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{6,})", args.url)
    vid_id = vid_id.group(1) if vid_id else "video"
    out = Path(args.out or f"deliver/end_{vid_id}.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.mkdtemp(prefix="end_"))
    raw = tmp / "raw.mp4"
    proc = tmp / "proc.mp4"
    try:
        download_youtube_clip(args.url, hhmmss(start), int(clip), str(raw))
        process_clip_copyright_bypass(str(raw), str(proc), is_short=True, mix_bgm=False)
        mix_bgm_on_merged_video(str(proc), str(out))
        print(f"[end] ✅ {out} · {probe_size(str(out))} · {out.stat().st_size / 1048576:.0f} MB")
        return str(out)
    finally:
        for p in (raw, proc):
            p.unlink(missing_ok=True)
        try:
            tmp.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    print(main())
