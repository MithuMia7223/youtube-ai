#!/usr/bin/env python3
"""
🌿 কপিরাইট-ফ্রি ভিডিও মেকার (বট + ওয়েবসাইট দুটোই এটা ব্যবহার করে)
================================================================

লিংক দিলে:
  ১) শুধু **বিষয়** পড়ে (ভিডিও ডাউনলোড হয় না)
  ২) Gemini → ইংরেজি স্টক-কীওয়ার্ড
  ৩) Pexels (ফ্রি লাইসেন্স) → না পেলে Wikimedia Commons (CC0/CC)
  ৪) ১০৮০ ক্রপ · বার ছাড়া · CC0 BGM
  ৫) ফাইনাল ফাইল + ক্রেডিট ফাইল

ফলে মূল ভিডিওর **একটা ফ্রেমও** ব্যবহার হয় না → কপিরাইট ক্লেইমের সুযোগ নেই।

CLI:
    python free_maker.py "https://youtu.be/XXXX" 30 square
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))


def _log(msg: str) -> None:
    print(msg, flush=True)


def title_and_tags(url: str) -> tuple[str, str]:
    """লিংক থেকে শুধু শিরোনাম/ট্যাগ — ভিডিও ডাউনলোড করা হয় না।"""
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True,
                               "no_warnings": True}) as y:
            info = y.extract_info(url, download=False) or {}
        return (info.get("title") or "").strip(), ", ".join((info.get("tags") or [])[:8])
    except Exception as e:
        _log(f"      ⚠️ শিরোনাম পড়া যায়নি: {str(e)[:70]}")
        return "", ""


def keywords_for(title: str, tags: str) -> str:
    """Gemini দিয়ে ইংরেজি স্টক-কীওয়ার্ড, না পেলে শিরোনাম থেকে।"""
    if title:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            from google import genai
            c = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
            prompt = ("Give 6-10 ENGLISH stock-footage search keywords (comma separated, "
                      f"no explanation) for a video about: {title}. {tags}")
            for m in ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3-flash-preview"):
                try:
                    r = c.models.generate_content(model=m, contents=prompt)
                    cand = (getattr(r, "text", "") or "").strip().replace("\n", " ")
                    cand = " ".join(w.strip(" .,;\"'") for w in cand.split(",")[:6])
                    if cand and all(ord(ch) < 128 for ch in cand):
                        _log(f"      🔑 কীওয়ার্ড: {cand[:80]}")
                        return cand
                except Exception:
                    continue
        except Exception as e:
            _log(f"      ⚠️ Gemini ব্যর্থ: {str(e)[:60]}")
    words = " ".join(re.findall(r"[A-Za-z]{3,}", title)[:6]) or "cinematic nature"
    _log(f"      🔑 ফলব্যাক কীওয়ার্ড: {words}")
    return words


def make(url: str, dur: float = 30.0, mode: str = "square",
         outdir: str | Path = "deliver", name: str | None = None) -> Path:
    """লিংক → ১০০% কপিরাইট-ফ্রি ১০৮০ ভিডিও। রিটার্ন: ফাইনাল ফাইলের পাথ।"""
    t0 = time.time()
    outdir_p = Path(outdir)
    outdir_p.mkdir(parents=True, exist_ok=True)
    name = name or f"free_{time.strftime('%H%M%S')}"

    _log("[1/4] লিংকের বিষয় পড়া হচ্ছে (মূল ভিডিও নামানো হবে না) …")
    title, tags = title_and_tags(url)
    if title:
        _log(f"      📖 বিষয়: {title[:70]}")
    query = keywords_for(title, tags)

    _log(f"[2/4] কপিরাইট-ফ্রি ফুটেজ খোঁজা হচ্ছে: '{query[:60]}' …")
    import stock
    raw = outdir_p / f"{name}_raw.mp4"
    stock.build_free(query, float(dur), str(raw), mode, cc0_only=True)

    _log("[3/4] ১০৮০ প্রসেসিং (বার ছাড়া) …")
    import youtube_processor as yp
    final = outdir_p / f"{name}.mp4"
    yp.process_clip_copyright_bypass(str(raw), str(final),
                                     is_short=(mode != "long"),
                                     bgm_dir=str(ROOT / "assets" / "audio" / "cc0"),
                                     mix_bgm=False)

    _log("[4/4] CC0 BGM …")
    try:
        track = stock.fetch_cc0_music("calm cinematic piano music", float(dur)) \
            or stock.make_bgm(float(dur), str(outdir_p / f"{name}_bgm.wav"))
        mixed = outdir_p / f"{name}_mixed.mp4"
        stock.mix(str(final), str(track), str(mixed), bgm_vol=0.22)
        if mixed.exists() and mixed.stat().st_size > 50_000:
            mixed.replace(final)
            _log(f"      🎵 BGM: {Path(str(track)).name}")
    except Exception as e:
        _log(f"      ⚠️ BGM বাদ ({str(e)[:60]})")

    for p in outdir_p.glob(f"{name}_raw*"):
        try:
            p.unlink()
        except Exception:
            pass

    _log(f"✅ তৈরি: {final.name} · {final.stat().st_size / 1048576:.1f} MB · "
         f"{time.time() - t0:.0f}s · ১০০% কপিরাইট-ফ্রি")
    return final


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("ব্যবহার: python free_maker.py <link> [dur] [square|long]")
        sys.exit(1)
    p = make(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 30.0,
             sys.argv[3] if len(sys.argv) > 3 else "square")
    print(p)
