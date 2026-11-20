"""
tests_video_layout.py — ভিডিওর লেআউট/রেজোলিউশন রিগ্রেশন টেস্ট।

কেন: একবার ভিডিওর উপরে-নিচে কালো বার ফিরে এসেছিল আর আউটপুট ছিল 4K (1080p নয়)।
এই টেস্টগুলো সেই দুটোই পাহারা দেয়, আর বাংলা লেখার shaping-ও (NFC → ◌ সমস্যা)।

চালাও:  .venv/bin/python tests_video_layout.py
"""
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import video_creator as vc  # noqa: E402

try:
    import imageio_ffmpeg
    FF = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:                                     # pragma: no cover
    FF = "ffmpeg"

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name}  {detail}")
        FAILS.append(name)


# ── ১) কনফিগ ────────────────────────────────────────────────────────────────
print("▪ কনফিগ")
check("BLACK_BARS বন্ধ (বার থাকবে না)", vc.BLACK_BARS is False, f"BLACK_BARS={vc.BLACK_BARS}")
check("HD_OUTPUT চালু (1080p)", vc.HD_OUTPUT is True, f"HD_OUTPUT={vc.HD_OUTPUT}")


# ── ২) শর্টস টেমপ্লেটে বার নেই, লেখা আছে ───────────────────────────────────
print("▪ শর্টস টেমপ্লেট (1080×1920)")
flat = Image.new("RGB", (1080, 1920), (30, 90, 160))
frame = np.array(vc.apply_short_romantic_template(flat, "মাছ ধরার গল্প", "কোথায় গিয়েছিলে?", 0.8))
row_mid_top = frame[int(1920 * 0.06)].mean(axis=0)      # শিরোনামের পট্টি
check("উপরের ৬%-এ কালো বার নেই", row_mid_top.mean() > 40, f"গড় উজ্জ্বলতা {row_mid_top.mean():.0f}")
check("নিচের ৬%-এ কালো বার নেই", frame[int(1920 * 0.96)].mean() > 40)
# সাবটাইটেলের হলুদ লেখা ফ্রেমের ভিতরে আছে কি
yellow = ((frame[:, :, 0] > 180) & (frame[:, :, 1] > 180) & (frame[:, :, 2] < 90)).sum()
check("সাবটাইটেল (হলুদ) ফ্রেমে দৃশ্যমান", yellow > 500, f"হলুদ পিক্সেল {yellow}")
# ৪K-নির্দিষ্ট y=3000 হার্ডকোড আর নেই → নিচের অংশে লেখা
check("সাবটাইটেল ৭০-৯০% উচ্চতায়", ((frame[1340:1730, :, 0] > 180) & (frame[1340:1730, :, 1] > 180)).sum() > 300)


# ── ৩) ড্রামা টেমপ্লেটে বার/বাক্স নেই, বাংলা লেখা ঠিক ─────────────────────
print("▪ ড্রামা টেমপ্লেট (1080×1920)")
d = np.array(vc.draw_drama_frame(Image.new("RGB", (1080, 1920), (40, 70, 120)),
                                 "কেতু", "দাদু, তুমি কোথায় গিয়েছিলে এতক্ষণ?", "sad", 1.2, 5.0))
check("উপরের ১০%-এ বার নেই", d[:190].mean() > 40, f"গড় {d[:190].mean():.0f}")
check("নিচের ৩০%-এ বার নেই", d[-576:].mean() > 40, f"গড় {d[-576:].mean():.0f}")
check("টেক্সট-আউটলাইন আছে (হলুদ লেখা)", ((d[:, :, 0] > 170) & (d[:, :, 1] > 170) & (d[:, :, 2] < 110)).sum() > 400)


# ── ৪) NFD নরমালাইজ (Pillow-এ raqm নেই) ─────────────────────────────────────
print("▪ বাংলা shaping")
check("bn() NFD দেয়", vc.bn("কোথায়") == "ক\u09c7\u09beথায়", repr(vc.bn("কোথায়")))
check("bn() খালি ইনপুটে SecurityError দেয় না", vc.bn("") == "" and vc.bn(None) == "")


# ── ৫) আসল রেন্ডার: রেজোলিউশন + cropdetect ─────────────────────────────────
print("▪ আসল রেন্ডার (শর্টস, ১৬:৯ ভিডিও ক্লিপ → ৯:১৬)")
tmp = tempfile.mkdtemp(prefix="vlayout_")
clip = os.path.join(tmp, "land.mp4")
subprocess.run([FF, "-y", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=1280x720:rate=24:duration=2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", clip], check=True)
aud = os.path.join(tmp, "a.m4a")
subprocess.run([FF, "-y", "-v", "error", "-f", "lavfi", "-i",
                "anullsrc=r=44100:cl=mono", "-t", "2", "-c:a", "aac", aud], check=True)
out = os.path.join(tmp, "o.mp4")
vc._build_image_video([{"image_path": clip, "text": "কোথায় গিয়েছিলে?"}], aud, out,
                      is_short=True, topic="টেস্ট", cb=lambda m: None)

info = subprocess.run([FF, "-hide_banner", "-i", out], capture_output=True, text=True).stderr
check("আউটপুট 1080×1920", "1080x1920" in info, [l.strip() for l in info.splitlines() if "Video:" in l][:1])
cd = subprocess.run([FF, "-hide_banner", "-i", out, "-vf", "cropdetect=limit=24:round=2:reset=0",
                     "-f", "null", "-"], capture_output=True, text=True).stderr
crops = [l.split("crop=")[-1].strip() for l in cd.splitlines() if "crop=" in l]
check("cropdetect পুরো ফ্রেম (কালো বার নেই)", bool(crops) and crops[-1].startswith("1080:1920:0:0"),
      crops[-1] if crops else "cropdetect ব্যর্থ")

print()
if FAILS:
    print(f"❌ {len(FAILS)}টা ফেল: {FAILS}")
    sys.exit(1)
print("✅ সব লেআউট-টেস্ট পাস — বার নেই, 1080p, বাংলা লেখা ঠিক")
