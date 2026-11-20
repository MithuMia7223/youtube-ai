#!/usr/bin/env python3
"""
letterbox (উপরে-নিচে কালো বার) রিগ্রেশন-টেস্ট
============================================

সমস্যা: বট উৎস ভিডিওকে `scale=1080:1920` করে স্ট্রেচ করে। উৎসে সিনেমার মতো
কালো বার **পোড়া** থাকলে স্ট্রেচে বার আরও মোটা হয়ে যায়। মাপা কেস:
`processed_7425534011.mp4` → ১০৮০×১৯২০ ফ্রেমে ৬২px (উপরে) + ১৬৪px (নিচে) = ১১.৮%।

চালাও:  ./.venv/bin/python tests_letterbox_check.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from youtube_processor import detect_letterbox, probe_size  # noqa: E402

FF = shutil.which("ffmpeg") or "ffmpeg"
ok_n = fail_n = 0


def check(name, cond, detail=""):
    global ok_n, fail_n
    if cond:
        ok_n += 1
        print(f"  ✅ {name}")
    else:
        fail_n += 1
        print(f"  ❌ {name} — {detail}")


def crop_of(path):
    out = subprocess.run(
        [FF, "-hide_banner", "-nostats", "-i", path,
         "-vf", "cropdetect=limit=20:round=2:reset=0", "-frames:v", "40", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    hits = [ln.split("crop=")[-1].split()[0] for ln in out.splitlines() if "crop=" in ln]
    return hits[-1] if hits else ""


def make_bar_clip(path, w=1280, h=720, bar=120):
    """উপরে-নিচে `bar` px কালো বার পোড়ানো টেস্ট-ক্লিপ।"""
    subprocess.run(
        [FF, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=orange:s={w}x{h}:d=2:r=25",
         "-vf", f"drawbox=x=0:y=0:w={w}:h={bar}:color=black:t=fill,"
                f"drawbox=x=0:y={h-bar}:w={w}:h={bar}:color=black:t=fill",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", path],
        check=True)


def main():
    tmp = tempfile.mkdtemp(prefix="letterbox_")
    try:
        # ১) কালো বার আছে → ধরা পড়ে
        src = os.path.join(tmp, "barred.mp4")
        make_bar_clip(src, bar=120)
        got = detect_letterbox(src)
        check("পোড়া কালো বার সনাক্ত হয়", bool(got), f"পাওয়া: {got}")
        if got:
            w, h, x, y = (int(v) for v in got.replace("crop=", "").rstrip(",").split(":"))
            check("ক্রপ-জ্যামিতি ঠিক (±৬px)", abs(h - 480) <= 6 and abs(y - 120) <= 6,
                  f"পাওয়া {w}x{h}+{x}+{y}, চাওয়া 1280x480+0+120")
            # ২) ক্রপের পরে আর বার নেই
            fixed = os.path.join(tmp, "fixed.mp4")
            subprocess.run(
                [FF, "-y", "-v", "error", "-i", src,
                 "-vf", f"{got.rstrip(',')},scale=1080:1920,setsar=1",
                 "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", fixed],
                check=True)
            c = crop_of(fixed)
            check("ক্রপের পরে ফ্রেম ভরা (বার নেই)", c.startswith("1080:1920"), f"cropdetect={c}")

        # ৩) পরিষ্কার ফাইলে ভুল-ধরা পড়ে না (false positive নেই)
        clean = os.path.join(tmp, "clean.mp4")
        make_bar_clip(clean, bar=0)
        check("বার-ছাড়া ফাইলে কিছু কাটে না", detect_letterbox(clean) is None,
              f"ভুল করে পেল: {detect_letterbox(clean)}")

        # ৪) probe_size ঠিক
        check("probe_size সঠিক", probe_size(clean) == (1280, 720), f"পাওয়া: {probe_size(clean)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nফলাফল: ✅ {ok_n} পাস · ❌ {fail_n} ফেল")
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
