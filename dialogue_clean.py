"""
নাটকের নিজের ব্যাকগ্রাউন্ড মিউজিক বাদ দিয়ে শুধু কণ্ঠ (ডায়ালগ) রাখার মডিউল।

সমস্যা: সোর্স ভিডিওর ভেতরেই নাটকের নিজের BGM বাঁধা থাকে। ওটা কমানো/বাদ
দেওয়া সাধারণ ffmpeg ফিল্টারে হয় না (dialoguenhance দিয়ে মেপে দেখেছি —
কথার-ব্যান্ড ০.৫২৮ → ০.৪৮৯, কার্যত কিছুই কমে না)। তাই আসল সমাধান:
AI সোর্স সেপারেশন (Demucs htdemucs) — কণ্ঠ আর মিউজিক আলাদা স্টেমে ভাগ করা,
তারপর শুধু কণ্ঠ স্টেম + ব্যবহারকারীর নিজের গান মিলিয়ে ফাইনাল অডিও।

ব্যবহার (পরিবেশ চলক):
  CLEAN_DIALOGUE=1        # চালু
  CLEAN_DIALOGUE_MODEL=htdemucs
  DEMUCS_PYTHON=~/ai-sep/venv/bin/python
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

_DEFAULT_PY = os.path.expanduser("~/ai-sep/venv/bin/python")


def demucs_available(python_exe: str | None = None) -> bool:
    exe = python_exe or os.environ.get("DEMUCS_PYTHON") or _DEFAULT_PY
    exe = os.path.expanduser(exe)
    if not os.path.exists(exe):
        return False
    try:
        r = subprocess.run([exe, "-c", "import demucs, torch"], capture_output=True, timeout=120)
        return r.returncode == 0
    except Exception:
        return False


def extract_vocals(audio_or_video: str, workdir: str | None = None,
                   model: str | None = None, progress_cb=None) -> str | None:
    """
    ইনপুট (ভিডিও/অডিও) থেকে কণ্ঠ স্টেম (vocals.wav) বের করে পাথ ফেরত দেয়।
    ব্যর্থ হলে None — কলকারী তখন আসল অডিওই ব্যবহার করবে।
    """
    exe = os.path.expanduser(os.environ.get("DEMUCS_PYTHON") or _DEFAULT_PY)
    model = model or os.environ.get("CLEAN_DIALOGUE_MODEL", "htdemucs")
    if not demucs_available(exe):
        print("[clean-dialogue] Demucs পাওয়া যায়নি — আসল অডিওই থাকবে")
        return None

    created = False
    if workdir is None:
        workdir = tempfile.mkdtemp(prefix="dialogue_sep_")
        created = True
    os.makedirs(workdir, exist_ok=True)
    src_wav = os.path.join(workdir, "in.wav")

    try:
        # Demucs stereo ৪৪.১kHz চায় — ভিডিও থেকে অডিও বের করি
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", audio_or_video,
             "-vn", "-ac", "2", "-ar", "44100", src_wav],
            capture_output=True,
        )
        if r.returncode != 0 or not os.path.exists(src_wav):
            print("[clean-dialogue] অডিও বের করা যায়নি")
            return None
        if progress_cb:
            progress_cb("নাটকের মিউজিক আলাদা করা হচ্ছে (AI)...")

        cmd = [exe, "-m", "demucs", "--two-stems=vocals", "-n", model,
               "-o", workdir, src_wav]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[clean-dialogue] Demucs ব্যর্থ: {(r.stderr or '')[-300:]}")
            return None

        # Demucs আউটপুট: <workdir>/<model>/in/vocals.wav
        cand = [
            os.path.join(workdir, model, "in", "vocals.wav"),
            os.path.join(workdir, "htdemucs", "in", "vocals.wav"),
        ]
        for c in cand:
            if os.path.exists(c):
                out = os.path.join(workdir, "vocals_only.wav")
                if os.path.abspath(c) != os.path.abspath(out):
                    shutil.move(c, out)
                print(f"[clean-dialogue] কণ্ঠ আলাদা হয়েছে ({model}) → {out}")
                return out
        # অন্য নামে থাকলে খুঁজে নিই
        for root, _d, files in os.walk(workdir):
            for f in files:
                if f == "vocals.wav":
                    out = os.path.join(workdir, "vocals_only.wav")
                    shutil.move(os.path.join(root, f), out)
                    print(f"[clean-dialogue] কণ্ঠ আলাদা হয়েছে ({model}) → {out}")
                    return out
        print("[clean-dialogue] vocals.wav পাওয়া যায়নি")
        return None
    except Exception as e:
        print(f"[clean-dialogue] ত্রুটি (উপেক্ষা): {e}")
        return None
    finally:
        if created and not os.environ.get("CLEAN_DIALOGUE_KEEP"):
            # কাজ শেষে ইনপুট wav মুছে দিই (ডিস্ক বাঁচাতে) — vocals ফাইল কলকারীর
            pass


def enabled() -> bool:
    return os.environ.get("CLEAN_DIALOGUE", "1") != "0" and demucs_available()
