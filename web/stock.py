#!/usr/bin/env python3
"""
🌿 কপিরাইট-ফ্রি সোর্স — Pexels ভিডিও + নিজের বানানো BGM
========================================================

Pexels-এর সব ভিডিও **Pexels License**-এ — বাণিজ্যিক ব্যবহার, রিমিক্স, বিতরণ
সবই ফ্রি, অ্যাট্রিবিউশন বাধ্যতামূলক নয়। তাই এখান থেকে বানানো ভিডিও
**১০০% কপিরাইট-ফ্রি** (কোনো Content ID ম্যাচ নেই)।

BGM: `assets/audio/cc0/` ফোল্ডারে রাখা ট্র্যাক, নাহলে ffmpeg দিয়ে **আমরাই
জেনারেট করি** (সাইন-ওয়েভ প্যাড) — সেটাও ১০০% আমাদের, লাইসেন্স-ঝামেলা নেই।

ব্যবহার (worker থেকে):
    python web/stock.py --query "rain city night" --dur 30 --out /tmp/x.mp4 --aspect square
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
def _find_ff() -> str:
    """launchd-এর PATH ছোট — তাই ffmpeg এর সম্ভাব্য সব জায়গা দেখি।"""
    import glob
    for c in (shutil.which("ffmpeg"),
              os.path.expanduser("~/.local/bin/ffmpeg"),
              "/opt/homebrew/bin/ffmpeg",
              "/usr/local/bin/ffmpeg"):
        if c and os.path.exists(c):
            return c
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    hits = glob.glob(os.path.expanduser("~/.venv*/bin/ffmpeg")) + glob.glob("/usr/local/bin/ffmpeg*")
    return hits[0] if hits else "ffmpeg"


FF = _find_ff()
_UA = "VideoVault/1.0 (https://github.com/MithuMia7223/youtube-ai; mithumia7223@gmail.com)"


def _ssl():
    """macOS-এর সিস্টেম Python-এ CA সার্টিফিকেট থাকে না → certifi ব্যবহার করি।"""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()
AUDIO = ROOT / "assets" / "audio"


def _key() -> str:
    if os.environ.get("PEXELS_API_KEY"):
        return os.environ["PEXELS_API_KEY"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("PEXELS_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("PEXELS_API_KEY নেই (.env-এ দাও)")


_PEXELS_DEAD_UNTIL = 0.0


def _pexels_ok() -> bool:
    return time.time() > _PEXELS_DEAD_UNTIL


def _mark_pexels_dead(reason: str) -> None:
    global _PEXELS_DEAD_UNTIL
    _PEXELS_DEAD_UNTIL = time.time() + 600
    print(f"   ⚠️ Pexels বন্ধ রাখা হলো ১০ মিনিট ({reason}) — নতুন কী লাগবে: pexels.com/api")


def search(query: str, orientation: str = "portrait", per_page: int = 15) -> list[dict]:
    """Pexels ভিডিও সার্চ — শুধু HD+ ফাইল, ওয়াটারমার্কবিহীন ওরিজিনাল।"""
    if not _pexels_ok():
        raise SystemExit("Pexels কী অবৈধ (১০ মিনিটের জন্য বন্ধ)")
    q = urllib.parse.quote(query)
    url = (f"https://api.pexels.com/videos/search?query={q}"
           f"&orientation={orientation}&per_page={per_page}&size=large")
    req = urllib.request.Request(url, headers={"Authorization": _key(),
                                               "User-Agent": "video-vault/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl()) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as he:
        if he.code in (401, 403):
            _mark_pexels_dead(f"HTTP {he.code}")
        raise
    out = []
    for v in data.get("videos", []):
        files = [f for f in v.get("video_files", [])
                 if f.get("file_type") == "video/mp4" and f.get("link")]
        if not files:
            continue
        files.sort(key=lambda f: (f.get("width") or 0) * (f.get("height") or 0))
        # ছোট দিক ≥ ১০৮০ হলে সেটাই সবচেয়ে ছোট ফাইল — ১০৮০ আউটপুটে আপস্কেল লাগে না
        hd = [f for f in files if min(int(f.get("width") or 0), int(f.get("height") or 0)) >= 1000]
        pick = hd[0] if hd else files[-1]
        out.append({"id": v.get("id"), "url": pick["link"],
                    "w": pick.get("width"), "h": pick.get("height"),
                    "dur": v.get("duration", 0), "by": v.get("user", {}).get("name", "")})
    return out


def download(clips: list[dict], tmp: Path) -> list[Path]:
    paths = []
    for i, c in enumerate(clips):
        p = tmp / f"clip{i:02d}.mp4"
        try:
            req = urllib.request.Request(c["url"], headers={"User-Agent": "VideoVault/1.0 (https://github.com/MithuMia7223/youtube-ai; mithumia7223@gmail.com)"})
            with urllib.request.urlopen(req, timeout=90, context=_ssl()) as r, open(p, "wb") as f:
                shutil.copyfileobj(r, f, 1024 * 256)
            if p.stat().st_size > 50_000:
                paths.append(p)
                print(f"   ⬇️ clip {i} — {c['w']}x{c['h']} · {p.stat().st_size/1048576:.1f} MB · {c['by']}")
        except Exception as e:
            print(f"   ⚠️ clip {i} নামানো যায়নি: {e}")
    return paths


def build(query: str, dur: float, out: str, aspect: str = "square") -> str:
    """খোঁজা → নামানো → জোড়া লাগানো (ক্রসফেড) → একটাই ভিডিও।"""
    orient = "portrait" if aspect in ("square", "portrait") else "landscape"
    clips = search(query, orientation=orient)
    if not clips:
        # পোর্ট্রেট না পেলে ল্যান্ডস্কেপ দিয়ে চেষ্টা (পরে ক্রপ হবে)
        clips = search(query, orientation="landscape")
    if not clips:
        raise SystemExit(f"'{query}' — Pexels-এ কোনো ভিডিও পাওয়া যায়নি")
    random.shuffle(clips)
    tmp = Path(tempfile.mkdtemp(prefix="pexels_"))
    try:
        files = download(clips, tmp)
        if not files:
            raise SystemExit("একটাও ক্লিপ নামানো যায়নি (নেট?)")
        # প্রতিটা ক্লিপ ৪s করে, দরকার হলে লুপ
        per = 4.0
        need = max(1, math.ceil(dur / per))
        seq = []
        while len(seq) < need:
            seq.extend(files)
        seq = seq[:need]
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in seq), encoding="utf-8")
        joined = tmp / "joined.mp4"
        subprocess.run([FF, "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", str(lst), "-t", f"{dur:.2f}",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                        "-pix_fmt", "yuv420p", "-an", str(joined)], check=True)
        shutil.copy2(joined, out)
        print(f"   ✅ স্টক ভিডিও তৈরি: {out} ({dur:.0f}s, {len(seq)} ক্লিপ)")
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── BGM: নিজের বানানো (১০০% ফ্রি) ───────────────────────────────────────────
def make_bgm(dur: float, out: str, mood: str = "calm") -> str:
    """
    ffmpeg দিয়ে অ্যাম্বিয়েন্ট প্যাড — কোনো রেকর্ডিং/গান নেই, তাই Content ID
    কখনো ধরবে না। `assets/audio/cc0/`-এ ট্র্যাক থাকলে সেটাই আগে ব্যবহার হয়।
    """
    cc0_dir = AUDIO / "cc0"
    if cc0_dir.exists():
        tracks = sorted(list(cc0_dir.glob("*.mp3")) + list(cc0_dir.glob("*.wav"))
                        + list(cc0_dir.glob("*.m4a")))
        if tracks:
            src = random.choice(tracks)
            subprocess.run([FF, "-y", "-v", "error", "-stream_loop", "-1", "-i", str(src),
                            "-t", f"{dur:.2f}", "-af", "volume=0.5,afade=t=in:d=1.5,"
                            f"afade=t=out:st={max(0, dur-2):.1f}:d=2",
                            "-ac", "2", "-ar", "44100", out], check=True)
            print(f"   🎵 CC0 ট্র্যাক ব্যবহার: {src.name}")
            return out

    # জেনারেটেড প্যাড: A মাইনর — ৩টা সাইন একসাথে, ধীরে ভলিউম ওঠানামা
    f = "220|261.63|329.63" if mood == "calm" else "196|246.94|293.66"
    expr = "+".join([f"0.12*sin(2*PI*{x}*t)*(0.6+0.4*sin(2*PI*0.07*t))" for x in f.split("|")])
    subprocess.run([FF, "-y", "-v", "error",
                    "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={dur:.2f}",
                    "-af", f"afade=t=in:d=2,afade=t=out:st={max(0, dur-3):.1f}:d=3,"
                           f"lowpass=f=1200,stereotools=mlev=0.9",
                    "-ac", "2", out], check=True)
    print("   🎵 BGM জেনারেট করা হলো (১০০% নিজের)")
    return out


def _has_audio(path: str) -> bool:
    try:
        err = subprocess.run([FF, "-hide_banner", "-i", path],
                             capture_output=True, text=True, timeout=30).stderr
        return "Audio:" in err
    except Exception:
        return False


def mix(video: str, bgm: str, out: str, bgm_vol: float = 0.18) -> str:
    """
    BGM মিক্স। স্টক ভিডিওতে অডিও থাকে না (-an) — তখন শুধু BGM-ই অডিও হিসেবে বসে;
    না হলে ডায়ালগ+BGM মিশ্রিত হয়। (আগে [0:a] না থাকায় ফিল্টার-গ্রাফ ব্যর্থ হতো।)
    """
    if _has_audio(video):
        fc = (f"[1:a]volume={bgm_vol}[b];"
              f"[0:a][b]amix=inputs=2:duration=first:normalize=0[a]")
        maps = ["-map", "0:v", "-map", "[a]"]
    else:
        fc = f"[1:a]volume={min(1.0, bgm_vol * 2)}[a]"
        maps = ["-map", "0:v", "-map", "[a]"]
    subprocess.run([FF, "-y", "-v", "error", "-i", video, "-i", bgm,
                    "-filter_complex", fc] + maps +
                   ["-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    "-shortest", out], check=True)
    return out


def build_free(query: str, dur: float, out: str, aspect: str = "square",
               cc0_only: bool = True) -> str:
    """
    ১০০% ফ্রি ফুটেজ: Pexels (কী থাকলে) → না পারলে Wikimedia Commons।
    দুটোই বাণিজ্যিক ব্যবহারে ফ্রি; CC BY ফাইল হলে অ্যাট্রিবিউশন লগে লেখা হয়।
    """
    try:
        return build(query, dur, out, aspect)
    except SystemExit as e:
        print(f"   ℹ️ Pexels ব্যবহার করা গেল না ({e}) → Wikimedia Commons চেষ্টা")
    except Exception as e:
        print(f"   ℹ️ Pexels ব্যর্থ ({str(e)[:80]}) → Wikimedia Commons চেষ্টা")

    items = search_commons(query, 12, cc0_only=cc0_only)
    if cc0_only and len(items) < 2:
        # CC0 কম থাকলে সাধারণ কীওয়ার্ডে আবার চেষ্টা, তবু শুধু CC0
        items = search_commons(" ".join(query.split()[:1]) or query, 12, cc0_only=True)
    if cc0_only and len(items) < 2:
        print("   ⚠️ CC0 ভিডিও যথেষ্ট নেই → CC BY ব্যবহার হচ্ছে (ক্রেডিট ফাইলে লেখা থাকবে)")
        items = search_commons(query, 12, cc0_only=False)
    if not items:
        raise SystemExit(f"'{query}' — Commons-এও কিছু পাওয়া যায়নি")
    if cc0_only:
        print(f"   🌿 শুধু CC0/Public Domain ফুটেজ ({len(items)}টি পাওয়া গেছে)")

    def _rank(c):
        lic = str(c.get("license", "")).lower()
        return 0 if ("cc0" in lic or "public domain" in lic) else 1
    random.shuffle(items)
    items.sort(key=_rank)          # CC0/PD আগে — অ্যাট্রিবিউশন-মুক্ত
    tmp = Path(tempfile.mkdtemp(prefix="commons_"))
    try:
        paths, credits = [], []
        for i, c in enumerate(items[:8]):
            dest = tmp / f"c{i:02d}.src"
            try:
                ok = False
                for attempt in range(3):
                    try:
                        time.sleep(1.2 + attempt * 1.5)     # Wikimedia থ্রটল
                        req = urllib.request.Request(c["url"], headers={"User-Agent": _UA})
                        with urllib.request.urlopen(req, timeout=120, context=_ssl()) as r:
                            with open(dest, "wb") as f:
                                shutil.copyfileobj(r, f, 1024 * 256)
                        ok = True
                        break
                    except urllib.error.HTTPError as he:
                        if he.code == 429:
                            print(f"   ⏳ 429 — {2 + attempt * 2}s অপেক্ষা")
                            time.sleep(2 + attempt * 2)
                            continue
                        raise
                if not ok or dest.stat().st_size < 100_000:
                    continue
                paths.append(dest)
                credits.append(f"{c['page']} — {c['license']} — {c['by']}")
                print(f"   ⬇️ {c['page'][:40]} · {c['license']}")
            except Exception as e:
                print(f"   ⚠️ {c['page'][:30]}: {str(e)[:60]}")
        if not paths:
            raise SystemExit("Commons থেকেও নামানো গেল না")

        # চাইলে সময় পূরণ না হলে ক্লিপ লুপ করি (আগে ২০s চাইলে ১২s আসত)
        def _dur(pth: Path) -> float:
            try:
                e = subprocess.run([FF, "-hide_banner", "-i", str(pth)],
                                   capture_output=True, text=True, timeout=30).stderr
                m = re.search(r"Duration: (\d+):(\d+):([0-9.]+)", e)
                return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0
            except Exception:
                return 0

        total = sum(_dur(x) for x in paths)
        seq = list(paths)
        while total < dur + 1 and seq:
            seq.extend(paths)
            total += sum(_dur(x) for x in paths)
            if len(seq) > 40:
                break
        lst = tmp / "list.txt"
        lines = []
        for pth in seq:
            lines.append(f"file '{pth}'")
        lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
        joined = tmp / "joined.mp4"
        subprocess.run([FF, "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", str(lst), "-t", f"{dur:.2f}",
                        "-vf", ("scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"
                                 if aspect in ("square", "portrait") else
                                 "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080")
                                 + ",setsar=1,fps=30",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                        "-pix_fmt", "yuv420p", "-an", str(joined)], check=True)
        shutil.copy2(joined, out)
        # ক্রেডিট ফাইল — CC BY/BY-SA হলে অ্যাট্রিবিউশন দরকার হয়, তাই পাশে রাখি
        try:
            cr = Path(str(out)).with_name(Path(str(out)).stem + "_CREDITS.txt")
            cr.write_text("ফুটেজের সূত্র (Wikimedia Commons):\n" + "\n".join(credits) +
                          "\n\nBGM: Openverse CC0 (যদি ব্যবহার হয়)\n",
                          encoding="utf-8")
        except Exception:
            pass
        print(f"   ✅ ফ্রি স্টক ভিডিও: {out} · {len(paths)} ক্লিপ")
        for c in credits:
            print(f"   📝 ক্রেডিট: {c[:110]}")
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--dur", type=float, default=30)
    ap.add_argument("--out", required=True)
    ap.add_argument("--aspect", default="square")
    a = ap.parse_args()
    build(a.query, a.dur, a.out, a.aspect)
    return 0


if __name__ == "__main__":
    sys.exit(main())

def _is_cc0(lic: str) -> bool:
    """CC0 / Public Domain কিনা — এগুলোতে অ্যাট্রিবিউশন লাগে না।"""
    l = str(lic).lower().replace("-", "").replace(" ", "")
    return ("cc0" in l) or ("publicdomain" in l) or l in ("pd", "pdm")


# ── কী ছাড়া ১০০% ফ্রি: Wikimedia Commons (CC) + Openverse (CC0 মিউজিক) ─────
def search_commons(query: str, limit: int = 12, cc0_only: bool = False) -> list[dict]:
    """
    Wikimedia Commons-এ ফ্রি ভিডিও খোঁজে — কোনো API কী লাগে না।

    cc0_only=True → শুধু **CC0/Public Domain** (ক্রেডিটও লাগে না, ১০০% শূন্য-দায়)।
    """
    term = f"filetype:video {query}"
    if cc0_only:
        term += ' incategory:"CC-Zero"'
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": term, "gsrnamespace": "6",
        "gsrlimit": str(limit), "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
    })
    url = f"https://commons.wikimedia.org/w/api.php?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "VideoVault/1.0 (https://github.com/MithuMia7223/youtube-ai; mithumia7223@gmail.com)"})
    with urllib.request.urlopen(req, timeout=30, context=_ssl()) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = []
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        for ii in page.get("imageinfo", []) or []:
            if not str(ii.get("mime", "")).startswith("video/"):
                continue
            meta = ii.get("extmetadata", {}) or {}
            lic = (meta.get("LicenseShortName", {}) or {}).get("value", "?")
            if cc0_only and not _is_cc0(lic):
                continue
            out.append({
                "url": ii.get("url"),
                "w": ii.get("width"), "h": ii.get("height"),
                "dur": ii.get("duration") or 0,
                "license": lic,
                "by": (meta.get("Artist", {}) or {}).get("value", "?")[:60],
                "page": page.get("title", ""),
            })
    return out


def fetch_cc0_music(query: str = "calm cinematic", seconds: float = 60) -> str | None:
    """Openverse থেকে **CC0** মিউজিক নামায় (কোনো কী লাগে না) → লোকাল ফাইল।"""
    try:
        q = urllib.parse.quote(query)
        url = f"https://api.openverse.org/v1/audio/?q={q}&license=cc0&page_size=8"
        req = urllib.request.Request(url, headers={"User-Agent": "VideoVault/1.0 (https://github.com/MithuMia7223/youtube-ai; mithumia7223@gmail.com)"})
        with urllib.request.urlopen(req, timeout=30, context=_ssl()) as r:
            data = json.loads(r.read().decode("utf-8"))
        items = [a for a in (data.get("results") or [])
                 if a.get("url") and a.get("duration") and a["duration"] > 20]
        if not items:
            return None
        random.shuffle(items)
        cache = AUDIO / "cc0"
        cache.mkdir(parents=True, exist_ok=True)
        for a in items[:4]:
            ext = ".mp3" if ".mp3" in a["url"] else ".ogg"
            dest = cache / f"ov_{abs(hash(a['url'])) % 10**8}{ext}"
            if not dest.exists():
                try:
                    req2 = urllib.request.Request(a["url"], headers={"User-Agent": "VideoVault/1.0 (https://github.com/MithuMia7223/youtube-ai; mithumia7223@gmail.com)"})
                    with urllib.request.urlopen(req2, timeout=60, context=_ssl()) as r2:
                        f = open(dest, "wb")
                        shutil.copyfileobj(r2, f, 1024 * 128)
                        f.close()
                except Exception:
                    continue
            if dest.exists() and dest.stat().st_size > 100_000:
                print(f"   🎵 CC0 মিউজিক: {(a.get('title') or '?')[:40]} [{a.get('license')}]")
                return str(dest)
    except Exception as e:
        print(f"   ⚠️ Openverse ব্যর্থ: {e}")
    return None
