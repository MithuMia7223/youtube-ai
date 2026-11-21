#!/usr/bin/env python3
"""
🎯 অটো-হাইলাইট — ভিডিওর "মূল অংশ" নিজেই খুঁজে বের করে
=======================================================

বট যেমন অটোমেশন করে কেটে দেয়, এখানেও তাই: পুরো ভিডিও বিশ্লেষণ করে
**দর্শকের মনোযোগ টানার অংশগুলো** স্কোর করি, তারপর শুধু সেগুলো রেখে
বাকিটা ফেলে দিই।

স্কোর কীভাবে হয় (৩টি সংকেত, একসাথে):
  ১. **শব্দের জোর** — অডিও RMS (চিৎকার, গান, বিস্ফোরণ = বেশি)
  ২. **দৃশ্য-পরিবর্তন** — ffmpeg `scdet` (দ্রুত কাট = অ্যাকশন)
  ৩. **নড়াচড়া** — ফ্রেম-ডিফ (ক্যামেরা মুভমেন্ট, ভিড়)

তারপর গড়-স্মুথিং → সবচেয়ে বেশি স্কোরের অ-ওভারল্যাপিং উইন্ডো বাছাই।
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _ff() -> str:
    for c in (shutil.which("ffmpeg"),
              os.path.expanduser("~/.local/bin/ffmpeg"),
              "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if c and os.path.exists(c):
            return c
    return "ffmpeg"


FF = _ff()


def duration(path: str) -> float:
    out = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True,
                         text=True, timeout=60).stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.?\d*)", out)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def audio_energy(path: str, hop: float = 0.1) -> list[float]:
    """
    প্রতি ০.১ সেকেন্ডে **মোমেন্টারি লাউডনেস** (EBU R128, dB)।
    আগে `astats`-এর reset ব্যবহৃত হতো → মান কার্যত ধ্রুবক আসত; ebur128 নির্ভরযোগ্য।
    """
    cmd = [FF, "-hide_banner", "-v", "error", "-hwaccel", "videotoolbox", "-i", path, "-vn",
           "-af", "ebur128=metadata=1,ametadata=print:key=lavfi.r128.M:file=-",
           "-f", "null", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        vals = []
        for x in re.findall(r"lavfi\.r128\.M=(-?[\d.]+)", p.stdout or ""):
            v = float(x)
            vals.append(-70.0 if v < -70 else v)      # নীরবতা = -70 dB ফ্লোর
        return vals
    except Exception:
        return []


def scene_scores(path: str) -> dict[int, float]:
    """
    `scdet` দিয়ে দৃশ্য-পরিবর্তনের স্কোর (সেকেন্ড → স্কোর)।

    **কীফ্রেম-অনলি ডিকোড** (`-skip_frame nokey`) — পুরো ১০ মিনিটের ১০৮০ ভিডিও
    ২ সেকেন্ডে স্ক্যান হয় (আগে ১১৪s লাগত)। কীফ্রেম সাধারণত কাটের কাছেই পড়ে,
    তাই কাট-ঘনত্বের সূচক হিসেবে যথেষ্ট; খুব কম কীফ্রেম পেলে ফুল ডিকোডে ফিরি।
    """
    def run(extra: list[str]) -> dict[int, float]:
        cmd = [FF, "-hide_banner", "-v", "info"] + extra + ["-i", path, "-an",
               "-vf", "scale=256:-2,scdet=threshold=8,"
                      "metadata=print:key=lavfi.scd.score:file=-",
               "-f", "null", "-"]
        out: dict[int, float] = {}
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            cur = 0.0
            for line in (p.stdout or "").splitlines():
                m = re.search(r"pts_time:([\d.]+)", line)
                if m:
                    cur = float(m.group(1))
                m = re.search(r"lavfi\.scd\.score=([\d.]+)", line)
                if m:
                    sec = int(cur)
                    out[sec] = max(out.get(sec, 0.0), float(m.group(1)))
        except Exception:
            pass
        return out

    quick = run(["-skip_frame", "nokey"])
    if len(quick) >= 20:
        return quick
    return run([])


def face_scores(path: str, fps: float = 1.0, width: int = 360) -> list[float]:
    """
    প্রতি সেকেন্ডে **মুখের স্কোর** — বড়/কাছের মুখ = ইমোশন, একাধিক মুখ = দৃশ্যের
    মূল মুহূর্ত (হাসি, কান্না, ঝগড়া)। Haar ক্যাসকেড (OpenCV) দিয়ে মাপি।

    স্কোর = Σ (face_w*face_h)/(W*H) — কতটা জুড়ে মুখ আছে, তাই ক্লোজ-আপ বেশি দাম পায়।
    """
    try:
        import cv2
    except Exception:
        return []
    tmp = Path(tempfile.mkdtemp(prefix="hl_face_"))
    try:
        subprocess.run([FF, "-y", "-v", "error", "-i", path, "-an",
                        "-vf", f"fps={fps},scale={width}:-2",
                        "-q:v", "4", str(tmp / "f_%05d.jpg")], timeout=1800)
        files = sorted(tmp.glob("f_*.jpg"))
        if not files:
            return []
        casc = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        out = []
        for f in files:
            img = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
            if img is None:
                out.append(0.0)
                continue
            H, W = img.shape[:2]
            faces = casc.detectMultiScale(img, scaleFactor=1.2, minNeighbors=5,
                                          minSize=(int(W * 0.08), int(W * 0.08)))
            sc = sum((w * h) / float(W * H) for (x, y, w, h) in faces)
            out.append(min(1.0, sc * 3.0))       # ৩৩% ফ্রেম-কভার = ফুল স্কোর
        return out
    except Exception as e:
        print(f"   ⚠️ মুখ শনাক্তকরণ ব্যর্থ: {str(e)[:60]}")
        return []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _norm(v: list[float]) -> list[float]:
    if not v:
        return []
    lo, hi = min(v), max(v)
    if hi - lo < 1e-9:
        return [0.5] * len(v)
    return [(x - lo) / (hi - lo) for x in v]


def _face_window(path: str, t0: float, dur: float) -> float:
    """শুধু একটা উইন্ডোতে মুখ-স্কোর (গড়) — পুরো ভিডিও স্ক্যান করার দরকার নেই।"""
    tmp = Path(tempfile.mkdtemp(prefix="hl_fw_"))
    try:
        try:
            import cv2
        except Exception:
            return 0.0
        subprocess.run([FF, "-y", "-v", "error", "-ss", f"{t0:.2f}", "-t", f"{dur:.2f}",
                        "-hwaccel", "videotoolbox", "-i", path, "-an", "-vf", "fps=1,scale=360:-2", "-q:v", "4",
                        str(tmp / "f_%03d.jpg")], timeout=600)
        files = sorted(tmp.glob("f_*.jpg"))
        if not files:
            return 0.0
        casc = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        tot = []
        for f in files:
            img = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            H, W = img.shape[:2]
            faces = casc.detectMultiScale(img, scaleFactor=1.2, minNeighbors=5,
                                          minSize=(int(W * 0.08), int(W * 0.08)))
            tot.append(min(1.0, sum((w * h) / float(W * H) for (_, _, w, h) in faces) * 3.0))
        return sum(tot) / len(tot) if tot else 0.0
    except Exception:
        return 0.0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def detect(path: str, clip_len: float = 8.0, top: int = 6,
           min_gap: float = 2.0, total: float | None = None) -> list[dict]:
    """
    দুই ধাপে হাইলাইট বাছাই (দ্রুত + নিখুঁত):

    ধাপ ১ — পুরো ভিডিওর **শব্দের আবেগ + দৃশ্য-পরিবর্তন** থেকে সেরা উইন্ডো বাছি
             (সস্তা, ১০ মিনিটের ভিডিও ~২০s)
    ধাপ ২ — শুধু ওই কয়েকটা উইন্ডোতে **মুখের ক্লোজ-আপ** মাপি (ইমোশন)
             → চূড়ান্ত স্কোর = ০.৬ × ধাপ-১ + ০.৪ × মুখ
    """
    dur = duration(path)
    if dur <= 0:
        return []
    energy = audio_energy(path, hop=0.1)
    scenes = scene_scores(path)

    n_sec = int(dur) + 1
    if energy:
        per = max(1, round(1.0 / 0.1))
        sec_energy = []
        for s in range(n_sec):
            chunk = energy[s * per:(s + 1) * per]
            sec_energy.append(sum(chunk) / len(chunk) if chunk else -70.0)
        ne = _norm(sec_energy)
    else:
        ne = [0.0] * n_sec
    max_sc = max(scenes.values()) if scenes else 1.0
    ns = [min(1.0, scenes.get(s, 0.0) / max(max_sc, 1e-6)) for s in range(n_sec)]

    coarse = [0.75 * ne[s] + 0.25 * ns[s] for s in range(n_sec)]

    # ── ধাপ ১: সেরা K উইন্ডো (top × ৩, পরে মুখ দিয়ে ছাঁটাই) ──
    K = max(top * 3, 6)
    order = sorted(range(n_sec), key=lambda s: -coarse[s])
    cand: list[dict] = []
    for s in order:
        if len(cand) >= K:
            break
        st = float(s)
        if st + clip_len > dur:
            st = max(0.0, dur - clip_len)
        if any(abs(st - c["start"]) < clip_len + min_gap for c in cand):
            continue
        cand.append({"start": round(st, 2), "dur": round(min(clip_len, dur), 2),
                     "coarse": round(float(coarse[s]), 3)})

    # ── ধাপ ২: মুখের ক্লোজ-আপ (ইমোশন) — শুধু প্রার্থীদের উপর ──
    for c in cand:
        c["face"] = round(float(_face_window(path, c["start"], c["dur"])), 3)
    for c in cand:
        c["score"] = round(float(0.6 * c["coarse"] + 0.4 * c["face"]), 3)
    cand.sort(key=lambda c: -c["score"])

    picked: list[dict] = []
    picked_total = 0.0
    for c in cand:
        if len(picked) >= top:
            break
        if any(abs(c["start"] - p["start"]) < clip_len + min_gap for p in picked):
            continue
        picked.append({"start": c["start"], "dur": c["dur"], "score": c["score"],
                       "face": c["face"], "coarse": c["coarse"]})
        picked_total += c["dur"]
        if total and picked_total >= total:
            break

    picked.sort(key=lambda p: p["start"])
    return picked


def cut(path: str, segs: list[dict], out: str, mute_original: bool = True) -> str:
    """
    সেগমেন্টগুলো কেটে এক ফাইলে জোড়া দেয় (re-encode, স্মুথ কাট)।
    `mute_original=True` → আসল অডিও বাদ (ভয়েসওভার/BGM পরে বসবে)।
    """
    if not segs:
        raise SystemExit("কোনো সেগমেন্ট নেই")
    tmp = Path(tempfile.mkdtemp(prefix="hl_"))
    try:
        parts = []
        for i, s in enumerate(segs):
            p = tmp / f"p{i:02d}.mp4"
            cmd = [FF, "-y", "-v", "error", "-ss", str(s["start"]), "-t", str(s["dur"]),
                   "-i", path, "-vf", "fps=30,setsar=1",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                   "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k"]
            if mute_original:
                cmd += ["-an"]
            cmd.append(str(p))
            subprocess.run(cmd, check=True)
            parts.append(p)
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        subprocess.run([FF, "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", str(lst), "-c", "copy", out], check=True)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap_flags = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(ap_flags) < 2:
        print("ব্যবহার: python web/highlights.py <video> <out.mp4> [--clip=8] [--top=6] [--keep-audio]")
        return 2
    src, out = ap_flags[0], ap_flags[1]
    clip_len = next((float(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--clip=")), 8.0)
    top = next((int(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--top=")), 6)
    segs = detect(src, clip_len=clip_len, top=top)
    print(json.dumps({"duration": duration(src), "segments": segs}, ensure_ascii=False, indent=2))
    cut(src, segs, out, mute_original="--keep-audio" not in sys.argv)
    print(f"✅ {out} — {sum(s['dur'] for s in segs):.0f} সেকেন্ড হাইলাইট")
    return 0


if __name__ == "__main__":
    sys.exit(main())
