#!/usr/bin/env python3
"""
ট্র্যাকিং কোয়ালিটি মাপার টুল।

আউটপুট ভিডিওর ফ্রেমে YuNet দিয়ে মুখ খুঁজে মাপে:
  • কত % ফ্রেমে মুখ পাওয়া গেছে (না পেলে মুখ ফ্রেমের বাইরে/কাটা)
  • মুখের কেন্দ্র ফ্রেমের কেন্দ্র থেকে কত দূরে (০ = নিখুঁত মাঝখানে)
  • কত % ফ্রেমে মুখ কিনারায় (কাটার ঝুঁকিতে)

ব্যবহার:
  .venv/bin/python tools/check_tracking.py deliver/xxx.mp4
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import numpy as np

YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")


def load_yunet():
    import cv2
    cache = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "assets", "models", "face_detection_yunet_2023mar.onnx")
    if not os.path.exists(cache):
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        import urllib.request
        urllib.request.urlretrieve(YUNET_URL, cache)
    return cv2, cv2.FaceDetectorYN.create(cache, "", (320, 320), 0.45, 0.3, 5000)


def analyse(path: str, fps: float = 2.0, w: int = 320, verbose: bool = True):
    cv2, det = load_yunet()
    probe = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path,
         "-vf", f"fps={fps},scale={w}:-2", "-pix_fmt", "bgr24",
         "-f", "rawvideo", "pipe:1"],
        capture_output=True).stdout
    # ফ্রেমের উচ্চতা জানতে এক ফ্রেম আলাদা করে নিই
    one = subprocess.run(["ffmpeg", "-v", "error", "-i", path,
                          "-vf", f"scale={w}:-2", "-frames:v", "1",
                          "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1"],
                         capture_output=True).stdout
    h = len(one) // (w * 3)
    frames = np.frombuffer(probe[: len(probe) // (w * h * 3) * (w * h * 3)], np.uint8)
    frames = frames.reshape(-1, h, w, 3)
    det.setInputSize((w, h))

    total = len(frames)
    hits = 0
    offsets = []
    edge = 0
    for f in frames:
        _r, faces = det.detect(f)
        if faces is None or len(faces) == 0:
            continue
        hits += 1
        # সবচেয়ে বড় মুখ
        f0 = max(faces, key=lambda c: c[2] * c[3])
        cx = (f0[0] + f0[2] / 2) / w
        cy = (f0[1] + f0[3] / 2) / h
        offsets.append((cx, cy))
        # মুখের বক্সের কিনারা ফ্রেমের ৫% এর ভিতরে থাকলে = কাটার ঝুঁকি
        if f0[0] < 0.02 * w or f0[1] < 0.02 * h or \
           f0[0] + f0[2] > 0.98 * w or f0[1] + f0[3] > 0.98 * h:
            edge += 1

    seen = hits / total if total else 0
    if offsets:
        dx = np.array([abs(x - 0.5) for x, _ in offsets])
        dy = np.array([abs(y - 0.5) for _, y in offsets])
        mean_off = float((dx.mean() + dy.mean()) / 2)
        far = float((np.maximum(dx, dy) > 0.30).mean())
    else:
        mean_off, far = float("nan"), float("nan")
    res = {
        "frames": total,
        "face_seen_pct": round(seen * 100, 1),
        "mean_offset": round(mean_off, 3),
        "edge_pct": round(edge / hits * 100, 1) if hits else 0.0,
        "far_pct": round(far * 100, 1),
    }
    if verbose:
        print(f"{os.path.basename(path)}: ফ্রেম {res['frames']} | "
              f"মুখ পাওয়া {res['face_seen_pct']}% | "
              f"কেন্দ্র থেকে সরে {res['mean_offset']:.3f} | "
              f"কিনারায় {res['edge_pct']}% | অনেক দূরে {res['far_pct']}%")
    return res


if __name__ == "__main__":
    for p in sys.argv[1:]:
        analyse(p)
