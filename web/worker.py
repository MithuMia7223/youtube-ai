#!/usr/bin/env python3
"""
⚙️ ওয়েবসাইটের কাজের ইঞ্জিন — একটা ভিডিও লিংক নিয়ে পুরো পাইপলাইন চালায়
=====================================================================

    python web/worker.py <url> <mode> <start> <duration> <outdir> <name>

  url      : YouTube লিংক (অথবা টেস্টের জন্য লোকাল ফাইল-পাথ)
  mode     : square (১:১ ১০৮০) | long (১৯২০×১০৮০)
  start    : শুরুর সময় (MM:SS বা সেকেন্ড)
  duration : কত সেকেন্ড নেবে
  outdir   : কোথায় রাখবে (ডিফল্ট deliver/)
  name     : আউটপুট ফাইলের নাম (এক্সটেনশন ছাড়া)

কাজ: ডাউনলোড → বার-মুক্ত ক্রপ → ১:১/১৬:৯ ১০৮০ → deliver/-এ রাখা।
প্রতি ধাপের অগ্রগতি stdout-এ লেখে (সাইট সেটা লগ হিসেবে দেখায়)।
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# launchd থেকে চালালে PATH ছোট থাকে — ffmpeg/yt-dlp যাতে পাওয়া যায়
for _p in (os.path.expanduser("~/.local/bin"), "/opt/homebrew/bin", "/usr/local/bin"):
    if _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + ":" + os.environ.get("PATH", "")


def _ff() -> str:
    """ffmpeg-এর পাথ (launchd-এর PATH ছোট হলে ~/.local/bin-ও দেখি)।"""
    for c in (shutil.which("ffmpeg"), os.path.expanduser("~/.local/bin/ffmpeg"),
              "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if c and os.path.exists(c):
            return c
    return "ffmpeg"


def log(*a):
    print(*a, flush=True)


def parse_time(v: str) -> str:
    v = (v or "0").strip()
    if ":" in v:
        return v
    try:
        sec = int(float(v))
    except ValueError:
        return "0"
    return f"{sec // 60}:{sec % 60:02d}"


def _download_full(url: str, out: str) -> None:
    """
    পুরো ভিডিও নামায় (≤১০৮০)। YouTube-এর ক্লায়েন্ট নিয়ম বদলায় —
    android/web_safari সহ কয়েকটা স্ট্র্যাটেজি চেষ্টা করি (বটের মতোই)।
    Facebook/Instagram/TikTok লিংকেও একই কমান্ড চলে (yt-dlp জেনেরিক)।
    """
    import youtube_processor as yp
    yp.set_ffmpeg_path()
    base = [yp.get_ytdlp_path()] + list(yp.get_ytdlp_js_args())
    cookies = ["--cookies", "cookies.txt"] if Path("cookies.txt").exists() else []
    strategies = [
        [],
        ["--extractor-args", "youtube:player_client=android"],
        ["--extractor-args", "youtube:player_client=web_safari"],
        ["--extractor-args", "youtube:player_client=ios"],
        ["--extractor-args", "youtube:player_client=tv_embedded"],
        ["--extractor-args", "youtube:player_client=mweb"],
    ]
    err = ""
    for extra in strategies:
        cmd = base + cookies + extra + [
            # AV1 ডিকোড ৬ գծով ধীর (১০ মিনিট = ৬ মিনিট!) তাই h264 আগে চাই
            "-f", "bv*[height<=1080][vcodec^=avc1]+ba/bv*[height<=1080][vcodec^=vp9]+ba/"
                  "bv*[height<=1080]+ba/b[height<=1080]/b",
            "--merge-output-format", "mp4", "--socket-timeout", "30",
            "--concurrent-fragments", "4", "--no-progress", "-o", out, url]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and Path(out).exists():
            log(f"      ⬇️ স্ট্র্যাটেজি: {extra[1].split('=')[-1] if extra else 'default'}")
            return
        err = (r.stderr or "").strip().splitlines()[-1:] or [""]
        log(f"      ⚠️ {extra[1].split('=')[-1] if extra else 'default'}: {str(err[0])[:70]}")
    raise RuntimeError("ডাউনলোড ব্যর্থ — সব স্ট্র্যাটেজি খারাপ")


def _auto_highlights(src: Path, out: Path, clip_len: float = 8.0,
                     top: int = 0, dur_hint: float = 0.0,
                     keep_audio: bool = False) -> None:
    """
    অটো কাটিং: মূল অংশ খুঁজে বের করে শুধু সেগুলো একসাথে জোড়া দেয়।
    `top=0` হলে মোট দৈর্ঘ্য `dur_hint`-এর সমান ক্লিপ নেওয়া হয়।
    """
    import highlights as hl
    total = hl.duration(str(src))
    n = top or max(3, round(dur_hint / clip_len)) if dur_hint else (top or 6)
    log(f"      🔎 বিশ্লেষণ: {total/60:.1f} মিনিট · {n}টা ক্লিপ × {clip_len:.0f}s")
    segs = hl.detect(str(src), clip_len=clip_len, top=n, total=dur_hint or None)
    if not segs:
        raise SystemExit("হাইলাইট পাওয়া যায়নি")
    chosen = ", ".join(f"{s['start']:.0f}s" for s in segs)
    log(f"      🎯 বাছাই ({len(segs)}): {chosen} — {sum(s['dur'] for s in segs):.0f}s")
    hl.cut(str(src), segs, str(out), mute_original=not keep_audio)


def main() -> int:
    if len(sys.argv) < 7:
        log("ব্যবহার: worker.py <url> <mode> <start> <duration> <outdir> <name>")
        return 2
    url, mode, start, dur, outdir, name = sys.argv[1:7]
    # ঐচ্ছিক: --bgm  --meta (AI টাইটেল/SEO)  --thumb (থাম্বনেইল)
    flags = set(sys.argv[7:])
    want_bgm = "--bgm" in flags
    # --free  → ফুটেজ Pexels/Commons (১০০% ফ্রি), BGM CC0/জেনারেটেড
    want_free = "--free" in flags
    want_remake = "--remake" in flags      # লিংকের টপিক → ফ্রি ফুটেজ (মূল ক্লিপ নয়)

    # (সুরক্ষা নিচে — _q তৈরি হওয়ার পরে)
    _q = [f for f in flags if f.startswith("--q=")]
    # সুরক্ষা: ফ্রি-মোডে কেউ লিংক দিলে সেটাকে কীওয়ার্ড ভেবে খুঁজতে যেত (আটকে যেত)।
    # লিংক + ফ্রি = অটো-রিমেক (লিংকের বিষয় পড়ে ফ্রি ফুটেজ)।
    if want_free and url.startswith("http"):
        want_remake = True
        _q.clear()
    free_query = (_q[0][4:] if _q else "nature cinematic")
    # ডিফল্ট: শুধু CC0/Public Domain — ক্রেডিটও লাগে না, ১০০% শূন্য-দায়
    cc0_only = "--any-license" not in flags
    want_auto = "--auto" in flags        # পুরো ভিডিও → হাইলাইট কেটে নেওয়া
    want_meta = "--meta" in flags
    want_thumb = "--thumb" in flags
    is_short = mode != "long"
    outdir_p = Path(outdir)
    outdir_p.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    raw = outdir_p / f"{name}_raw.mp4"
    final = outdir_p / f"{name}.mp4"

    import youtube_processor as yp

    # ── ১) ভিডিও আনা ────────────────────────────────────────────────────
    if want_remake and url.startswith("http"):
        # ১) লিংক থেকে শুধু শিরোনাম/বিষয় নিই — ভিডিও ডাউনলোড করি না
        log("[1/4] লিংকের বিষয় পড়া হচ্ছে (ভিডিও নামানো হবে না) …")
        title, tags = "", ""
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True,
                                   "no_warnings": True, "extract_flat": False}) as y:
                info = y.extract_info(url, download=False) or {}
            title = (info.get("title") or "").strip()
            tags = ", ".join((info.get("tags") or [])[:8])
            log(f"      📖 বিষয়: {title[:70]}")
        except Exception as e:
            log(f"      ⚠️ শিরোনাম পড়া যায়নি: {str(e)[:60]}")

        # ২) Gemini দিয়ে ইংরেজি স্টক-কীওয়ার্ড (ছবি খোঁজার জন্য)
        query = ""
        try:
            from gemini_helper import generate_script  # noqa: F401
        except Exception:
            pass
        try:
            from google import genai as _genai
            _c = _genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
            _prompt = ("Give 6-10 ENGLISH stock-footage search keywords (comma separated, "
                       f"no explanation) for a video about: {title}. {tags}")
            r, last_err = None, None
            for _m in ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3-flash-preview"):
                try:
                    r = _c.models.generate_content(model=_m, contents=_prompt)
                    if (getattr(r, "text", "") or "").strip():
                        break
                except Exception as _e:
                    last_err = _e
            if r is None:
                raise last_err or RuntimeError("Gemini উত্তর দেয়নি")
            cand = (getattr(r, "text", "") or "").strip().replace(chr(10), " ")
            cand = " ".join(w.strip(" .,;\"'") for w in cand.split(",")[:6])
            if cand and all(ord(c) < 128 for c in cand):
                query = cand
            log(f"      🔑 কীওয়ার্ড: {query[:80]}")
        except Exception as e:
            log(f"      ⚠️ Gemini ব্যর্থ ({str(e)[:50]}) → শিরোনাম ব্যবহার")

        if not query:
            import re as _re
            query = " ".join(_re.findall(r"[A-Za-z]{3,}", title)[:6]) or "cinematic nature"
            log(f"      🔑 ফলব্যাক কীওয়ার্ড: {query}")

        free_query = query
        want_free = True
        log("[2/4] কপিরাইট-ফ্রি ফুটেজ খোঁজা হচ্ছে …")

    if want_free:
        if not want_remake:
            log(f"[1/3] কপিরাইট-ফ্রি ফুটেজ খোঁজা হচ্ছে: '{free_query}' …")
        sys.path.insert(0, str(ROOT / "web"))
        import stock as _stock
        _stock.build_free(free_query, float(dur), str(raw), mode, cc0_only=cc0_only)
        if not raw.exists():
            log("❌ ফ্রি ফুটেজ তৈরি হয়নি")
            return 3
        log(f"      ✅ {(raw.stat().st_size / 1048576):.1f} MB ফ্রি ফুটেজ ({time.time() - t0:.0f}s)")
    elif url.startswith(("/", "file://")):
        src = url.replace("file://", "")
        log(f"[1/3] লোকাল ফাইল ব্যবহার: {src}")
        shutil.copy2(src, raw)
        # ── ম্যানুয়াল কাট: start/dur দেওয়া থাকলে ঠিক ওই অংশটুকু নিই ──
        try:
            _d = float(dur or 0)
        except ValueError:
            _d = 0.0
        if _d > 0:
            _ss = parse_time(start).replace(":", ".")
            _cut = outdir_p / f"{name}_cut.mp4"
            log(f"      ✂️ ম্যানুয়াল কাট: {start} থেকে {_d:.1f}s")
            subprocess.run([_ff(), "-y", "-v", "error", "-ss", str(_ss), "-t", f"{_d:.2f}",
                            "-i", str(raw), "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac",
                            "-b:a", "160k", "-avoid_negative_ts", "make_zero", str(_cut)],
                           check=True)
            raw.unlink(missing_ok=True)
            raw = _cut
    elif want_auto:
        full = outdir_p / f"{name}_full.mp4"
        log(f"[1/3] পুরো ভিডিও নামানো হচ্ছে (হাইলাইট বিশ্লেষণের জন্য) — {url[:70]}")
        _download_full(url, str(full))
        if not full.exists() or full.stat().st_size < 10_000:
            log("❌ ডাউনলোড ব্যর্থ")
            return 3
        log(f"      ✅ {(full.stat().st_size / 1048576):.1f} MB ({time.time() - t0:.0f}s)")
        try:
            _e = subprocess.run([_ff(), "-hide_banner", "-i", str(full)],
                                capture_output=True, text=True, timeout=60).stderr
            _m = re.search(r"Video:.*?, (\d+)x(\d+)", _e)
            if _m:
                w, h = int(_m.group(1)), int(_m.group(2))
                log(f"      📺 সোর্স: {w}×{h}")
                if min(w, h) < 720:
                    log("      ⚠️ সোর্স কম রেজোলিউশন — YouTube ১০৮০-র জন্য cookies.txt দরকার")
        except Exception:
            pass
        _auto_highlights(full, raw, clip_len=8.0, dur_hint=float(dur or 0),
                         keep_audio="--keep-audio" in flags)
        log(f"      ✅ হাইলাইট: {raw.stat().st_size / 1048576:.1f} MB ({time.time() - t0:.0f}s)")
        try:
            full.unlink()          # পুরো ফাইল আর দরকার নেই — ডিস্ক বাঁচাই
        except Exception:
            pass
    else:
        log(f"[1/3] ডাউনলোড হচ্ছে — {dur}s @ {start} …")
        yp.download_youtube_clip(url, parse_time(start), float(dur), str(raw))
    if not raw.exists() or raw.stat().st_size < 10_000:
        log("❌ ডাউনলোড ব্যর্থ — ফাইল তৈরি হয়নি")
        return 3
    log(f"      ✅ ডাউনলোড {(raw.stat().st_size / 1048576):.1f} MB ({time.time() - t0:.0f}s)")

    # ── ২) প্রসেসিং (বার-মুক্ত, ১০৮০) ───────────────────────────────────
    log(f"[2/3] প্রসেসিং — {mode} (বার-মুক্ত ১০৮০) …")
    yp.process_clip_copyright_bypass(str(raw), str(final), is_short=is_short,
                                     bgm_dir=str(ROOT / "assets" / "audio"), mix_bgm=False)

    # ── BGM (বটের মতো) ──────────────────────────────────────────────────
    if want_bgm and want_free:
        try:
            log("[2b] CC0 BGM খোঁজা হচ্ছে …")
            sys.path.insert(0, str(ROOT / "web"))
            import stock as _stock
            track = _stock.fetch_cc0_music("calm cinematic piano music", float(dur)) or \
                    _stock.make_bgm(float(dur), str(outdir_p / f"{name}_bgm.wav"))
            bgm_out = outdir_p / f"{name}_bgm.mp4"
            _stock.mix(str(final), str(track), str(bgm_out), bgm_vol=0.22)
            if bgm_out.exists():
                bgm_out.replace(final)
                log(f"      ✅ CC0 BGM মিক্স হয়েছে ({os.path.basename(str(track))})")
        except Exception as e:
            log(f"      ⚠️ CC0 BGM ব্যর্থ (উপেক্ষা): {e}")
    elif want_bgm:
        bgm_out = outdir_p / f"{name}_bgm.mp4"
        ok = False
        try:
            log("[2b] BGM মিক্স করা হচ্ছে …")
            yp.mix_bgm_on_merged_video(str(final), str(bgm_out),
                                       bgm_dir=str(ROOT / "assets" / "audio"))
            if bgm_out.exists() and bgm_out.stat().st_size > 10_000:
                bgm_out.replace(final)
                ok = True
                log("      ✅ BGM যোগ হয়েছে")
        except Exception as e:
            log(f"      ⚠️ মূল BGM মিক্স ব্যর্থ: {str(e)[:90]}")
        if not ok:
            # অটো-হাইলাইটে আসল অডিও কাটা থাকে → [0:a] নেই, তাই প্রথম পথ ব্যর্থ।
            # stock.mix অডিওহীন ভিডিও সামলায় → CC0 BGM সরাসরি বসাই।
            try:
                log("      ℹ️ বিকল্প পথ: CC0 BGM সরাসরি বসানো হচ্ছে")
                sys.path.insert(0, str(ROOT / "web"))
                import stock as _stock
                from pathlib import Path as _P
                try:
                    _v = float(dur or 0)
                except ValueError:
                    _v = 0.0
                if _v <= 0:
                    import highlights as _hl
                    _v = _hl.duration(str(final))
                # আগে প্রজেক্টের নিজের BGM গানগুলো (বট যেগুলো ব্যবহার করে)
                import random as _rnd
                _songs = sorted(p for p in (ROOT / "assets" / "audio").glob("bgm*.mp3")
                                if "outro" not in p.name)
                if _songs:
                    track = str(_rnd.choice(_songs))
                    log(f"      🎵 নিজের BGM: {Path(track).name}")
                else:
                    track = _stock.fetch_cc0_music("calm cinematic piano music", _v) or \
                            _stock.make_bgm(_v, str(outdir_p / f"{name}_bgm.wav"))
                _stock.mix(str(final), str(track), str(bgm_out), bgm_vol=0.35)
                bgm_out.replace(final)
                ok = True
                log(f"      ✅ CC0 BGM যোগ হয়েছে ({_P(str(track)).name})")
            except Exception as e:
                log(f"      ⚠️ BGM সম্পূর্ণ ব্যর্থ (উপেক্ষা): {str(e)[:90]}")
    if not final.exists():
        log("❌ প্রসেসিং ব্যর্থ")
        return 4
    w, h = yp.probe_size(str(final))
    log(f"      ✅ প্রসেস হয়েছে: {w}×{h} · {(final.stat().st_size / 1048576):.1f} MB")

    # ── ৩) deliver/-এ রাখি (ওয়েবসাইট এখান থেকেই দেখায়) ─────────────────
    deliver = ROOT / "deliver"
    deliver.mkdir(exist_ok=True)
    if final.resolve().parent != deliver.resolve():
        shutil.copy2(final, deliver / final.name)
    try:
        raw.unlink()
    except OSError:
        pass
    # ── AI টাইটেল/SEO + থাম্বনেইল (বটের মতো) ────────────────────────────
    title = ""
    if want_meta:          # শুধু চাইলে Gemini ডাকা হবে (নইলে অকারণ অপেক্ষা)
        try:
            log("[2c] AI টাইটেল/SEO তৈরি হচ্ছে …")
            # উৎসের আসল টাইটেল পেলে সেটাই বিষয় হিসেবে দিই (নইলে জেনেরিক)
            subject = ""
            if not url.startswith(("/", "file://")):
                try:
                    # get_video_duration ফাংশনটা yt-dlp থেকে টাইটেলও পড়ে
                    r = yp.get_video_duration(url)
                    subject = (r.get("title") if isinstance(r, dict) else "") or ""
                except Exception:
                    subject = ""
            from gemini_helper import generate_seo_meta
            meta = {}
            for attempt in (1, 2):          # Gemini মাঝে মাঝে 503 দেয় — দুইবার চেষ্টা
                try:
                    meta = generate_seo_meta(subject or f"Bengali movie drama clip, {dur} seconds") or {}
                    if (meta or {}).get("title"):
                        break
                except Exception as ge:
                    log(f"      ⚠️ Gemini চেষ্টা {attempt} ব্যর্থ: {str(ge)[:80]}")
                    time.sleep(3)
            title = (meta or {}).get("title", "") or ""
            desc = (meta or {}).get("description", "") or ""
            tags = (meta or {}).get("tags", []) or []
            if title:
                log(f"TITLE {title}")
                log(f"DESC {desc[:400]}")
                log(f"TAGS {', '.join(tags) if isinstance(tags, list) else tags}")
        except Exception as e:
            log(f"      ⚠️ টাইটেল/SEO ব্যর্থ (উপেক্ষা): {e}")

    if want_thumb:
        try:
            log("[2d] থাম্বনেইল তৈরি হচ্ছে …")
            from thumbnail_creator import create_thumbnail
            tpath = outdir_p / f"{name}_thumb.jpg"
            create_thumbnail(title=title or name, topic="AI CLIP",
                             output_path=str(tpath), video_path=str(final),
                             is_short=is_short)
            if tpath.exists():
                log(f"THUMB {tpath.name}")
        except Exception as e:
            log(f"      ⚠️ থাম্বনেইল ব্যর্থ (উপেক্ষা): {e}")

    log(f"[3/3] ✅ তৈরি: deliver/{final.name} · মোট {time.time() - t0:.0f}s")
    log(f"DONE {final.name} {w} {h}")

    # কাজ শেষ → মাঝপথের ভারী ফাইল মুছি (ডিস্ক ভরে যাচ্ছিল: deliver-এ ৩৫MB জঞ্জাল)
    try:
        kept = 0
        for pat in (f"{name}_raw*.mp4", f"{name}_raw*.part", f"{name}_raw*.webm",
                    f"{name}_bgm*", f"{name}_noaudio*", f"{name}_tmp*"):
            for f in outdir_p.glob(pat):
                if f.is_file() and f.name != final.name:
                    try:
                        f.unlink()
                        kept += 1
                    except Exception:
                        pass
        if kept:
            log(f"      🧹 {kept}টা অস্থায়ী ফাইল মুছে ফেলা হলো")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(5)
