import os
import subprocess
import tempfile
import random
import math
import re
import imageio_ffmpeg
import numpy as np
from moviepy import VideoFileClip, AudioFileClip, CompositeAudioClip, concatenate_audioclips
from dotenv import load_dotenv

load_dotenv()

def set_ffmpeg_path():
    """Dynamically add imageio_ffmpeg's precompiled ffmpeg binary folder and virtualenv bin to PATH."""
    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_dir = os.path.dirname(ffmpeg_exe)
        
        # Ensure a file/symlink literally named "ffmpeg" exists in the binaries folder
        # (yt-dlp looks specifically for "ffmpeg" in PATH, not "ffmpeg-macos-aarch64-v7.1")
        target_name = "ffmpeg"
        if os.name == "nt":
            target_name = "ffmpeg.exe"
            
        bin_ffmpeg = os.path.join(ffmpeg_dir, target_name)
        if not os.path.exists(bin_ffmpeg):
            try:
                os.symlink(os.path.basename(ffmpeg_exe), bin_ffmpeg)
            except Exception:
                try:
                    import shutil
                    shutil.copy2(ffmpeg_exe, bin_ffmpeg)
                except Exception as sym_err:
                    print(f"[Warning] Failed to link/copy ffmpeg: {sym_err}")

        if ffmpeg_dir not in os.environ["PATH"]:
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ["PATH"]
        
        # Add actual project venv bin directory to PATH explicitly
        project_dir = os.path.dirname(os.path.abspath(__file__))
        venv_bin = os.path.join(project_dir, ".venv", "bin")
        if os.path.isdir(venv_bin) and venv_bin not in os.environ["PATH"]:
            os.environ["PATH"] = venv_bin + os.pathsep + os.environ["PATH"]
            
        import sys
        sys_venv_bin = os.path.dirname(sys.executable)
        if sys_venv_bin not in os.environ["PATH"]:
            os.environ["PATH"] = sys_venv_bin + os.pathsep + os.environ["PATH"]
    except Exception as e:
        print(f"[Warning] Failed to set imageio ffmpeg path: {e}")

_encoder_cache = None

def get_best_encoder():
    """Determine the best available video encoder (hardware accelerated if possible)."""
    global _encoder_cache
    if _encoder_cache is not None:
        return _encoder_cache
        
    set_ffmpeg_path()
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        res = subprocess.run([ffmpeg_exe, "-encoders"], capture_output=True, text=True, check=True)
        if "h264_videotoolbox" in res.stdout:
            # বিটরেট-মোড: q:v 50 → ২.৭ Mbps (ব্লারি), ৭৫ → ২০ Mbps (অতিরিক্ত বড়)
            # ১০৮০-এর জন্য ৮ Mbps টার্গেট — YouTube-এর সুপারিশকৃত মান,
            # q:v 50 (৫ Mbps) নরম দেখাত, q:v 75 (২০ Mbps) ফাইল বিশাল করত
            _encoder_cache = ("h264_videotoolbox", ["-b:v", "8M", "-maxrate", "12M",
                                                   "-bufsize", "16M", "-allow_sw", "1"])
            print("[INFO] Hardware acceleration enabled: Using h264_videotoolbox")
        else:
            _encoder_cache = ("libx264", ["-preset", "veryfast", "-crf", "18"])
            print("[INFO] Hardware acceleration not found: Using libx264")
    except Exception as e:
        print(f"[Warning] Failed to check encoders: {e}. Defaulting to libx264.")
        _encoder_cache = ("libx264", ["-preset", "veryfast", "-crf", "18"])
        
    return _encoder_cache

def get_ytdlp_path():
    """Get the path to yt-dlp, looking in the venv first, then PATH."""
    import sys
    import shutil
    # Add deno to PATH if available (yt-dlp uses it as JS runtime for YouTube)
    deno_path = os.path.expanduser("~/.deno/bin")
    if os.path.isdir(deno_path) and deno_path not in os.environ.get("PATH", ""):
        os.environ["PATH"] = deno_path + os.pathsep + os.environ.get("PATH", "")
    # Check if yt-dlp exists in the virtualenv bin directory
    venv_bin_dir = os.path.dirname(sys.executable)
    venv_ytdlp = os.path.join(venv_bin_dir, "yt-dlp")
    if os.path.exists(venv_ytdlp):
        return venv_ytdlp
    # Check PATH
    path_ytdlp = shutil.which("yt-dlp")
    if path_ytdlp:
        return path_ytdlp
    return "yt-dlp"

def get_ytdlp_js_args():
    deno_exe = os.path.expanduser("~/.deno/bin/deno")
    if os.path.exists(deno_exe):
        return ["--js-runtimes", f"deno:{deno_exe}"]
    return ["--js-runtimes", "deno"]

def shape_bengali(text: str) -> str:
    """
    Decompose combined Bengali vowels (ো, ৌ) and reorder pre-vowels (ি, ে, ৈ)
    to the left of their consonant/conjunct clusters for standard FreeType rendering.
    """
    text = text.replace("\u09CB", "\u09C7\u09BE")  # ো -> ে + া
    text = text.replace("\u09CC", "\u09C7\u09D7")  # ৌ -> ে + ৗ
    
    chars = list(text)
    pre_vowels = {"\u09BF", "\u09C7", "\u09C8"} # ি, ে, ৈ
    
    i = 0
    while i < len(chars):
        if chars[i] in pre_vowels:
            val = chars.pop(i)
            j = i - 1
            while j > 0:
                if chars[j - 1] == "\u09CD":
                    j -= 2
                else:
                    break
            chars.insert(max(0, j), val)
        else:
            i += 1
    return "".join(chars)


def get_best_font_path(font_type="bangla"):
    """
    Find a valid font file path dynamically based on OS to prevent FFmpeg crashes.
    """
    import os
    if font_type == "bangla":
        candidates = [
            # macOS paths
            "/System/Library/Fonts/Supplemental/Bangla Sangam MN.ttc",
            "/System/Library/Fonts/Supplemental/Bangla MN.ttc",
            "/System/Library/Fonts/KohinoorBangla.ttc",
            # Linux paths
            "/usr/share/fonts/truetype/lohit-bengali/Lohit-Bengali.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/opentype/malayalam/SolaimanLipi.ttf",
            "/usr/share/fonts/SolaimanLipi.ttf",
            # Windows paths
            "C:\\Windows\\Fonts\\vrinda.ttf",
            "C:\\Windows\\Fonts\\shonar.ttf"
        ]
    else: # english / default / helvetica
        candidates = [
            # macOS paths
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Verdana.ttf",
            # Linux paths
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            # Windows paths
            "C:\\Windows\\Fonts\\arial.ttf"
        ]
        
    for p in candidates:
        if os.path.exists(p):
            return p
            
    # Absolute fallbacks (if nothing found, hope FFmpeg can resolve by name or just return the first Mac path)
    return candidates[0]

def parse_time(time_str):
    """Parse time string formats (HH:MM:SS, MM:SS, or seconds) into float seconds."""
    time_str = str(time_str).strip()
    if not time_str:
        return 0
    try:
        if ":" in time_str:
            parts = list(map(float, time_str.split(":")))
            if len(parts) == 1:
                return parts[0]
            elif len(parts) == 2:
                # MM:SS
                return parts[0] * 60 + parts[1]
            elif len(parts) == 3:
                # HH:MM:SS
                return parts[0] * 3600 + parts[1] * 60 + parts[2]
        return float(time_str)
    except Exception:
        return 0

def format_seconds(seconds):
    """Format seconds into HH:MM:SS string."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def extract_video_id(url):
    """Extract standard 11-character YouTube video ID from a URL."""
    pattern = r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    if "v=" in url:
        return url.split("v=")[1].split("&")[0]
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    return None

def get_video_transcript(video_id):
    """Fetch video transcript from YouTube in Bengali or English."""
    from youtube_transcript_api import YouTubeTranscriptApi
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.fetch(video_id, languages=['bn', 'en'])
        transcript_text = ""
        for item in transcript_list:
            start = item.start
            text = item.text
            m, s = divmod(int(start), 60)
            h, m = divmod(m, 60)
            time_str = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
            transcript_text += f"[{time_str}] {text}\n"
        return transcript_text
    except Exception as e:
        print(f"Standard transcript API failed: {e}. Trying yt-dlp subtitle download...")
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            import tempfile
            import subprocess
            import re
            
            with tempfile.TemporaryDirectory() as temp_dir:
                vtt_base = os.path.join(temp_dir, f"sub_{video_id}")
                langs = ["bn", "en"]
                vtt_path = None
                
                for lang in langs:
                    cookie_opts = [["--cookies", "cookies.txt"]] if os.path.exists("cookies.txt") else []
                    cookie_opts.append([])
                    
                    found_lang = False
                    for opt in cookie_opts:
                        cmd = [
                            get_ytdlp_path(),
                        ] + get_ytdlp_js_args() + [
                            "--write-subs",
                            "--write-auto-subs",
                            "--sub-lang", lang,
                            "--skip-download",
                            "-o", vtt_base,
                        ]
                        cmd.extend(opt)
                        cmd.append(url)
                        
                        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        
                        expected_path = f"{vtt_base}.{lang}.vtt"
                        if os.path.exists(expected_path):
                            vtt_path = expected_path
                            found_lang = True
                            break
                    if found_lang:
                        break
                
                if vtt_path and os.path.exists(vtt_path):
                    with open(vtt_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    lines = content.split("\n")
                    transcript_text = ""
                    seen_texts = set()
                    time_pattern = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s+-->")
                    current_time_str = ""
                    
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        match = time_pattern.match(line)
                        if match:
                            h, m, s, _ = match.groups()
                            current_time_str = f"{h}:{m}:{s}" if int(h) > 0 else f"{m}:{s}"
                            continue
                        if line == "WEBVTT" or line.startswith("Kind:") or line.startswith("Language:"):
                            continue
                        cleaned = re.sub(r"<[^>]+>", "", line)
                        cleaned = cleaned.replace("&gt;&gt;", "").replace("&lt;", "<").replace("&gt;", ">").strip()
                        if not cleaned:
                            continue
                        normalized = re.sub(r"\s+", "", cleaned)
                        if normalized in seen_texts:
                            continue
                        seen_texts.add(normalized)
                        if current_time_str:
                            transcript_text += f"[{current_time_str}] {cleaned}\n"
                    
                    if transcript_text:
                        print(f"Successfully retrieved transcript using yt-dlp fallback for {video_id}!")
                        return transcript_text
        except Exception as fallback_err:
            print(f"yt-dlp transcript fallback failed: {fallback_err}")
        return ""

def clean_overlapping_segments(segments):
    """Sort and adjust segments to ensure there are no overlapping timeframes."""
    parsed_segs = []
    for seg in segments:
        start_str = seg.get("start_time", "0")
        dur = int(seg.get("duration", 0))
        try:
            start_sec = parse_time(start_str)
        except Exception:
            start_sec = 0
        parsed_segs.append({
            "start_sec": start_sec,
            "duration": dur,
            "original": seg
        })
    
    # Sort by starting seconds
    parsed_segs.sort(key=lambda x: x["start_sec"])
    
    unique_segs = []
    for ps in parsed_segs:
        if not unique_segs:
            unique_segs.append(ps)
            continue
        
        last = unique_segs[-1]
        last_end = last["start_sec"] + last["duration"]
        
        # If this segment starts before the last segment ends, they overlap!
        if ps["start_sec"] < last_end:
            overlap = last_end - ps["start_sec"]
            if overlap >= ps["duration"]:
                # Completely covered by the previous segment, skip this one
                continue
            else:
                # Adjust start time and reduce duration to remove the overlap
                new_start = last_end
                new_dur = ps["duration"] - overlap
                ps["start_sec"] = new_start
                ps["duration"] = new_dur
                
                # Format back to MM:SS or HH:MM:SS
                m, s = divmod(new_start, 60)
                h, m = divmod(m, 60)
                time_str = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
                ps["original"]["start_time"] = time_str
                ps["original"]["duration"] = new_dur
                unique_segs.append(ps)
        else:
            unique_segs.append(ps)
            
    return [x["original"] for x in unique_segs]

def find_best_segments_with_gemini(transcript_text, video_duration, is_short):
    """
    Analyze the transcript with Google Gemini to find a list of the most engaging highlight segments
    and a specific 20-30s teaser hook.
    For Shorts: returns exactly 1 segment of 30-60 seconds, teaser is ignored.
    For Long: returns a list of 5 to 7 separate high-engagement segments, and a 20-30s teaser hook.
    The total duration of the segments is dynamically chosen between 12 and 14 minutes.
    """
    from gemini_helper import client, DEFAULT_MODEL
    from google.genai import types
    import json
    
    if not client or not transcript_text:
        return None
        
    if is_short:
        prompt = f"""
        You are a professional YouTube growth hacker and video editor specializing in viral Bangla Natok (drama) Shorts, TikToks, and Reels.
        Below is the transcript of a drama video (with timestamps).
        
        Your goal is to identify a single highly viral, intense, EMOTIONAL highlight scene (sad, crying, tragic, or heart-touching moment) that tells a mini-story or has a massive emotional payoff.
        
        Requirements:
        1. Find a segment of 30 to 58 seconds.
        2. The start of the segment MUST be a strong "hook" (an emotional crying moment, a sad realization, a dramatic confession, or an intense heartbreak) that immediately grabs attention within the first 2 seconds.
        3. The segment should end on a dramatic emotional cliffhanger or a satisfying emotional resolution.
        4. Do not include silent intros, comedy, or slow setups.
        
        Transcript:
        {transcript_text}
        """
    else:
        prompt = f"""
        You are an expert YouTube drama compilation editor. Your task is to create a 12 to 15 minute highlight compilation from the drama transcript below.
        
        CRITICAL RULES:
        - All segments MUST be intense, emotional, sad, tragic, or crying scenes (high-emotion drama moments).
        - Avoid comedy, funny encounters, or generic talking scenes. Focus strictly on the emotional peak highlights of the drama.

        STRICT REQUIREMENTS — You MUST follow all of these:
        1. YOU MUST SELECT A MINIMUM OF 8 segments and a MAXIMUM OF 12 segments. Do NOT return fewer than 8 segments under any circumstances.
        2. Each segment duration MUST be between 60 and 120 seconds (1 to 2 minutes each). Do NOT pick segments shorter than 60 seconds.
        3. The TOTAL combined duration of ALL segments MUST be between 720 and 900 seconds (12 to 15 minutes). Count the seconds carefully.
        4. Spread the segments evenly: pick emotional scenes from the beginning (first 25%), middle (25%-75%), and end (last 25%) of the drama. Do NOT cluster all segments in one area.
        5. CRITICAL: No two segments may overlap in time. Each scene must have a completely different start time.
        6. The VERY LAST segment in your list MUST be the final resolution or emotional ending scene of the drama so the compilation has a clear ending.
        7. For the teaser hook: pick the single most explosive, heart-wrenching, or crying 20-30 second moment from ANY part of the video. The teaser MUST have a different start_time from all main segments.
        8. If the source video is shorter than 15 minutes, still pick 8 segments by reducing each segment duration proportionally, but never below 40 seconds each.

        REMINDER: Return EXACTLY 8 to 12 segments. Each segment between 60-120 seconds. Total = 12-15 minutes.

        Transcript:
        {transcript_text}
        """
        
    import time
    for attempt in range(3):
        try:
            from pydantic import BaseModel
            class Segment(BaseModel):
                start_time: str
                duration: int
                narration: str
                
            class SegmentList(BaseModel):
                segments: list[Segment]
                teaser_start_time: str
                teaser_duration: int
                
            response = client.models.generate_content(
                model=DEFAULT_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=SegmentList,
                )
            )
            res_dict = json.loads(response.text)
            print(f"Gemini suggested segments: {res_dict}")
            raw_segs = res_dict.get("segments", [])
            cleaned_segs = clean_overlapping_segments(raw_segs)
            
            # Validate: long video must have at least 5 segments totaling enough duration
            if not is_short:
                total_dur = sum(int(s.get("duration", 0)) for s in cleaned_segs)
                print(f"[Gemini] Long video: {len(cleaned_segs)} segments, total={total_dur}s ({total_dur//60}m {total_dur%60}s)")
                if len(cleaned_segs) < 5 or total_dur < 600:  # less than 5 segments or < 10 min
                    print(f"[Gemini] WARNING: Not enough segments ({len(cleaned_segs)}) or duration ({total_dur}s). Will use fallback distribution.")
                    return None  # Trigger fallback in bot.py
            
            return {
                "segments": cleaned_segs,
                "teaser_start_time": res_dict.get("teaser_start_time", "").strip(),
                "teaser_duration": int(res_dict.get("teaser_duration", 0))
            }
        except Exception as e:
            print(f"Attempt {attempt+1} failed to find segments with Gemini: {e}")
            if attempt == 2:
                return None
            time.sleep(2)

def get_video_duration(url):
    """Get the video title and duration in seconds using yt-dlp."""
    set_ffmpeg_path()
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    # Try multiple client strategies to bypass 403
    client_strategies = ["android", "ios", "tv_embedded", "mweb", None]
    cookie_prefix = ["--cookies", "cookies.txt"] if os.path.exists("cookies.txt") else []

    for client in client_strategies:
        cmd = [get_ytdlp_path()] + get_ytdlp_js_args() + [
               "--dump-json", "--no-playlist",
               "--user-agent", user_agent,
               "--no-check-certificates", "--force-ipv4"]
        if cookie_prefix:
            cmd += cookie_prefix
        if client:
            cmd += ["--extractor-args", f"youtube:player_client={client}"]
        cmd.append(url)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
            import json
            data = json.loads(res.stdout)
            return int(data.get("duration", 0)), data.get("title", "YouTube Clip")
        except Exception as e:
            print(f"[get_video_duration] client={client} failed: {e}")

    return 0, "YouTube Clip"

def download_youtube_clip(url, start_time_str, duration, output_path):
    """Download the full video and clip a single range locally to bypass YouTube's ffmpeg block."""
    set_ffmpeg_path()
    download_multiple_youtube_clips(url, [(start_time_str, duration)], output_path)
    return output_path

def download_multiple_youtube_clips(url, clip_ranges, output_path):
    """Download specific ranges directly from YouTube using --download-sections, with full fallback."""
    set_ffmpeg_path()

    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    # Base strategies for client options (order of preference: default/web client first for 1080p, then fallbacks)
    base_strategies = []
    if not os.path.exists("cookies.txt"):
        try:
            ensure_cookies("cookies.txt")
        except Exception:
            pass
    if os.path.exists("cookies.txt"):
        base_strategies.extend([
            ["--cookies", "cookies.txt"],
            ["--cookies", "cookies.txt", "--extractor-args", "youtube:player_client=ios"],
            ["--cookies", "cookies.txt", "--extractor-args", "youtube:player_client=android"]
        ])
    base_strategies.extend([
        ["--cookies-from-browser", "chrome"],   # কুকি ছাড়া ৩৬০p-ই দেয়
        [],
        ["--extractor-args", "youtube:player_client=ios"],
        ["--extractor-args", "youtube:player_client=android"],
        ["--extractor-args", "youtube:player_client=tv_embedded"],
        ["--extractor-args", "youtube:player_client=mweb"]
    ])

    segment_paths = []
    try:
        print("[yt-dlp] Attempting fast download-sections strategy...")
        for idx, (start_time_str, duration_val) in enumerate(clip_ranges):
            segment_path = output_path.replace(".mp4", f"_seg_{idx}.mp4")
            start_sec = parse_time(start_time_str)
            end_sec = start_sec + duration_val
            
            success = False
            for s_idx, extra in enumerate(base_strategies):
                cmd = [
                    get_ytdlp_path(),
                ] + get_ytdlp_js_args() + [
                    "-f", "bestvideo[height<=1080][vcodec*=avc]+bestaudio[ext=m4a]/bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/bestvideo+bestaudio/best",
                    "--merge-output-format", "mp4",
                    "--user-agent", user_agent,
                    "--socket-timeout", "30",
                    "--concurrent-fragments", "4",
                    "--retries", "5",
                    "--download-sections", f"*{start_sec}-{end_sec}",
                    "-o", segment_path,
                ] + extra + [url]
                
                try:
                    subprocess.run(cmd, check=True)
                    if os.path.exists(segment_path) and os.path.getsize(segment_path) > 100000:
                        success = True
                        break
                except Exception:
                    if os.path.exists(segment_path):
                        try:
                            os.remove(segment_path)
                        except:
                            pass
            if success:
                segment_paths.append(segment_path)
            else:
                raise RuntimeError("Failed to download section.")
                
        # If all sections succeeded, concatenate them
        concat_txt_path = output_path.replace(".mp4", "_concat_list.txt")
        with open(concat_txt_path, "w") as f:
            for seg in segment_paths:
                f.write(f"file '{os.path.abspath(seg)}'\n")
                
        concat_cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_txt_path,
            "-c", "copy",
            output_path
        ]
        subprocess.run(concat_cmd, check=True)
        
        # Cleanup
        for seg in segment_paths:
            if os.path.exists(seg):
                try:
                    os.remove(seg)
                except:
                    pass
        if os.path.exists(concat_txt_path):
            try:
                os.remove(concat_txt_path)
            except:
                pass
        print("[yt-dlp] Fast download-sections strategy succeeded!")
        return
        
    except Exception as fast_err:
        print(f"[yt-dlp] Fast strategy failed: {fast_err}. Falling back to full video download...")
        # Cleanup any partially downloaded segments
        for seg in segment_paths:
            if os.path.exists(seg):
                try:
                    os.remove(seg)
                except:
                    pass

    # FALLBACK: Download full video and slice locally (the original slower method)
    temp_full = output_path.replace(".mp4", "_temp_full.mp4")
    success = False
    for strategy in base_strategies:
        cmd = [
            get_ytdlp_path(),
        ] + get_ytdlp_js_args() + [
            "-f", "bestvideo[height<=1080][vcodec*=avc]+bestaudio[ext=m4a]/bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "--user-agent", user_agent,
            "--socket-timeout", "30",
            "--concurrent-fragments", "4",
            "--retries", "5",
            "-o", temp_full,
        ] + strategy + [url]
        
        try:
            subprocess.run(cmd, check=True)
            if os.path.exists(temp_full) and os.path.getsize(temp_full) > 100000:
                success = True
                break
        except Exception:
            if os.path.exists(temp_full):
                try:
                    os.remove(temp_full)
                except:
                    pass
                    
    if not success or not os.path.exists(temp_full):
        raise RuntimeError("Failed to download YouTube video using native yt-dlp.")
        
    # Cut the segments locally using ffmpeg and merge them
    segment_paths = []
    concat_txt_path = output_path.replace(".mp4", "_concat_list.txt")
    try:
        for idx, (start_time_str, duration_val) in enumerate(clip_ranges):
            segment_path = output_path.replace(".mp4", f"_seg_{idx}.mp4")
            crop_cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_time_str),
                "-t", str(duration_val),
                "-i", temp_full,
                "-c", "copy",
                "-avoid_negative_ts", "make_non_negative",
                segment_path
            ]
            subprocess.run(crop_cmd, check=True)
            if os.path.exists(segment_path):
                segment_paths.append(segment_path)
                
        with open(concat_txt_path, "w") as f:
            for seg in segment_paths:
                f.write(f"file '{os.path.abspath(seg)}'\n")
                
        concat_cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_txt_path,
            "-c", "copy",
            output_path
        ]
        subprocess.run(concat_cmd, check=True)
        
    finally:
        for seg in segment_paths:
            if os.path.exists(seg):
                try:
                    os.remove(seg)
                except:
                    pass
        if os.path.exists(temp_full):
            try:
                os.remove(temp_full)
            except:
                pass
        if os.path.exists(concat_txt_path):
            try:
                os.remove(concat_txt_path)
            except:
                pass
                    
    return output_path

def clean_bangla_title(title):
    if not title:
        return ""
    # Remove brackets and contents inside them
    cleaned = re.sub(r'[\(\[\{].*?[\)\]\}]', '', title)
    # Remove common promotional words
    cleaned = re.sub(r'(?i)bangla|new|natok|drama|shorts|clip|video|remastered|hd|4k|202\d|203\d', '', cleaned)
    # Replace separators with space
    cleaned = re.sub(r'\||:|–|-|—', ' ', cleaned)
    # Filter words to keep Bengali or alphanumeric
    words = cleaned.split()
    cleaned_words = []
    for w in words:
        if any('\u0980' <= c <= '\u09ff' for c in w) or any(c.isalnum() for c in w):
            cleaned_words.append(w)
    result = " ".join(cleaned_words).strip()
    return result if result else title

class OneEuroFilter:
    """1€ filter (Casiez et al., CHI 2012 — open source algorithm).

    Adaptive low-pass filter: kills jitter when the subject is still, yet
    stays responsive during fast movement — the industry-standard technique
    for smoothing noisy tracker signals without visible lag.
    """

    def __init__(self, freq, min_cutoff=0.4, beta=0.08, d_cutoff=1.0):
        import math  # keeps module-level deps unchanged
        self._math = math
        self.freq = float(freq)
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.x_prev = None
        self.dx_prev = 0.0

    def _alpha(self, cutoff):
        te = 1.0 / self.freq
        tau = 1.0 / (2 * self._math.pi * cutoff)
        return 1.0 / (1.0 + tau / te)

    def filter(self, x):
        if self.x_prev is None:
            self.x_prev = x
            return x
        dx = (x - self.x_prev) * self.freq
        edx = self.dx_prev + self._alpha(self.d_cutoff) * (dx - self.dx_prev)
        cutoff = self.min_cutoff + self.beta * abs(edx)
        xf = self.x_prev + self._alpha(cutoff) * (x - self.x_prev)
        self.x_prev, self.dx_prev = xf, edx
        return xf


# ─── Subject-tracking geometry (single source of truth) ──────────────────
# Long-form : crop 1/TRACK_ZOOM_LONG of each axis, then scale back up.
# Shorts    : pre-zoom the frame by TRACK_ZOOM_SHORT *before* the square crop.
#             A 1:1 crop of a 16:9 source has ZERO vertical room, so the camera
#             physically cannot follow a subject up/down. Pre-zooming buys that
#             room back without changing the final output size.
TRACK_ZOOM_LONG = 1.02
TRACK_ZOOM_SHORT = 1.15   # উল্লম্ব হেডরুম: ২৩px → ১৪৪px (মাথা ছাদে কাটা বন্ধ)


# ─── Face beautification (skin + tone) ───────────────────────────────────
# Tunable without touching code:
#   FACE_BEAUTY=0            -> off
#   FACE_BEAUTY_STRENGTH=0.5 -> half strength (subtle)
FACE_BEAUTY = os.environ.get("FACE_BEAUTY", "1").strip().lower() not in (
    "0", "false", "off", "no", "")
try:
    FACE_BEAUTY_STRENGTH = float(os.environ.get("FACE_BEAUTY_STRENGTH", "1.4"))
except ValueError:
    FACE_BEAUTY_STRENGTH = 1.0


def beauty_filter(strength: float | None = None) -> str:
    """
    Skin softening + gentle pop for faces, tuned to read as "good camera and
    good light" rather than an obvious filter.

    smartblur : smooths low-contrast areas (skin, light shadow) while the `lt`
                threshold protects high-contrast detail, so eyes, lips,
                eyebrows and hair stay crisp;
    unsharp   : puts crispness back into edges only (luma) — soft, never mushy,
                and no colour fringing on skin;
    eq        : small lift in brightness / contrast / saturation for a warmer,
                healthier skin tone;
    vibrance  : lifts muted colours (skin) more than already-saturated ones,
                so faces warm up without turning orange.

    A bilateral pass was tested and dropped: it flattens the eyes.
    """
    if not FACE_BEAUTY:
        return "null"
    v = max(0.0, min(2.0, FACE_BEAUTY_STRENGTH if strength is None else strength))
    if v <= 0.0:
        return "null"
    lr = 0.9 + 0.4 * v
    ls = -0.30 * v
    lt = 4.0 + 2.0 * v
    ua = 0.30 + 0.25 * v
    bri = 0.010 * v
    con = 1.0 + 0.025 * v
    sat = 1.0 + 0.05 * v
    vib = 0.10 * (v / 1.4)
    # ── গতি বনাম লুক ────────────────────────────────────────────────────
    # মাপা (১০s @1080p): smartblur একাই ~১.৫s (ফিল্টার-চেইনের সবচেয়ে ভারী ধাপ),
    # vignette ~০.৮s। FAST_RENDER=1 (ডিফল্ট) হলে smartblur বাদ — চেহারা প্রায়
    # একই থাকে (unsharp+eq+vibrance থাকে), রেন্ডার হবে ~২-৩ গুণ দ্রুত।
    # পুরো লুক দরকার হলে: FAST_RENDER=0
    fast = os.environ.get("FAST_RENDER", "1") != "0"
    parts = []
    if not fast:
        parts.append(f"smartblur=lr={lr:.2f}:ls={ls:.2f}:lt={lt:.1f}")
    parts.append(f"unsharp=5:5:{ua:.2f}:5:5:0.0")
    parts.append(f"eq=brightness={bri:.3f}:contrast={con:.3f}:saturation={sat:.3f}")
    parts.append(f"vibrance=intensity={vib:.3f}")
    return ",".join(parts)


def track_crop_chain(face_cmd_prefix="", is_short=False, out_w=None, out_h=None):
    """
    ffmpeg filter chain that crops a subject-following window.

    The sendcmd file drives crop x/y, so the crop filter must stay in exactly
    this shape or the command coordinates fall out of sync with the frame.
    """
    if is_short:
        z = TRACK_ZOOM_SHORT
        out = f"scale={out_w or 1080}:{out_h or 1080}:flags=lanczos"
        return (
            f"scale=iw*{z}:ih*{z},{face_cmd_prefix}"
            f"crop@sq=w='trunc(min(iw,ih)/{z}/2)*2':h='trunc(min(iw,ih)/{z}/2)*2':"
            f"x='(iw-ow)/2':y='(ih-oh)/2',{out}"
        )
    # লং: ক্রপ-উইন্ডো **১৬:৯** — উৎস ৪:৩ বা ৯:১৬ হলেও আউটপুট বিকৃত হবে না,
    # আর উইন্ডো ফ্রেমের ভিতরে থাকে বলে কোনো কালো বার আসে না।
    out = f"scale={out_w or 1920}:{out_h or 1080}:flags=lanczos"
    # ⚠️ এই চেইনে **একটাই** crop থাকতে হবে — sendcmd `crop x/y` ফিল্টার-ইনডেক্স
    # ধরে কাজ করে; বাড়তি crop বসালে কমান্ড ভুল ফিল্টারে গিয়ে ট্র্যাকিং স্থির
    # হয়ে যায় (ঠিক এই ভুলটাই হয়েছিল)। ক্রপ-উইন্ডো ১৬:৯, তাই scale-ই যথেষ্ট।
    return (
        f"{face_cmd_prefix}"
        f"crop@sq=w='trunc(min(iw,ih*16/9)/{TRACK_ZOOM_LONG}/2)*2':"
        f"h='trunc(min(ih,iw*9/16)/{TRACK_ZOOM_LONG}/2)*2':"
        f"x='(iw-ow)/2':y='(ih-oh)/2',{out},setsar=1"
    )


def compute_face_sendcmd_file(input_path, speed_factor, is_short, sample_fps=5.0, out_fps=None,
                            content_w=None, content_h=None, pre_crop=""):
    """
    Subject-tracking (face + body) crop helper.

    Samples downscaled frames from the video (hflipped, so coordinates match
    the crop-chain orientation) and detects the dominant subject:
      1. YuNet (opencv_zoo, Apache-2.0) DNN face detector — catches faces
         Haar misses (small, angled, distant);
      2. Haar cascade fallbacks (frontal → profile face → upper body →
         full body) keep the person framed when no face is visible.
    The track is de-noised (median outlier rejection, gap interpolation) and
    smoothed with a critically-damped spring, then written as an ffmpeg
    sendcmd commands file with one command per output frame, so the crop
    window glides instead of stepping.

    Returns the commands file path, or None when tracking is not possible
    (OpenCV missing, no stable subject found, or any error) — the caller then
    keeps the static center crop.
    """
    try:
        import cv2
    except Exception as e:
        print(f"[subject-track] OpenCV unavailable ({e}); keeping static center crop")
        return None

    tmp_path = None
    try:
        set_ffmpeg_path()

        clip = VideoFileClip(input_path)
        try:
            src_w, src_h = clip.size
            duration = clip.duration
            src_fps = float(getattr(clip, "fps", 0) or 0)
        finally:
            clip.close()
        # ⚠️ sendcmd কমান্ড **আউটপুট ফ্রেমের** সাথে মিলতে হবে। আগে ডিফল্ট ৩০ fps
        # ধরে নেওয়া হতো, কিন্তু সোর্স ২৫ fps হলে আউটপুটও ২৫ fps — তখন ক্রপ
        # ভুল সময়ে বসে গিয়ে ছবি কেঁপে যেত ("shake")। তাই আসল fps ব্যবহার করি।
        if not out_fps:
            # আউটপুট ফ্রেম = সোর্স ফ্রেম (setpts শুধু সময় সংকুচিত করে), তাই
            # কার্যকর fps = src_fps × speed — কমান্ড ঠিক এই ছন্দে বসালেই প্রতিটি
            # ফ্রেমে সঠিক অবস্থান পড়ে (এবং ছবি আর কাঁপে না)।
            out_fps = (src_fps * speed_factor) if src_fps and src_fps > 1 else 30.0
        # ⚠️ বার কাটা হলে ক্রপ-ফিল্টার যে ফ্রেমটা দেখে সেটা ছোট — ট্র্যাকিংও
        # ঠিক ওই ফ্রেমের মাপে হিসাব করতে হবে, নইলে বিষয় ফ্রেমের কিনারায় চলে যায়।
        if content_w and content_h:
            src_w, src_h = float(content_w), float(content_h)
        if not src_w or not src_h or not duration or duration < 1.0:
            return None

        # Mirror of the crop window sizes used by the ffmpeg crop filters below.
        # NOTE: sendcmd coordinates are expressed in the frame the crop filter
        # actually sees — for Shorts that frame has already been pre-zoomed.
        if is_short:
            # ffmpeg's scale uses int(iw*zoom) (truncation), so mirror that here
            eff_w = float(int(src_w * TRACK_ZOOM_SHORT))
            eff_h = float(int(src_h * TRACK_ZOOM_SHORT))
            crop_w = math.floor(min(eff_w, eff_h) / TRACK_ZOOM_SHORT / 2.0) * 2.0
            crop_h = crop_w
        else:
            eff_w, eff_h = float(src_w), float(src_h)
            # ১৬:৯ উইন্ডো (উপরের ffmpeg এক্সপ্রেশনের হুবহু নকল)
            _w = min(src_w, src_h * 16.0 / 9.0)
            _h = min(src_h, src_w * 9.0 / 16.0)
            crop_w = math.floor(_w / TRACK_ZOOM_LONG / 2.0) * 2.0
            crop_h = math.floor(_h / TRACK_ZOOM_LONG / 2.0) * 2.0

        track_x = crop_w < eff_w - 4      # room to slide horizontally
        track_y = crop_h < eff_h - 4      # room to slide vertically
        if not track_x and not track_y:
            return None  # window already covers the frame; nothing to follow

        # Detect on small hflipped frames (hflip matches the processing chain)
        sample_w = 320
        sample_h = max(2, int(round(src_h * sample_w / src_w / 2.0)) * 2)
        sample_cmd = [
            "ffmpeg", "-v", "error",
            "-i", input_path,
            "-vf", f"{pre_crop}hflip,fps={sample_fps},scale={sample_w}:{sample_h}",
            "-pix_fmt", "bgr24",
            "-f", "rawvideo", "pipe:1",
        ]
        proc = subprocess.Popen(sample_cmd, stdout=subprocess.PIPE)
        frame_bytes = sample_w * sample_h * 3
        # Primary detector: YuNet (opencv_zoo, Apache-2.0) — a tiny open-source
        # DNN model that reliably catches faces Haar misses (small, angled,
        # distant). Fallbacks: Haar body cascades keep the person framed when
        # no face is visible (profile shots, over-the-shoulder, back shots).
        yunet = None
        model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "assets", "models", "face_detection_yunet_2023mar.onnx")
        if os.path.exists(model_path):
            try:
                yunet = cv2.FaceDetectorYN_create(model_path, "", (sample_w, sample_h), score_threshold=0.55)
            except Exception as e:
                print(f"[subject-track] YuNet load failed ({e}); using Haar cascades only")
                yunet = None
        else:
            print("[subject-track] YuNet model missing; using Haar cascades only")

        haar_detectors = [
            (cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml"), (24, 24), 5, True),
            (cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml"), (24, 24), 4, True),
            (cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_upperbody.xml"), (36, 20), 5, False),
            (cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_fullbody.xml"), (36, 60), 5, False),
        ]

        centers = []  # (cx, cy) in 0..1; None while no subject seen yet
        prev_c = None  # last accepted subject centre (for "sticky" selection)
        vel = [0.0, 0.0]   # বিষয়ের গতি (prediction-এর জন্য)
        prev_size = 0.0    # আগের মুখের ক্ষেত্রফল (মাপের ধারাবাহিকতা)
        misses = 0         # কত ফ্রেম ধরে বিষয় হারিয়ে গেছে
        tiny = 0           # কত ফ্রেম ধরে বিষয় অন্য মুখের তুলনায় অনেক ছোট
        prev_gray_ref = [None]   # মোশন ফলব্যাকের জন্য আগের ফ্রেম (grayscale)
        motion_hits = [0]        # কত ফ্রেমে মোশন-ফলব্যাক ব্যবহার হয়েছে
        cut_count = [0]          # কতগুলো শট-কাট ধরা পড়েছে
        motion_hist = [[]]       # মোশন-ফলব্যাকের সাম্প্রতিক কেন্দ্র (স্থিরতা যাচাই)
        no_face_run = [0]        # টানা কত ফ্রেম কোনো মুখ/শরীর পাওয়া যায়নি
        diff_avg = [2.0]         # চলমান ফ্রেম-diff গড় (গতিশীল কাট-সীমার জন্য)
        _last_for_diff = [None]  # চলমান গড়ের জন্য আগের ফ্রেম
        motion_streak = [0]      # টানা কত ফ্রেম একই জায়গায় নড়াচড়া
        cut_at = []              # কোন স্যাম্পল-ইনডেক্সে শট-কাট ধরা পড়েছে

        def pick(candidates, prev):
            """
            Choose which detection is *our* subject.

            Picking the biggest face is what makes tracking look unstable: the
            moment a second person walks in, the crop abandons the subject it
            was following and slides across the frame. So we prefer the face
            closest to where the subject was last seen, and only fall back to
            the biggest one when that face has genuinely disappeared.
            """
            if not candidates:
                return None, False

            def ctr(c):
                return ((c[0] + c[2] / 2) / sample_w, (c[1] + c[3] / 2) / sample_h)

            if prev is not None:
                # গতিবেগ দিয়ে ভবিষ্যদ্বাণী: দ্রুত হাঁটা/ক্যামেরা প্যানে বিষয়
                # ৩০%-এর বেশি সরে গেলেও আগের মানুষটাকেই ধরা পড়ে।
                px = prev[0] + vel[0]
                py = prev[1] + vel[1]
                best_key, best = None, None
                for c in candidates:
                    cx, cy = ctr(c)
                    d = math.hypot(cx - px, cy - py)
                    d_prev = math.hypot(cx - prev[0], cy - prev[1])
                    # মাপের ধারাবাহিকতা: কাছের মানুষ → দূরের মানুষ লাফ দেওয়া বন্ধ
                    size_pen = 0.0
                    if prev_size:
                        area = c[2] * c[3]
                        size_pen = min(1.5, abs(math.log(max(area, 1e-6) / prev_size)))
                    key = (round(d + 0.35 * size_pen, 4), d_prev)
                    if best_key is None or key < best_key:
                        best_key, best = key, c
                # সহনশীল দূরত্ব: আগে ০.৩০ ছিল — দুইজন মানুষ কাছাকাছি এলে
                # ভুল মানুষ ধরে ফেলত। এখন ০.৫৫ (ভবিষ্যদ্বাণী সহ)।
                # প্রক্সিমিটি-সীমা মুখের মাপের সমানুপাতিক: ক্লোজ-আপে (মুখ
                # স্ক্রিন-ভরা) কেন্দ্র নড়ে অনেক দূরে — ছোট সীমায় লক ভেঙে
                # বড় মুখে লাফাত ("দুই-মুখের দোলা")। সীমা = আগের মুখের
                # প্রস্থের ১.৫× (ন্যূনতম ০.৫৫)।
                _lim = max(0.35, 1.5 * math.sqrt(max(prev_size, 0.0)))
                if best_key is not None and best_key[0] <= _lim:
                    return best, best[4]

            biggest = max(candidates, key=lambda c: c[2] * c[3])
            return biggest, biggest[4]

        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            frame = np.frombuffer(buf, np.uint8).reshape(sample_h, sample_w, 3)
            candidates = []
            if yunet is not None:
                res = yunet.detect(frame)
                faces = res[1] if isinstance(res, tuple) else res
                if faces is not None and len(faces) > 0:
                    for f in faces:
                        candidates.append((float(f[0]), float(f[1]), float(f[2]), float(f[3]), True))
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if not candidates:
                for det, min_sz, nbrs, face_cascade in haar_detectors:
                    found = det.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=nbrs, minSize=min_sz)
                    if len(found) > 0:
                        for (bx, by, bw, bh) in found:
                            candidates.append((float(bx), float(by), float(bw), float(bh), bool(face_cascade)))
                        break

            box, is_face = pick(candidates, prev_c)

            # ── মোশন ফলব্যাক ────────────────────────────────────────────────
            # পিঠ ঘুরানো শট, দূরের ওয়াইড শট, অন্ধকার দৃশ্য — মুখ/শরীর কোনোটাই
            # ধরা পড়ে না। তখন পুরো ক্লিপ স্ট্যাটিক ক্রপে চলে যেত (ব্যবহারকারীর
            # অভিযোগ: "মাঝে মাঝে ট্র্যাকিং হয় না")। এখন ফ্রেম-পার্থক্য দিয়ে
            # যেখানে নড়াচড়া হচ্ছে সেটাই ধরি — পুরো ফ্রেম নড়লে (ক্যামেরা প্যান)
            # সেটা বাদ দিই, কারণ তখন ক্রপ নিজেই ঠিক থাকে।
            if box is None:
                no_face_run[0] += 1
            else:
                no_face_run[0] = 0
            if box is None and prev_gray_ref[0] is not None:
                try:
                    d = cv2.absdiff(gray, prev_gray_ref[0])
                    d = cv2.GaussianBlur(d, (5, 5), 0)
                    _th, mask = cv2.threshold(d, 18, 255, cv2.THRESH_BINARY)   # ২২→১৮: মৃদু নড়াচড়াও ধরা পড়ে
                    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=2)
                    cnts, _h = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                                cv2.CHAIN_APPROX_SIMPLE)
                    cand = [cv2.boundingRect(c) for c in cnts]
                    cand = [c for c in cand if c[2] * c[3] > 0.015 * sample_w * sample_h]
                    whole = [c for c in cand if c[2] * c[3] > 0.55 * sample_w * sample_h]
                    cand = [c for c in cand if c not in whole]   # গোটা ফ্রেম নড়া = ক্যামেরা
                    # টাইটেল/এন্ড-কার্ড (গ্রাফিক) হলে বড় "মোশন" দেখায় কিন্তু
                    # বিষয় থাকে না — বড় জোন (২৫%+) বাদ দিই; সব বাদ পড়লে
                    # ক্রপ শেষ অবস্থানেই স্থির থাকে (টাইটেলে ক্যামেরা ঘোরানো ঠিক নয়)।
                    cand = [c for c in cand if c[2] * c[3] < 0.25 * sample_w * sample_h]
                    # টানা অনেকক্ষণ কোনো মুখ/শরীর না পাওয়া গেলে (নাটক শেষ →
                    # গ্রাফিক/টাইটেল জোন) মোশন-ফলব্যাক পুরোপুরি বন্ধ — গ্রাফিকের
                    # ফ্ল্যাশ/স্ফুলিংকে ধরে ক্যামেরা আর লাফাবে না (শেষদিকের শেক)।
                    if no_face_run[0] > sample_fps * 2.0:
                        cand = []
                    if cand:
                        if prev_c is not None:
                            cand.sort(key=lambda c: math.hypot(
                                (c[0] + c[2] / 2) / sample_w - prev_c[0],
                                (c[1] + c[3] / 2) / sample_h - prev_c[1]))
                        else:
                            cand.sort(key=lambda c: -c[2] * c[3])
                        bx0, by0, bw0, bh0 = cand[0]
                        mcx = (bx0 + bw0 / 2) / sample_w
                        mcy = (by0 + bh0 / 2) / sample_h
                        # স্থিরতা যাচাই: টানা ৩ ফ্রেম একই জায়গার (±১০%) নড়াচড়া
                        # তবেই গ্রহণ — এক-ফ্রেমের র‍্যান্ডম টুকরা (পাখি, চারা, তালু)
                        # ক্রপ লাফায় না। মানুষ হারিয়ে গেলে ক্রপ শেষ অবস্থানে থাকে,
                        # যা লাফানোর চেয়ে অনেক ভালো দেখায়।
                        if (motion_hist[0] and
                                math.hypot(mcx - motion_hist[0][-1][0],
                                           mcy - motion_hist[0][-1][1]) < 0.10):
                            motion_streak[0] += 1
                        else:
                            motion_streak[0] = 1
                        motion_hist[0].append((mcx, mcy))
                        if len(motion_hist[0]) > 3:
                            motion_hist[0].pop(0)
                        if motion_streak[0] >= 3:
                            box = (float(bx0), float(by0),
                                   float(bw0), float(bh0), False)
                            motion_hits[0] += 1
                except Exception:
                    pass
            # ── নাটকের "কাট" (shot change) সনাক্ত → নতুন শটে নতুন করে লক ────
            # প্রতিটি শটে মানুষ আলাদা জায়গায়। কাট না ধরলে আগের শটের অবস্থানে
            # ক্রপ আটকে থাকে → নতুন শটের মানুষ কাটা পড়ে ("প্রতিটা কাটে ঠিক করো")।
            if prev_gray_ref[0] is not None:
                try:
                    _dd = cv2.absdiff(gray, prev_gray_ref[0])
                    # কাট-মাপ: গড় diff নয় (হালকা কাট diff=২-এ হারায়), গতিশীল
                    # সীমা = চলমান গড়ের ৪× (ন্যূনতম ৪) — হালকা কাট ধরে, সাধারণ
                    # ক্যামেরা-নড়া ফলস হয় না।
                    _mv = float(np.mean(_dd))
                    if float(np.percentile(_dd, 50)) > max(4.0, 4.0 * diff_avg[0]):
                        prev_c, prev_size, vel = None, 0.0, [0.0, 0.0]
                        misses = 0
                        cut_count[0] += 1
                        cut_at.append(len(centers))   # এই স্যাম্পলেই কাট
                except Exception:
                    pass
            prev_gray_ref[0] = gray
            try:
                diff_avg[0] = 0.95 * diff_avg[0] + 0.05 * float(np.mean(cv2.absdiff(gray, _last_for_diff[0] if _last_for_diff[0] is not None else gray)))
                _last_for_diff[0] = gray
            except Exception:
                pass

            if box is not None:
                misses = 0
                # (v2-তে এখানে "ছোট হলে লক ছেড়ে দাও" নিয়ম ছিল — তাতে ট্র্যাকিং
                #  মানুষ বদলাত। ব্যবহারকারী চান একই মানুষ ধরে রাখা → সরানো হলো।)
            elif prev_c is not None:
                misses += 1
                # ২.৫ সেকেন্ড ধরে বিষয় হারিয়ে গেলে তবেই নতুন মানুষ ধরব —
                # আগে এক ফ্রেম মিসেই পুরোনো পরিচয় মুছে যেত → ভুল মানুষ ধরা পড়ত
                # ২.৫s → ৬s: বেশি সময় ধরে একই মানুষ ধরে রাখি (কম বার বদলায়)
                if misses > int(sample_fps * 6.0):
                    prev_c, prev_size, vel = None, 0.0, [0.0, 0.0]
            if box is not None:
                bx, by, bw, bh = box[:4]
                raw_c = ((bx + bw / 2) / sample_w, (by + bh / 2) / sample_h)
                # For face hits, aim the frame centre at the upper body (chest)
                # so the body stays framed, not just the head
                # Aim a little below the face so chest/shoulders stay in frame,
                # but CAP the shift: an unbounded chest offset pushes the window
                # past the top of the available crop room, which is what made
                # the subject sit 20% off-centre in Shorts.
                # ০.০৮ (৮%) অফসেটে মুখ ফ্রেমের উপরের কিনারায় চলে যেত → কাটা পড়ত।
                # এখন ৩%-এ সীমিত, তবু বুক/কাঁধ ফ্রেমে থাকে।
                chest = min(0.45 * bh / sample_h, 0.03) if is_face else 0.0
                cy = raw_c[1] + chest
                if prev_c is not None:
                    # গতিবেগ = শেষ দুই ডিটেকশনের পার্থক্য (α-স্মুদিত)
                    vel[0] = 0.6 * (raw_c[0] - prev_c[0]) + 0.4 * vel[0]
                    vel[1] = 0.6 * (raw_c[1] - prev_c[1]) + 0.4 * vel[1]
                prev_c = raw_c
                prev_size = float(bw * bh)
                centers.append((raw_c[0], min(cy, 1.0)))
            else:
                # ⚠️ prev_c এখানে মুছি না — পরিচয় ধরে রাখি (উপরে ২.৫s টাইমআউট)
                centers.append(None)
        proc.stdout.close()
        proc.wait()

        n = len(centers)
        found = sum(1 for c in centers if c is not None)
        # ২৫% → ১৫%: কম-দৃশ্যমান সাবজেক্টেও ট্র্যাকিং চালু রাখি (ব্যবহারকারীর
        # চাহিদা: "সব ভিডিও ট্র্যাকিং হবে")। তার নিচে হলে স্ট্যাটিক ক্রপই নিরাপদ,
        # কারণ ভুল ডিটেকশন নাড়ালে ক্রপ কাঁপে — সেটা আরও খারাপ দেখায়।
        # ১৫% → ৫%: অর্ধেক ফ্রেমে মুখ না পেলেও আংশিক ট্র্যাক স্ট্যাটিক ক্রপের
        # চেয়ে ভালো — স্ট্যাটিক ক্রপে বিষয় ফ্রেমের বাইরে চলে যায়।
        if n == 0 or found < max(2, int(n * 0.05)):
            print(f"[subject-track] No stable subject ({found}/{n} samples); keeping static center crop")
            return None
        if found < int(n * 0.5):
            print(f"[subject-track] Sparse subject ({found}/{n}) — gap-fill + spring smoothing")

        # ── Gap filling ───────────────────────────────────────────────────
        # Interpolate through short detection gaps instead of freezing on the
        # last position (freezing, then resuming, is itself a visible jerk).
        # Gaps longer than ~1.5 s are held so the crop never invents motion.
        rel_x = [c[0] if c else None for c in centers]
        rel_y = [c[1] if c else None for c in centers]
        hold_max = max(2, int(sample_fps * 1.5))
        for i in range(n):
            if rel_x[i] is not None:
                continue
            lo = i - 1
            while lo >= 0 and rel_x[lo] is None:
                lo -= 1
            hi = i + 1
            while hi < n and rel_x[hi] is None:
                hi += 1
            if lo < 0 and hi >= n:
                continue
            if lo < 0:
                rel_x[i], rel_y[i] = rel_x[hi], rel_y[hi]
            elif hi >= n or hi - lo > hold_max:
                rel_x[i], rel_y[i] = rel_x[lo], rel_y[lo]
            else:
                f = (i - lo) / float(hi - lo)
                rel_x[i] = rel_x[lo] + (rel_x[hi] - rel_x[lo]) * f
                rel_y[i] = rel_y[lo] + (rel_y[hi] - rel_y[lo]) * f

        # ── Outlier rejection ─────────────────────────────────────────────
        # A single bad detection (motion blur, a hand in front of the face)
        # would otherwise drag the whole smoothing filter off for ~1 s.
        def median5(seq):
            """৫-ট্যাপ মিডিয়ান (০.৪s): ডিটেকশনের এক-ফ্রেম শব্দ (হাত, ব্লার) মুছে
            দেয় — শব্দ থাকলে ক্যামেরা অকারণে এক-দুই পিক্সেল নড়ে ("নরচরা")।"""
            out = list(seq)
            half = 2
            for i in range(len(seq)):
                lo = max(0, i - half)
                hi = min(len(seq), i + half + 1)
                out[i] = sorted(seq[lo:hi])[len(seq[lo:hi]) // 2]
            return out

        rel_x = median5(rel_x)
        rel_y = median5(rel_y)

        # Desired crop offsets in the *cropped* frame's pixels, for every sample
        # মাথার উপরে জায়গা: টার্গেট-লাইন ৫০% → ৪২% (মুখ একটু উপরে,
        # শরীর নিচে — গ্রুপ শটে মাথা কাটা পড়ে না)
        face_y_frac = 0.42 if is_short else 0.50

        def targets(rel_xv, rel_yv):
            tx = rel_xv * eff_w - crop_w / 2
            ty = rel_yv * eff_h - crop_h * face_y_frac
            return (
                min(max(tx, 0), eff_w - crop_w),
                min(max(ty, 0), eff_h - crop_h),
            )

        txs, tys = zip(*[targets(x, y) for x, y in zip(rel_x, rel_y)])

        # ── প্যান-শট গার্ড ────────────────────────────────────────────────
        # নাটকের শেষ শটে প্রায়ই ক্যামেরা নিজেই দুই কিনারায় প্যান করে (মানুষ
        # ফ্রেমজুড়ে হাঁটে)। তখন টার্গেট ০ ↔ (eff_w − crop_w) পুরো রেঞ্জে ছুটে
        # যায় → ক্রপ প্রতি সেকেন্ডে ৩০০–৪০০px নড়ে ("শেষদিকে বেশি নরচরা")।
        # কোনো অংশে টার্গেট এক সেকেন্ডে ২০% ক্রপ-প্রস্থের বেশি দৌড়ালে সেই
        # অংশ জমে যায় (শেষ স্থান ধরে রাখি) — স্থির ফ্রেম অগোছালো প্যানের চেয়ে ভালো।
        def freeze_runaway(seq, crop_sz):
            """
            প্যান-শট গার্ড (ভ২-সংশোধিত)।

            আগের সংস্করণ একবার জমলে **শেষ পর্যন্ত** জমে থাকত — শট-কাটে
            নতুন মানুষের টার্গেট লাফ (৪৩২→৬১৭px) ধরা পড়ে সারা শট ধরে
            টার্গেট পুরোনো জায়গায় আটকে থাকত; contain তখন টার্গেটকে
            ব্যান্ডের কিনারায় ঠেলে দিত → ক্রিয়েটর স্থায়ীভাবে ৬০%-এ বসে
            থাকত ("ক্রিয়েটর মাঝে থাকবে" ভাঙত)।

            এখন: টার্গেট টানা টানা বড় লাফ দিলে (আসল ক্যামেরা-প্যান) জমি,
            কিন্তু টার্গেট ৬ স্যাম্পল (০.৫s) স্থির থাকলে **ছেড়ে দিই** —
            নতুন মানুষের কাছে স্প্রিং মসৃণভাবে এগিয়ে যায়।
            """
            out = list(seq)
            max_step = crop_sz * 0.20            # এক স্যাম্পল-ধাপের সীমা
            frozen = None
            calm = 0
            for i in range(1, len(out)):
                # ক্যালম-মাপ **কাঁচা** মানে (out ওভাররাইট হয়ে যায়)
                step_raw = abs(seq[i] - seq[i - 1])
                if frozen is not None:
                    if step_raw < max_step * 0.25:
                        calm += 1
                        if calm >= 6:            # ০.৫s স্থির → ছেড়ে দিই
                            frozen = None
                            calm = 0
                    else:
                        calm = 0
                    if frozen is not None:
                        out[i] = frozen
                elif step_raw > max_step:
                    frozen = seq[i - 1]           # এখান থেকে জমে যাই
                    calm = 0
                    out[i] = frozen
            return out

        txs = freeze_runaway(list(txs), crop_w)
        tys = freeze_runaway(list(tys), crop_h)

        # ── Smoothing ─────────────────────────────────────────────────────
        # A critically-damped spring, not a dead-band. A dead-band holds still
        # and then snaps at full speed the moment the subject leaves it — that
        # "hold … jerk" IS the shake people notice. A spring accelerates and
        # decelerates continuously, so there is no discontinuity anywhere.
        # A centred 3-tap pass afterwards is symmetric, so it adds no lag.
        dt = 1.0 / sample_fps
        snap_dist = crop_w * 0.35          # bigger than this = scene cut

        # ── হার্ড কনটেইনমেন্ট (টার্গেট-নিরপেক্ষ) ──────────────────────────
        # আগের সীমা ছিল "টার্গেটের ±২২%" — টার্গেট নিজেই কিনারায় গেলে ক্রপও
        # কিনারায় বসে থাকত → বিষয় ফ্রেমের বাইরে। এখন সরাসরি নিয়ম:
        # বিষয়ের কেন্দ্র অবশ্যই ক্রপ-ফ্রেমের ২০%–৮০% এর ভিতরে থাকবে (প্রতি স্যাম্পলে)।
        # rel = বিষয়ের কেন্দ্র (0..1); ক্রপ x-কেন্দ্র rel-এর ±০.৩০ এর ভিতরে বাধ্য করি।
        def contain_to_subject(pos_seq, tgt_seq, crop_sz, eff_sz, rels):
            lo, hi = 0.40 * crop_sz, 0.60 * crop_sz   # বিষয় ফ্রেমের ৪০–৬০% (মাঝে)
            out = []
            for pos, tgt, rel in zip(pos_seq, tgt_seq, rels):
                s = rel * eff_sz                     # বিষয়ের কেন্দ্র (eff পিক্সেল)
                x_min = s - hi                       # বিষয় ক্রপের ৭০% লাইনের ডানে নয়
                x_max = s - lo                       # বিষয় ক্রপের ৩০% লাইনের বাঁয়ে নয়
                x_min = max(0.0, x_min)
                x_max = min(eff_sz - crop_sz, x_max)
                if x_min > x_max:                    # বিষয় কিনারায় — একবারে সেন্টার
                    c = min(max(s - crop_sz / 2, 0.0), eff_sz - crop_sz)
                else:
                    c = min(max(tgt, x_min), x_max)
                out.append(c)
            return out

        cut_mask = set(cut_at)

        def stabilise(track, crop_sz):
            """
            শান্ত ক্যামেরা — "ডেড-জোন + সেন্টার-স্ন্যাপ" (ব্রডকাস্টে এভাবেই হয়)।

            সমস্যা ছিল দুইদিকেই: ক্যামেরা সারাক্ষণ মাইক্রো-নড়াচড়া করত
            ("নরচরা"), আবার দ্রুত প্যানে বিষয় বাইরে চলে যেত। সমাধান:

              ১. বিষয় কেন্দ্রের ±১৫% এর ভিতরে থাকলে ক্যামেরা **সম্পূর্ণ স্থির**
                 (এক পিক্সেলও নড়ে না → ছবি স্থির, চোখে আরাম)
              ২. বিষয় ১৫% ছাড়ালে একবার **পূর্ণ-সেন্টার** করার জন্য মসৃণ ভাবে এগোয়
              ৩. সেন্টারে (±৩%) পৌঁছালে আবার থেমে যায় → দীর্ঘ সময় স্থির
              ৪. বিষয় ২৫% ছাড়ালে দ্রুত ধরে (৫০%/s) — ফ্রেমের বাইরে যেতে দেয় না
              ৫. শেষে হার্ড-সীমা: বিষয় সবসময় ফ্রেমের ২৫–৭৫% এর ভিতরে

            ফলে নড়াচড়া হয় **কম সংখ্যকবার, প্রতিবার মসৃণ ও উদ্দেশ্যপূর্ণ** —
            সারাক্ষণ গড়িয়ে চলার বদলে।
            """
            dt = 1.0 / sample_fps
            # ব্যবহারকারীর রিপোর্ট: "নরচরা করে, shake করে"। তাই:
            #   • বড় ডেড-জোন (২২%) — এর ভিতরে থাকলে ক্যামেরা **এক পিক্সেলও নড়ে না**
            #   • খুব ধীর প্যান (৮% ক্রপ/সেকেন্ড) — চোখে প্রায় অদৃশ্য
            #   • বড় tau (০.৯s) — নরম ইজিং, হঠাৎ শুরু/থামা নেই
            # ডেড-জোন ২২% ছিল — তাতে বিষয় স্থায়ীভাবে কেন্দ্র থেকে ২২% পর্যন্ত
            # সরে বসে থাকত ("ক্রিয়েটর মাঝে থাকবে" ভাঙত)। এখন ১০%: বিষয় কেন্দ্র
            # থেকে ১০%-এর বেশি সরলে ক্যামেরা মসৃণভাবে এগিয়ে তাকে আবার মাঝে
            # আনে; ১০%-এর ভিতরে থাকলে ক্যামেরা সম্পূর্ণ স্থির (নরচরা নেই)।
            # ডেড-জোন এখন ৫%: বিষয় কেন্দ্র থেকে ৫%-এর (৪৩px) বেশি সরলে
            # ক্যামেরা মসৃণভাবে এগিয়ে তাকে মাঝে আনে — ৪০–৬০% ব্যান্ড
            # কঠোরভাবে ধরে রাখে। নড়াটা ধীর (৮%/সে + tau ০.৯s) তাই চোখে
            # শান্ত লাগে, ঝাঁকুনি নেই।
            idle_zone = crop_sz * 0.05
            settle = crop_sz * 0.03
            slow = crop_sz * 0.08
            fast = crop_sz * 0.45
            tau = 0.9
            pos, moving, out = track[0], False, []
            for i, tgt in enumerate(track):
                err = tgt - pos
                if cut_mask and i in cut_mask:
                    # শট-কাট: একবারে নতুন বিষয়ের জায়গায় বসাই (কাটের সাথে
                    # মিলে যায়, চোখে লাগে না) — নইলে স্প্রিং প্রায় পুরো শট
                    # ধরে পিছু নিত আর ক্রিয়েটর কিনারায় থাকত।
                    pos, moving = tgt, False
                    out.append(pos)
                    continue
                if abs(err) > crop_sz * 0.25:
                    # দৃশ্য বদল → সাথে সাথে বসাই। (০.৬ ক্রপ/সেকেন্ডের "গ্লাইড"
                    # চেষ্টা করেছিলাম — তাতে কয়েক ফ্রেম বিষয় কিনারায় গিয়ে
                    # **কাটা পড়ত**। ব্যবহারকারীর রিপোর্ট: "কাটে কাটে দেখা যাচ্ছে"।)
                    pos, moving = tgt, False
                    out.append(pos)
                    continue
                if not moving and abs(err) > idle_zone:
                    moving = True
                if moving and abs(err) < settle:
                    moving = False
                if moving:
                    step = err * min(1.0, dt / tau)
                    # টার্গেট যদি স্বয়ং দ্রুত এগোয় (হাঁটা/প্যান ফলো), ক্রপকেও
                    # তার ছন্দে যেতে দিতে হয় — নইলে মানুষ ক্রপের কিনারায়
                    # চলে যায় ("ট্র্যাকিং ক্রিয়েটর মাঝে থাকবে" ভাঙে)। টার্গেট
                    # -গতি = সাম্প্রতিক টার্গেট-পরিবর্তন।
                    # ক্যাপ-স্তর: বিষয় কেন্দ্র থেকে অনেক দূরে (>১৫%) হলে
                    # ধরতে হয় দ্রুত (২৫%/সে) — নইলে স্প্রিং পুরো শট ধরে
                    # পিছু নিত আর ক্রিয়েটর কিনারায় বসে থাকত। ছোট দূরত্বে
                    # ধীর (৮%/সে) — শান্ত ক্যামেরা।
                    _e = abs(err)
                    if _e > crop_sz * 0.25:
                        cap = fast
                    elif _e > crop_sz * 0.15:
                        cap = crop_sz * 0.25
                    else:
                        cap = slow
                    pos += max(-cap, min(cap, step))
                out.append(pos)
            # বিষয় সবসময় ফ্রেমের ৩৫–৬৫% এর ভিতরে → কাটার সুযোগ নেই
            lim = crop_sz * 0.15
            return [max(tgt - lim, min(tgt + lim, s)) for s, tgt in zip(out, track)]

        # ── কেন্দ্র-ভিত্তিক টার্গেট ─────────────────────────────────────────
        # লক্ষ্য: বিষয় **ফ্রেমের কেন্দ্রে**। আগে ডেড-জোন টার্গেটের সাপেক্ষে ছিল —
        # বিষয় ফ্রেমের ডানে স্থির হলেও ক্রপ "যথেষ্ট কাছে" ভেবে নড়ত না →
        # মানুষ ফ্রেমের ৭০% পর্যন্ত সরে যেত। এখন প্রথমে টার্গেটকে
        # contain_to_subject দিয়ে বিষয়-কেন্দ্রিক করি, তারপর স্মুদিং — ডেড-জোন
        # এখন "কেন্দ্র-ব্যান্ডে" কাজ করে, বিষয় কেন্দ্রের কাছে হলেই ক্যামেরা স্থির।
        if track_x:
            txs = contain_to_subject(list(txs), list(txs), crop_w, eff_w, rel_x)
        if track_y:
            tys = contain_to_subject(list(tys), list(tys), crop_h, eff_h, rel_y)

        sm_x = stabilise(txs, crop_w) if track_x else list(txs)
        sm_y = stabilise(tys, crop_h) if track_y else list(tys)

        # শেষ হার্ড-গ্যারান্টি: বিষয় **কখনোই** ফ্রেমের ৪০–৬০% এর বাইরে যাবে না।
        # ⚠️ এখানে স্মুদ করা পজিশনকেই সীমায় বাঁধি (tgt = sm)। আগে কাঁচা টার্গেট
        # (txs) পাঠানো হতো → ভিতরে থাকলেই স্প্রিংয়ের স্মুদিং বাতিল হয়ে কাঁচা,
        # কাঁপা টার্গেট সরাসরি ক্রপে চলে যেত ("নরচরা")।
        if track_x:
            sm_x = contain_to_subject(sm_x, sm_x, crop_w, eff_w, rel_x)
        if track_y:
            sm_y = contain_to_subject(sm_y, sm_y, crop_h, eff_h, rel_y)

        # ── চূড়ান্ত গতি-সীমা (কাট ছাড়া) ─────────────────────────────────
        # কনটেইনমেন্টের ফলে মাঝে মাঝে ১২০–১৪০px/স্যাম্পল "পিছু নেওয়া" হয়
        # (মানুষ ফ্রেমে ঢুকলে ক্রপ দৌড়ে পৌঁছায়) — চোখে লাফ লাগে। চূড়ান্ত
        # ট্র্যাকে প্রতি স্যাম্পলে সর্বোচ্চ ১৫% ক্রপ-প্রস্থ নড়া দিই; একমাত্র
        # শট-কাটের (টার্গেট >৪৫% লাফ) সাথে মিললে সীমা নেই — ওখানে একবারে
        # নতুন মানুষে বসা স্বাভাবিক এবং কাটের সাথে মিলে যায়।
        def final_speed_limit(seq, tgt_seq, crop_sz):
            out = list(seq)
            max_step = crop_sz * 0.15
            jump = crop_sz * 0.45
            for i in range(1, len(out)):
                tstep = abs(tgt_seq[i] - tgt_seq[i - 1])
                if tstep > jump:            # শট-কাট: সীমা নেই
                    continue
                delta = out[i] - out[i - 1]
                if abs(delta) > max_step:
                    out[i] = out[i - 1] + max_step if delta > 0 else out[i - 1] - max_step
            return out

        if track_x:
            sm_x = final_speed_limit(sm_x, txs, crop_w)
        if track_y:
            sm_y = final_speed_limit(sm_y, tys, crop_h)

        def sample_at(track, input_t):
            """Linear interpolation of the 5 Hz track at any input timestamp."""
            pos = input_t * sample_fps
            i = int(math.floor(pos))
            if i >= len(track) - 1:
                return track[-1]
            if i < 0:
                return track[0]
            f = pos - i
            return track[i] + (track[i + 1] - track[i]) * f

        # ── sendcmd on the OUTPUT timeline ────────────────────────────────
        # crop sits after setpts=PTS/speed → output_time * speed = input_time.
        # Old code emitted one command every 200 ms (5 Hz): the window held
        # still, then jumped a chunk. That staircase IS the visible camera
        # shake. Now there is one command per output frame, interpolated from
        # the smoothed track, so the window glides instead of stepping.
        out_dur = duration / speed_factor
        n_out = max(2, int(round(out_dur * out_fps)))
        lines = []
        for k in range(n_out):
            t_out = k / out_fps
            t_in = min(t_out * speed_factor, max(duration - 1e-3, 0.0))
            if track_x:
                x_px = int(round(min(max(sample_at(sm_x, t_in), 0), eff_w - crop_w)))
                lines.append(f"{t_out:.3f} crop@sq x {x_px};")
            if track_y:
                y_px = int(round(min(max(sample_at(sm_y, t_in), 0), eff_h - crop_h)))
                lines.append(f"{t_out:.3f} crop@sq y {y_px};")
        if not lines:
            return None

        fd, tmp_path = tempfile.mkstemp(prefix="face_cmds_", suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        print(f"[subject-track] Subject on {found}/{n} samples "
              f"(মোশন-ফলব্যাক {motion_hits[0]} · শট-কাট {cut_count[0]}) → crop follows smoothly ({tmp_path})")
        return tmp_path
    except Exception as e:
        print(f"[subject-track] Tracking failed ({e}); keeping static center crop")
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return None


# ── পোড়া কালো বার (letterbox) সনাক্তকরণ ────────────────────────────────────
def detect_letterbox(path, samples=(0.15, 0.35, 0.55, 0.75, 0.9), limit=24):
    """
    উৎস ভিডিওর **ভিতরে পোড়া** কালো বার মাপে এবং `crop=W:H:X:Y` স্ট্রিং ফেরত দেয়
    (বার না থাকলে None)।

    কেন দরকার: নিচের ফিল্টার-চেইন উৎসকে `scale=1080:1920` করে **স্ট্রেচ** করে, তারপর
    মাঝখানে স্কয়ার-ক্রপ বসায়। উৎসে যদি সিনেমার মতো উপরে-নিচে কালো বার পোড়া থাকে,
    স্ট্রেচে সেই বার আরও মোটা হয়ে যায় — ব্যবহারকারীর দেখা "উপরে-নিচে কালো বার"
    ঠিক এটাই (মাপা: ১০৮০×১৯২০ ফ্রেমে ৬২px + ১৬৪px = ১১.৮%)।
    """
    import shutil as _sh, subprocess as _sp
    from collections import Counter
    ff = _sh.which("ffmpeg") or "ffmpeg"
    try:
        dur = float(_sp.run(
            [ff, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", "-i", str(path)],
            capture_output=True, text=True, timeout=60).stdout.strip() or 0)
    except Exception:
        dur = 0
    crops = []
    for frac in samples:
        ss = max(0.0, dur * frac) if dur else 0.0
        try:
            out = _sp.run(
                [ff, "-hide_banner", "-nostats", "-ss", f"{ss:.2f}", "-i", str(path),
                 "-vf", f"cropdetect=limit={limit}:round=2:reset=0", "-frames:v", "12",
                 "-f", "null", "-"],
                capture_output=True, text=True, timeout=120).stderr
        except Exception:
            continue
        for line in out.splitlines():
            if "crop=" in line:
                crops.append(line.split("crop=")[-1].split()[0])
    if not crops:
        return None
    best, _n = Counter(crops).most_common(1)[0]
    try:
        w, h, x, y = (int(v) for v in best.split(":"))
    except Exception:
        return None

    # ── বৈধতা যাচাই ─────────────────────────────────────────────────────
    # এক-রঙা/এজবিহীন ফ্রেমে cropdetect মাঝে মাঝে আবর্জনা দেয় (যেমন
    # crop=-1278:-718:1280:720)। সেগুলো বাদ না দিলে পরিষ্কার ভিডিওতেও
    # ভুল ক্রপ বসে ফ্রেম নষ্ট হয়ে যেত।
    iw, ih = probe_size(path)
    if not iw or not ih:
        return None
    if w <= 0 or h <= 0 or x < 0 or y < 0:
        return None
    if w > iw or h > ih or x + w > iw + 2 or y + h > ih + 2:
        return None
    if w >= iw - 4 and h >= ih - 4:      # পুরো ফ্রেম = বার নেই
        return None
    # খুব ছোট পার্থক্য (<১.৫%) উপেক্ষা — কোডেক-নয়েজ, আসল বার নয়
    if (iw - w) < iw * 0.015 and (ih - h) < ih * 0.015:
        return None
    return f"crop@bars={w}:{h}:{x}:{y},"


# ── BGM বাছাই: নিজের গান (own) → CC0 ────────────────────────────
_CC0_BGM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "assets", "audio", "cc0")
# নিজের গান/মিউজিক এখানে রাখো — বট এগুলোও BGM হিসেবে মেশাবে
_OWN_BGM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "assets", "audio", "own")


def _bgm_candidates(bgm_dir: str) -> list[str]:
    """
    BGM তালিকা। অগ্রাধিকার: `assets/audio/own/` (নিজের গান) → `cc0/` (কপিরাইট-ফ্রি)।

    .env দিয়ে নিয়ন্ত্রণ:
        BGM_POOL=own   → শুধু নিজের গান (খালি হলে cc0 fallback)
        BGM_POOL=cc0   → শুধু কপিরাইট-ফ্রি ট্র্যাক
        BGM_POOL=mix   → দুটোই মিশিয়ে র‍্যান্ডম
        (ডিফল্ট: own-এ কিছু থাকলে own, নইলে cc0)
    """
    _bad = {"bgm_combined.mp3"}          # ২১ MB কনক্যাট — BGM হিসেবে অচল

    def _mp3(d: str, allow_legacy: bool = False) -> list[str]:
        if not d or not os.path.isdir(d):
            return []
        out = []
        for f in sorted(os.listdir(d)):
            if not f.lower().endswith((".mp3", ".wav", ".m4a", ".ogg")):
                continue
            if f in _bad or f.startswith("outro_"):
                continue
            # cc0 ছাড়া অন্য ফোল্ডারে পুরোনো bgm1..4 বাদ (লাইসেন্স অজানা)
            if not allow_legacy and f in ("bgm1.mp3", "bgm2.mp3", "bgm3.mp3", "bgm4.mp3"):
                continue
            out.append(os.path.join(d, f))
        return out

    own = _mp3(_OWN_BGM_DIR, allow_legacy=True)
    cc0 = _mp3(_CC0_BGM_DIR)
    mode = os.environ.get("BGM_POOL", "").strip().lower()
    if mode == "cc0":
        return cc0 or own
    if mode == "mix":
        return (own + cc0) or _mp3(bgm_dir, allow_legacy=True)
    if mode == "own":
        return own or cc0
    # ডিফল্ট: নিজের গান থাকলে সেটাই, নইলে কপিরাইট-ফ্রি
    return own if own else (cc0 or _mp3(bgm_dir, allow_legacy=True))

def ensure_cookies(path: str = "cookies.txt") -> bool:
    """
    YouTube এখন কুকি/PO-token ছাড়া ৩৬০p-এর বেশি দেয় না (ফলে ১০৮০ নরম দেখায়)।
    Chrome-এর কুকি থেকে একবার cookies.txt বানাই → পরে সব ডাউনলোডে ব্যবহার হবে।
    """
    if os.path.exists(path) and os.path.getsize(path) > 100:
        return True
    try:
        import yt_dlp
    except Exception:
        return False
    for browser in ("chrome", "edge", "brave", "firefox"):
        try:
            opts = {"quiet": True, "no_warnings": True, "skip_download": True,
                    "cookiesfrombrowser": (browser,), "cookiefile": path}
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info("https://www.youtube.com/watch?v=aqz-KE-bpKQ",
                                 download=False)
            if os.path.exists(path) and os.path.getsize(path) > 100:
                print(f"[cookies] ✅ {browser} থেকে cookies.txt তৈরি")
                return True
        except Exception:
            continue
    return False

def upscale_sharpen(input_path: str) -> str:
    """
    উৎস ১০৮০-এর কম হলে (যেমন ৭২০p ভিডিও) ১০৮০-তে বড় করার সময় detail ফিরিয়ে আনি।

    কারণ: ৭২০p → ১০৮০ মানে ১.৫× আপস্কেল — পিক্সেল নেই, তাই নরম দেখায়।
    `cas` (Contrast Adaptive Sharpen) আপস্কেলের নরম ভাবটা অনেকটাই ফেরায়,
    প্রান্তে হ্যালো ছাড়াই। উৎস ১০৮০+ হলে কিছুই যোগ হয় না (খরচও নেই)।
    """
    try:
        import subprocess as _sp, shutil as _sh, re as _re
        ff = _sh.which("ffmpeg") or "ffmpeg"
        err = _sp.run([ff, "-hide_banner", "-i", input_path],
                      capture_output=True, text=True, timeout=60).stderr
        m = _re.search(r"Video:.*?, (\d+)x(\d+)", err)
        if not m:
            return ""
        h = min(int(m.group(1)), int(m.group(2)))
        if h >= 1080:
            return ""
        if os.environ.get("UPSCALE_SHARPEN", "1") == "0":
            return ""
        print(f"[upscale] উৎস {h}p < ১০৮০ → CAS শার্পেনিং যোগ")
        return "cas=strength=0.55,"
    except Exception:
        return ""

def probe_size(path):
    """(width, height) — ffprobe ছাড়াই ffmpeg stderr থেকে।"""
    import re as _re, shutil as _sh, subprocess as _sp
    ff = _sh.which("ffmpeg") or "ffmpeg"
    try:
        err = _sp.run([ff, "-hide_banner", "-i", str(path)],
                      capture_output=True, text=True, timeout=60).stderr
        m = _re.search(r"Video:.*?, (\d{2,5})x(\d{2,5})", err)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return 0, 0


def process_clip_copyright_bypass(input_path, output_path, is_short=False, bgm_dir="assets/audio", mix_bgm=True, video_title=None, thumb_path=None, srt_path=None, intro_path=None, outro_path=None, avatar_path=None, narration_path=None):
    """
    Apply hard-level copyright bypass filters using synced FFmpeg commands:
    1. Horizontal Mirror (hflip).
    2. Vibrant color filter (eq).
    3. Speed up (1.04x) for the video.
    4. Zoom-in (1.05x) and crop to bypass structural comparison.
    5. Keep original dialogue/vocals while removing low-frequency/high-frequency background music.
    6. Overlay and mix custom BGM track.
    7. Crop to vertical 9:16 for Shorts.
    8. Prepend thumbnail image as first 1.5s of the video (optional).
    """
    set_ffmpeg_path()

    # ── আউটপুট সেটিংস: ১:১ স্কয়ার · ১০৮০ · অরিজিনাল কণ্ঠ ────────────────
    # FORCE_SQUARE=1 (ডিফল্ট): লং ভিডিওও ১:১ (১০৮০×১০৮০) ক্রপ হবে
    # VOICE_ORIGINAL=1 (ডিফল্ট): শিল্পীর নিজের কণ্ঠ অটুট — পিচ বদলাবে না (AI ভয়েস নয়)
    sq = bool(is_short) or os.environ.get("FORCE_SQUARE", "1") != "0"
    voice_original = os.environ.get("VOICE_ORIGINAL", "1") != "0"
    # MUTE_DIALOGUE=1 → ভিডিওর কণ্ঠ/ডায়ালগ বাদ, শুধু BGM থাকবে
    mute_dialogue = os.environ.get("MUTE_DIALOGUE", "0") == "1"
    _dial_vol = "0" if mute_dialogue else "1.35"

    f_bangla = get_best_font_path("bangla")
    f_english = get_best_font_path("english")
    watermark_text = os.environ.get("WATERMARK_TEXT", "Tawhidul official")
    
    # Get random BGM file
    bgm_files = _bgm_candidates(bgm_dir)

    bgm_path = random.choice(bgm_files) if bgm_files else None
    
    # Check if the input file has an audio track and get exact duration
    has_audio = True
    duration = 30.0
    try:
        clip = VideoFileClip(input_path)
        duration = clip.duration
        has_audio = clip.audio is not None
        clip.close()
    except Exception:
        has_audio = True
        
    encoder, encoder_args = get_best_encoder()


    # Randomize bypass factors for 0% copyright matching (changes fingerprint hash on every single run)
    # Using subtle pitch shift for both shorts and long videos to maintain crystal clear voice quality
    speed_factor = random.uniform(1.045, 1.055)
    if voice_original:
        # নিজের কণ্ঠ অটুট: পিচ-শিফট নেই, শুধু সামান্য গতি (atempo পিচ ঠিক রাখে)
        pitch_factor = 1.0
        tempo_factor = speed_factor
        _pitch_part = ""          # asetrate বাদ → কণ্ঠ যেমন ছিল তেমনই
        print(f"[voice] অরিজিনাল কণ্ঠ — পিচ অটুট, গতি {speed_factor:.3f}× (tempo {tempo_factor:.3f})")
    else:
        # Modified AI Voice Changer Filter (shifts pitch up or down distinctly to change vocal timber)
        if random.choice([True, False]):
            pitch_factor = random.uniform(1.12, 1.18)  # High-pitched AI voice filter
        else:
            pitch_factor = random.uniform(0.82, 0.87)  # Deep-pitched AI voice filter
        tempo_factor = speed_factor / pitch_factor
        _pitch_part = f"{_pitch_part}"

    # ── Face tracking: build a sendcmd file so the crop window follows the face ──
    # শুধু শর্টস-চেইনে ফেস-ক্রপ ব্যবহার হয়। লং-ফর্ম এখন ফুল-ব্লিড cover-crop করে,
    # তাই ওখানে sendcmd লাগে না। আগে সব ভিডিওতে ৫ fps-এ YuNet/Haar চলত →
    # ৩০ মিনিটের লং ভিডিওতে হাজার হাজার ফ্রেম বিশ্লেষণ = পুরো সময়ের বড় অংশ নষ্ট।
    face_cmd_file = None
    face_cmd_prefix = ""
    
    # Randomize EQ values per run for viral cinematic drama style (high contrast, warm skin tones, vibrant saturation)
    rand_contrast = round(random.uniform(1.12, 1.20), 3)
    rand_brightness = round(random.uniform(0.010, 0.020), 3)
    rand_saturation = round(random.uniform(1.25, 1.35), 3)
    
    # Rich cinematic drama skin-tone and shadow balance (Teal & Orange grading)
    rand_rs = round(random.uniform(-0.05, -0.02), 3)
    rand_gs = round(random.uniform(-0.02, 0.0), 3)
    rand_bs = round(random.uniform(0.03, 0.06), 3)
    
    rand_rm = round(random.uniform(0.05, 0.09), 3)
    rand_gm = round(random.uniform(-0.01, 0.02), 3)
    rand_bm = round(random.uniform(-0.08, -0.04), 3)
    
    # Highlights (glowing clear faces)
    rand_rh = round(random.uniform(0.04, 0.08), 3)
    rand_gh = round(random.uniform(0.0, 0.03), 3)
    rand_bh = round(random.uniform(-0.06, -0.02), 3)

    # Formulate filter_complex
    cleaned_title = ""
    if video_title:
        cleaned_title = clean_bangla_title(video_title)
        
    display_title = f"Part-1 | {cleaned_title}" if cleaned_title else ""
    # Shape Bengali characters for correct rendering in FreeType/FFmpeg
    display_title = shape_bengali(display_title)
    display_title = display_title.replace(":", "\\:").replace("'", "").replace("\"", "")
    
    title_overlay = ""
    if display_title:
        if sq:
            # Clean static text overlay in greenyellow color
            title_overlay = f",drawtext=text='{display_title}':x=(w-tw)/2:y=240:fontsize=96:fontcolor=greenyellow:bordercolor=black:borderw=8:fontfile='{f_bangla}'"
        else:
            # Keep yellow title bar only for long compilation videos
            title_overlay = f",drawtext=text='{display_title}':x=(w-tw)/2:y=h-160:fontsize=90:fontcolor=yellow:bordercolor=black:borderw=6:fontfile='{f_bangla}'"
    # Generate snow overlay if sq
    has_snow = False
    snow_path = None
    if sq:
        try:
            snow_path = ensure_snow_overlay()
            if snow_path and os.path.exists(snow_path):
                has_snow = True
        except Exception as e:
            print(f"[Warning] Failed to generate snow overlay: {e}")

    # Dynamically build inputs and keep track of their indices
    cmd_inputs = []
    
    # Input 0: Main video
    cmd_inputs += ["-i", input_path]
    main_idx = 0

    # আউটপুটের DAR জোর করে ঠিক রাখি — উৎসের অদ্ভুত SAR (যেমন 256:81) ক্যারি হয়ে
    # ফাইলটা 1080x1920 হয়েও 16:9 দেখালে মোবাইল প্লেয়ার বার বসিয়ে স্কেল করে।
    # শর্টস এখন ১:১ স্কয়ার (বার-মুক্ত, ফুল-ব্লিড)
    _ASPECT = "1:1" if sq else "16:9"
    # লং-ফর্ম আগে জোর করে 4K (3840x2160) বানাত → মোবাইলে ৪ গুণ পিক্সেল ডিকোড,
    # ব্যাটারি/হিট/ল্যাগ। এখন ডিফল্ট 1080p; দরকার হলে KEEP_4K=1 দিয়ে 4K।
    if sq:
        _LW, _LH = 1080, 1080
    elif os.environ.get("KEEP_4K", "0") == "1":
        _LW, _LH = 3840, 2160
    else:
        _LW, _LH = 1920, 1080
    _LONG = f"{_LW}:{_LH}"

    # উৎসে পোড়া কালো বার থাকলে আগেই কেটে নিই (নইলে স্ট্রেচে বার মোটা হয়)
    _up_sharp = upscale_sharpen(input_path)   # ৭২০p → ১০৮০ হলে CAS যোগ

    bars_prefix = ""
    # নিজেরাই বানানো স্টক ভিডিও ঠিক টার্গেট সাইজে থাকে — ওতে বার থাকতেই পারে না।
    # cropdetect কালো দৃশ্যে ভুল করে "বার" ধরে ফেলে (১০৮০×১০৮০ → ১০৮০×৯০০ হয়ে যেত),
    # তাই টার্গেট সাইজে হলে সনাক্তকরণ বাদ দিই।
    _skip_bars = False
    try:
        import shutil as _sh2
        _ff2 = _sh2.which("ffmpeg") or "ffmpeg"
        _e2 = __import__("subprocess").run([_ff2, "-hide_banner", "-i", str(input_path)],
                                           capture_output=True, text=True, timeout=60).stderr
        _m2 = __import__("re").search(r"Video:.*?, (\d+)x(\d+)", _e2)
        if _m2:
            _iw, _ih = int(_m2.group(1)), int(_m2.group(2))
            if (_iw, _ih) == (_LW, _LH):
                # শুধু তখনই বাদ, যখন ইনপুটই ঠিক আউটপুট সাইজ (স্টক ভিডিও)।
                # ১৯২০×১০৮০ উৎসে পোড়া বার থাকলে সেটা কাটতেই হবে, নইলে
                # ১:১ ক্রপের উপরে-নিচে কালো বার থেকে যায়।
                _skip_bars = True
                print(f"[letterbox] ইনপুট {_iw}×{_ih} = আউটপুট সাইজ — বার-সনাক্তকরণ বাদ")
    except Exception:
        pass
    try:
        _bars = None if _skip_bars else detect_letterbox(input_path)
        if _bars:
            bars_prefix = _bars
            print(f"[letterbox] উৎসের কালো বার কাটা হচ্ছে: {_bars.rstrip(',')}")
    except Exception as _e:
        print(f"[letterbox] সনাক্তকরণ ব্যর্থ (উপেক্ষা): {_e}")

    # ── ফেস-ট্র্যাকিং: **বার কাটার পরে** যে ফ্রেমটা থাকে, তার মাপে হিসাব ──
    # আগে পুরো ফ্রেমের (১০৮০) মাপে হিসাব হতো, কিন্তু ক্রপ-ফিল্টার দেখত
    # ৮৬৪ উচ্চতার ফ্রেম → বিষয় ফ্রেমের কিনারায়/কাটা পড়ত ("মাঝে মাঝে ট্র্যাক
    # ঠিক জায়গায় বসে না")। এখন কনটেন্ট-মাপ + একই প্রি-ক্রপ দিয়ে স্যাম্পল করি।
    _cw, _ch, _pre = None, None, ""
    if _bars:
        try:
            _nums = _bars.replace("crop@bars=", "").strip(",;").split(":")
            _cw, _ch = int(_nums[0]), int(_nums[1])
            _pre = _bars if _bars.endswith(",") else _bars + ","
        except Exception:
            _cw, _ch = None, None
    try:
        face_cmd_file = compute_face_sendcmd_file(
            input_path, speed_factor, sq,
            sample_fps=12.0 if sq else 5.0,
            content_w=_cw, content_h=_ch, pre_crop=_pre,
        )
        face_cmd_prefix = f"sendcmd=f='{face_cmd_file}'," if face_cmd_file else ""
    except Exception as _e:
        print(f"[subject-track] ট্র্যাকিং বাদ (উপেক্ষা): {_e}")
        face_cmd_file, face_cmd_prefix = None, ""

    inputs_count = 1
    
    bgm_idx = -1
    snow_idx = -1
    thumb_idx = -1
    
    # Input: BGM
    has_bgm = bool(bgm_path and os.path.exists(bgm_path) and mix_bgm)
    if has_bgm:
        bgm_start_ss = random.choice([30, 35, 40, 45, 50])
        cmd_inputs += ["-stream_loop", "-1", "-ss", str(bgm_start_ss), "-i", bgm_path]
        bgm_idx = inputs_count
        inputs_count += 1
        
    # Input: Snow overlay
    if has_snow:
        cmd_inputs += ["-stream_loop", "-1", "-i", snow_path]
        snow_idx = inputs_count
        inputs_count += 1
        
    # Input: Thumbnail image
    has_thumb = bool(thumb_path and os.path.exists(thumb_path))
    if has_thumb:
        cmd_inputs += ["-loop", "1", "-t", "1.5", "-i", thumb_path]
        thumb_idx = inputs_count
        inputs_count += 1

    # Input: Custom Intro Voiceover
    intro_idx = -1
    has_intro = bool(intro_path and os.path.exists(intro_path))
    if has_intro:
        cmd_inputs += ["-i", intro_path]
        intro_idx = inputs_count
        inputs_count += 1

    # Input: Custom Outro Voiceover
    outro_idx = -1
    has_outro = bool(outro_path and os.path.exists(outro_path))
    if has_outro:
        cmd_inputs += ["-i", outro_path]
        outro_idx = inputs_count
        inputs_count += 1

    # Input: Custom Avatar Logo
    avatar_idx = -1
    has_avatar = bool(avatar_path and os.path.exists(avatar_path))
    if has_avatar:
        cmd_inputs += ["-i", avatar_path]
        avatar_idx = inputs_count
        inputs_count += 1
        
    # Input: AI Narration Voiceover
    narration_idx = -1
    has_narration = bool(narration_path and os.path.exists(narration_path))
    if has_narration:
        cmd_inputs += ["-i", narration_path]
        narration_idx = inputs_count
        inputs_count += 1

    # Load outro duration if present
    outro_duration = 0.0
    delay_ms = 0
    if has_outro:
        try:
            from moviepy import AudioFileClip
            o_clip = AudioFileClip(outro_path)
            outro_duration = o_clip.duration
            o_clip.close()
            # Calculate output duration and delay based on speed factor
            output_duration = duration / speed_factor
            delay_sec = max(0, output_duration - outro_duration)
            delay_ms = int(delay_sec * 1000)
        except Exception as e:
            print(f"[Warning] Failed to load outro file duration: {e}")
            delay_ms = int(max(0, (duration / speed_factor) - 5) * 1000)

    # ── Build filter_complex and map arguments ───────────────────────────────
    # IMPORTANT: FFmpeg concat filter with n=2:v=1:a=1 requires exactly 4 inputs:
    #   [v_seg1][a_seg1][v_seg2][a_seg2]concat=n=2:v=1:a=1[v][a]
    # When has_thumb=True we must include BOTH the thumb audio AND main audio
    # INSIDE the same filter_complex so concat gets all 4 streams.
    # When has_thumb=False we use the simpler separate v_filter/a_filter approach.

    def build_filter_with_thumb(enc, enc_args):
        """Build a single unified filter_complex that prepends the thumbnail."""
        parts = []

        # ── Thumbnail video ─────────────────────────────────────────────────
        if sq:
            parts.append(f"[{thumb_idx}:v]scale=1080:1080:force_original_aspect_ratio=decrease,"
                         f"pad=1080:1080:(ow-iw)/2:(oh-ih)/2,setsar=1[v_t]")
        else:
            parts.append(f"[{thumb_idx}:v]scale={_LONG},setsar=1[v_t]")

        # Thumbnail silent audio (1.5 s, stereo 44100 Hz)
        parts.append("aevalsrc=0:c=stereo:s=44100:d=1.5[a_t]")

        avatar_sz = 220 if sq else 300
        # ── Main video ──────────────────────────────────────────────────────
        if sq:
            v_main = (
                f"[{main_idx}:v]{bars_prefix}hflip,eq=contrast={rand_contrast}:brightness={rand_brightness}:saturation={rand_saturation},"
                f"colorbalance=rs={rand_rs}:gs={rand_gs}:bs={rand_bs}:rm={rand_rm}:gm={rand_gm}:bm={rand_bm}:rh={rand_rh}:gh={rand_gh}:bh={rand_bh},"
                f"{_up_sharp}unsharp=7:7:1.2:7:7:1.2,setpts=PTS/{speed_factor:.4f},"
                f"{track_crop_chain(face_cmd_prefix, is_short=sq)},{beauty_filter()}"
                f"{title_overlay}[v_main_raw]"
            )
            parts.append(v_main)
        else:
            # High-level copyright bypass visual canvas layout for long compilation videos (4K HD output with face correction, static stable rendering)
            parts.append(
                f"[{main_idx}:v]{bars_prefix}hflip,{_up_sharp}unsharp=7:7:1.2:7:7:1.2,eq=contrast={rand_contrast}:brightness={rand_brightness}:saturation={rand_saturation},"
                f"hue=h=-6:s=1.08,colorbalance=rs={rand_rs}:gs={rand_gs}:bs={rand_bs}:rm={rand_rm}:gm={rand_gm}:bm={rand_bm}:rh={rand_rh}:gh={rand_gh}:bh={rand_bh},"
                f"setpts=PTS/{speed_factor:.4f},"
                f"{track_crop_chain(face_cmd_prefix, is_short=sq, out_w=_LW, out_h=_LH)},"
                f"{beauty_filter()},"
                f"drawtext=text='{watermark_text}':x=200:y=h-260:fontsize=68:fontcolor=white:bordercolor=black:borderw=5:fontfile='{f_english}',"
                f"drawtext=text='On My YouTube Channel':x=200:y=h-180:fontsize=44:fontcolor=yellow:bordercolor=black:borderw=4:fontfile='{f_english}'"
                f"{title_overlay}[v_main_raw]"
            )
            
        v_main_name = "[v_main_raw]"
        if has_avatar and os.environ.get("SHOW_AVATAR", "0") == "1":
            r = avatar_sz // 2
            parts.append(f"[{avatar_idx}:v]scale={avatar_sz}:{avatar_sz},format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(hypot(X-{r},Y-{r}),{r}),255,0)'[avatar_round]")
            pad = 60 if sq else 100
            parts.append(f"{v_main_name}[avatar_round]overlay=x={pad}:y={pad}[v_main_p]")
        else:
            parts.append(f"{v_main_name}format=yuv420p[v_main_p]")

        # ── Main audio (Crystal clear AI/Studio voice with background noise cancellation) ─────────────────
        if sq:
            audio_eq = (
                f"[{main_idx}:a]afftdn=noise_reduction=10,aresample=44100,"
                f"highpass=f=200,lowpass=f=3500,"
                f"equalizer=f=120:width_type=h:width=50:g=2.0,"
                f"equalizer=f=3000:width_type=h:width=1000:g=2.0,"
                f"acompressor=threshold=-15dB:ratio=3:attack=5:release=50,"
                f"{_pitch_part}asetpts=N/SR/TB,"
                f"atempo={tempo_factor:.4f},volume={_dial_vol}"
            )
            bgm_vol_val = 0.28
        else:
            # Flawless crystal clear audio settings for long compilation videos matching Shorts
            audio_eq = (
                f"[{main_idx}:a]afftdn=noise_reduction=10,aresample=44100,"
                f"highpass=f=200,lowpass=f=3500,"
                f"equalizer=f=120:width_type=h:width=50:g=2.0,"
                f"equalizer=f=3000:width_type=h:width=1000:g=2.0,"
                f"acompressor=threshold=-15dB:ratio=3:attack=5:release=50,"
                f"{_pitch_part}asetpts=N/SR/TB,"
                f"atempo={tempo_factor:.4f},volume={_dial_vol}"
            )
            bgm_vol_val = 0.28
        if has_audio:
            parts.append(f"{audio_eq}[a_eq]")
            current_dialogue = "[a_eq]"
            
            if has_intro:
                parts.append(f"[{intro_idx}:a]asetpts=N/SR/TB,volume=1.8[intro_vol]")
                parts.append(f"{current_dialogue}[intro_vol]amix=inputs=2:duration=first:normalize=0[diag_intro]")
                current_dialogue = "[diag_intro]"
                
            if has_narration:
                # ⚠️ "extra voice" বাগ: আগে উৎস ক্লিপের নিজের কথা volume=0.35-এ
                # রাখা হতো, তাই ন্যারেশনের নিচে মূল ক্লিপের কণ্ঠও শোনা যেত —
                # দুই কণ্ঠ একসাথে। এখন ডিফল্টে উৎস-কণ্ঠ **বন্ধ** (0.0);
                # ইচ্ছা করলে KEEP_ORIG_AUDIO_VOL=0.35 দিয়ে ফেরানো যায়।
                parts.append(f"[{narration_idx}:a]asetpts=N/SR/TB,volume=1.5[narr_vol]")
                # amix-এ উৎস রাখতেই হয় (নইলে [a_eq] আউটপুট unconnected → ffmpeg এরর),
                # কিন্তু ভলিউম ০ হলে কিছু শোনা যায় না → "extra voice" আর নেই।
                _orig_vol = float(os.environ.get(
                    "KEEP_ORIG_AUDIO_VOL", "0.95" if voice_original else "0") or 0)
                parts.append(f"{current_dialogue}volume={_orig_vol}[orig_bg]")
                parts.append(f"[orig_bg][narr_vol]amix=inputs=2:duration=first:normalize=0[diag_narr]")
                current_dialogue = "[diag_narr]"
                
            if has_outro:
                parts.append(f"[{outro_idx}:a]asetpts=N/SR/TB,adelay={delay_ms}|{delay_ms},volume=1.8[outro_vol]")
                parts.append(f"{current_dialogue}[outro_vol]amix=inputs=2:duration=first:normalize=0[diag_outro]")
                current_dialogue = "[diag_outro]"
                
            if has_bgm:
                parts.append(f"[{bgm_idx}:a]asetpts=N/SR/TB,volume={bgm_vol_val}[bgm_vol]")
                parts.append(f"{current_dialogue}[bgm_vol]amix=inputs=2:duration=first[a_main_out]")
            else:
                parts.append(f"{current_dialogue}acopy[a_main_out]")
        else:
            # No audio track — use BGM only, or silence
            if has_bgm:
                parts.append(f"[{bgm_idx}:a]asetpts=N/SR/TB,volume=0.80[a_main_out]")
            else:
                parts.append("aevalsrc=0:c=stereo:s=44100[a_main_out]")

        # ── Concat thumbnail + main  (video + audio streams) ────────────────
        # concat n=2:v=1:a=1 needs: [v_t][a_t][v_main_p][a_main_out]
        v_main_final = "[v_main_p]"
        if srt_path and os.path.exists(srt_path):
            escaped_srt = srt_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
            margin = 200 if sq else 80
            font_sz = 64 if sq else 24
            sub_filter = f"[v_main_p]subtitles='{escaped_srt}':force_style='Alignment=2,MarginV={margin},OutlineColour=&H000000,BorderStyle=3,Outline=3,Shadow=0,Fontname=Arial,Fontsize={font_sz},PrimaryColour=&H00FFFF'[v_main_sub]"
            parts.append(sub_filter)
            v_main_final = "[v_main_sub]"
        # SAR ঠিক করা: উৎসের SAR (যেমন 256:81) ক্যারি হয়ে গেলে ফাইলটা
        # 1080x1920 হয়েও DAR 16:9 দেখায় → মোবাইল প্লেয়ার একে চওড়া করে,
        # উপরে-নিচে বার + স্কেলিং-স্ট্রেস। setsar=1 দিলে DAR ঠিক 9:16 হয়।
        parts.append(f"{v_main_final}setsar=1[v_sar]")
        parts.append(f"[v_t][a_t][v_sar][a_main_out]concat=n=2:v=1:a=1[v][a]")

        filter_str = "; ".join(parts)
        cmd = ["ffmpeg", "-y", "-threads", "0", "-sws_flags", "lanczos"]
        cmd += cmd_inputs
        # +faststart: moov-box শুরুতে থাকে → মোবাইলে/p্রিভিউতে সাথে সাথে চলে,
        # পুরো ফাইল ডাউনলোডের জন্য অপেক্ষা করতে হয় না (মোবাইলে "স্ট্রেস" কমে)
        cmd += ["-filter_complex", filter_str, "-map", "[v]", "-map", "[a]",
                "-c:a", "aac", "-movflags", "+faststart", "-aspect", _ASPECT]
        if has_bgm:
            cmd += ["-shortest"]
        cmd += ["-c:v", enc] + enc_args + [output_path]
        return cmd

    def build_command(enc, enc_args):
        """Build command without thumbnail (or delegate to thumb builder)."""
        if has_thumb:
            return build_filter_with_thumb(enc, enc_args)

        avatar_sz = 220 if sq else 300
        # ── No-thumbnail path (unchanged logic) ────────────────────────────
        # v_filter / a_filter are only used here
        vf_parts = []
        if sq:
            v_main = (
                f"[{main_idx}:v]{bars_prefix}hflip,eq=contrast={rand_contrast}:brightness={rand_brightness}:saturation={rand_saturation},"
                f"colorbalance=rs={rand_rs}:gs={rand_gs}:bs={rand_bs}:rm={rand_rm}:gm={rand_gm}:bm={rand_bm}:rh={rand_rh}:gh={rand_gh}:bh={rand_bh},"
                f"{_up_sharp}unsharp=7:7:1.2:7:7:1.2,setpts=PTS/{speed_factor:.4f},"
                f"{track_crop_chain(face_cmd_prefix, is_short=sq)},{beauty_filter()}"
                f"{title_overlay}"
            )
        else:
            # High-level copyright bypass visual canvas layout for long compilation videos (4K HD output with face correction, static stable rendering)
            v_main = (
                f"[{main_idx}:v]{bars_prefix}hflip,{_up_sharp}unsharp=7:7:1.2:7:7:1.2,eq=contrast={rand_contrast}:brightness={rand_brightness}:saturation={rand_saturation},"
                f"hue=h=-6:s=1.08,colorbalance=rs={rand_rs}:gs={rand_gs}:bs={rand_bs}:rm={rand_rm}:gm={rand_gm}:bm={rand_bm}:rh={rand_rh}:gh={rand_gh}:bh={rand_bh},"
                f"setpts=PTS/{speed_factor:.4f},"
                f"{track_crop_chain(face_cmd_prefix, is_short=sq, out_w=_LW, out_h=_LH)},"
                f"{beauty_filter()},"
                f"drawtext=text='{watermark_text}':x=200:y=h-260:fontsize=68:fontcolor=white:bordercolor=black:borderw=5:fontfile='{f_english}',"
                f"drawtext=text='On My YouTube Channel':x=200:y=h-180:fontsize=44:fontcolor=yellow:bordercolor=black:borderw=4:fontfile='{f_english}'"
                f"{title_overlay}"
            )
            
        vf_parts.append(f"{v_main}[v_raw]")
        current_v = "[v_raw]"
        
        if has_avatar and os.environ.get("SHOW_AVATAR", "0") == "1":
            r = avatar_sz // 2
            pad = 60 if sq else 100
            vf_parts.append(f"[{avatar_idx}:v]scale={avatar_sz}:{avatar_sz},format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(hypot(X-{r},Y-{r}),{r}),255,0)'[avatar_round]")
            vf_parts.append(f"{current_v}[avatar_round]overlay=x={pad}:y={pad}[v_avatar]")
            current_v = "[v_avatar]"
            
        vf_parts.append(f"{current_v}format=yuv420p[v]")
        no_thumb_vf = "; ".join(vf_parts)

        if srt_path and os.path.exists(srt_path):
            escaped_srt = srt_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
            margin = 600 if sq else 80
            font_sz = 64 if sq else 24
            no_thumb_vf = no_thumb_vf.replace("[v]", "[v_nosub]")
            no_thumb_vf += f"; [v_nosub]subtitles='{escaped_srt}':force_style='Alignment=2,MarginV={margin},OutlineColour=&H000000,BorderStyle=3,Outline=3,Shadow=0,Fontname=Arial,Fontsize={font_sz},PrimaryColour=&H00FFFF'[v]"

        if sq:
            audio_eq_no_thumb = (
                f"[{main_idx}:a]afftdn=noise_reduction=10,aresample=44100,"
                f"highpass=f=200,lowpass=f=3500,"
                f"equalizer=f=120:width_type=h:width=50:g=2.0,equalizer=f=3000:width_type=h:width=1000:g=2.0,"
                f"acompressor=threshold=-15dB:ratio=3:attack=5:release=50,{_pitch_part}"
                f"asetpts=N/SR/TB,atempo={tempo_factor:.4f},volume={_dial_vol}"
            )
            bgm_vol_val = 0.28
        else:
            audio_eq_no_thumb = (
                f"[{main_idx}:a]afftdn=noise_reduction=10,aresample=44100,"
                f"highpass=f=200,lowpass=f=3500,"
                f"equalizer=f=120:width_type=h:width=50:g=2.0,equalizer=f=3000:width_type=h:width=1000:g=2.0,"
                f"acompressor=threshold=-15dB:ratio=3:attack=5:release=50,{_pitch_part}"
                f"asetpts=N/SR/TB,atempo={tempo_factor:.4f},volume={_dial_vol}"
            )
            bgm_vol_val = 0.28

        if has_bgm and has_audio:
            parts_nt = []
            parts_nt.append(f"{audio_eq_no_thumb}[a_eq]")
            current_a = "[a_eq]"
            
            if has_intro:
                parts_nt.append(f"[{intro_idx}:a]asetpts=N/SR/TB,volume=1.8[intro_vol]")
                parts_nt.append(f"{current_a}[intro_vol]amix=inputs=2:duration=first:normalize=0[diag_intro]")
                current_a = "[diag_intro]"
                
            if has_narration:
                # (একই ফিক্স — থাম্বনেইল-ছাড়া পথ)
                parts_nt.append(f"[{narration_idx}:a]asetpts=N/SR/TB,volume=1.5[narr_vol]")
                _orig_vol2 = float(os.environ.get("KEEP_ORIG_AUDIO_VOL", "0") or 0)
                parts_nt.append(f"{current_a}volume={_orig_vol2}[orig_bg]")
                parts_nt.append(f"[orig_bg][narr_vol]amix=inputs=2:duration=first:normalize=0[diag_narr]")
                current_a = "[diag_narr]"
                
            if has_outro:
                parts_nt.append(f"[{outro_idx}:a]asetpts=N/SR/TB,adelay={delay_ms}|{delay_ms},volume=1.8[outro_vol]")
                parts_nt.append(f"{current_a}[outro_vol]amix=inputs=2:duration=first:normalize=0[diag_outro]")
                current_a = "[diag_outro]"
                
            parts_nt.append(f"[{bgm_idx}:a]asetpts=N/SR/TB,volume={bgm_vol_val}[bgm_vol]")
            parts_nt.append(f"{current_a}[bgm_vol]amix=inputs=2:duration=first[a]")
            no_thumb_af = "; ".join(parts_nt)
        elif has_audio:
            parts_nt = []
            parts_nt.append(f"{audio_eq_no_thumb}[a_eq]")
            current_a = "[a_eq]"
            
            if has_intro:
                parts_nt.append(f"[{intro_idx}:a]asetpts=N/SR/TB,volume=1.8[intro_vol]")
                parts_nt.append(f"{current_a}[intro_vol]amix=inputs=2:duration=first:normalize=0[diag_intro]")
                current_a = "[diag_intro]"
                
            if has_narration:
                parts_nt.append(f"[{narration_idx}:a]asetpts=N/SR/TB,volume=1.5[narr_vol]")
                parts_nt.append(f"{current_a}volume=0.35[orig_bg]")
                parts_nt.append(f"[orig_bg][narr_vol]amix=inputs=2:duration=first:normalize=0[diag_narr]")
                current_a = "[diag_narr]"
                
            if has_outro:
                parts_nt.append(f"[{outro_idx}:a]asetpts=N/SR/TB,adelay={delay_ms}|{delay_ms},volume=1.8[outro_vol]")
                parts_nt.append(f"{current_a}[outro_vol]amix=inputs=2:duration=first:normalize=0[diag_outro]")
                current_a = "[diag_outro]"
                
            parts_nt.append(f"{current_a}acopy[a]")
            no_thumb_af = "; ".join(parts_nt)
        elif has_bgm:
            no_thumb_af = f"[{bgm_idx}:a]asetpts=N/SR/TB,volume=0.80[a]"
        else:
            no_thumb_af = None

        cmd = ["ffmpeg", "-y", "-threads", "0", "-sws_flags", "lanczos"]
        cmd += cmd_inputs
        if no_thumb_af:
            cmd += ["-filter_complex", f"{no_thumb_vf};{no_thumb_af}", "-map", "[v]", "-map", "[a]", "-c:a", "aac", "-movflags", "+faststart", "-aspect", _ASPECT]
            if has_bgm:
                cmd += ["-shortest"]
        else:
            cmd += ["-filter_complex", no_thumb_vf, "-map", "[v]", "-movflags", "+faststart", "-aspect", _ASPECT]
        cmd += ["-c:v", enc] + enc_args + [output_path]
        return cmd

    def build_command_no_thumb(enc, enc_args):
        """Fallback: same pipeline with the thumbnail input disabled.

        The unified thumb filter_complex (thumbnail concat + main video) can
        fail on some streams/encoders; this re-runs the no-thumb branch of
        build_command instead of it.
        """
        nonlocal has_thumb
        saved, has_thumb = has_thumb, False
        try:
            return build_command(enc, enc_args)
        finally:
            has_thumb = saved

    def build_command_bare(enc, enc_args):
        """Absolute minimum fallback: just speed + flip, no BGM, no thumb."""
        if sq:
            v_f = (
                f"[0:v]hflip,setpts=PTS/{speed_factor:.4f},"
                f"{track_crop_chain(face_cmd_prefix, is_short=sq)},{beauty_filter()}[v]"
            )
        else:
            # High-level copyright bypass visual canvas layout for long compilation videos (4K HD output with face correction, static stable rendering)
            v_f = (
                f"[0:v]hflip,unsharp=5:5:0.8:5:5:0.8,eq=contrast={rand_contrast}:brightness={rand_brightness}:saturation={rand_saturation},"
                f"hue=h=-6:s=1.08,colorbalance=rs={rand_rs}:gs={rand_gs}:bs={rand_bs}:rm={rand_rm}:gm={rand_gm}:bm={rand_bm}:rh={rand_rh}:gh={rand_gh}:bh={rand_bh},"
                f"setpts=PTS/{speed_factor:.4f},"
                f"{track_crop_chain(face_cmd_prefix, is_short=sq, out_w=_LW, out_h=_LH)},"
                f"{beauty_filter()}[v]"
            )

        cmd = ["ffmpeg", "-y", "-threads", "0",
               "-i", input_path]
        if has_audio:
            if sq:
                a_f_bare = (
                    f"[0:a]afftdn=noise_reduction=10,aresample=44100,"
                    f"equalizer=f=120:width_type=h:width=50:g=2.0,"
                    f"equalizer=f=3000:width_type=h:width=1000:g=2.0,"
                    f"acompressor=threshold=-15dB:ratio=3:attack=5:release=50,"
                    f"{_pitch_part}asetpts=N/SR/TB,"
                    f"atempo={tempo_factor:.4f},volume=1.20[a]"
                )
            else:
                a_f_bare = (
                    f"[0:a]afftdn=noise_reduction=10,aresample=44100,"
                    f"equalizer=f=120:width_type=h:width=50:g=2.0,"
                    f"equalizer=f=3000:width_type=h:width=1000:g=2.0,"
                    f"acompressor=threshold=-15dB:ratio=3:attack=5:release=50,"
                    f"{_pitch_part}asetpts=N/SR/TB,"
                    f"atempo={tempo_factor:.4f},volume=1.20[a]"
                )
            cmd += ["-filter_complex", f"{v_f};{a_f_bare}", "-map", "[v]", "-map", "[a]", "-c:a", "aac", "-movflags", "+faststart", "-aspect", _ASPECT]
        else:
            cmd += ["-filter_complex", v_f, "-map", "[v]", "-movflags", "+faststart", "-aspect", _ASPECT]
        cmd += ["-c:v", enc] + enc_args + [output_path]
        return cmd
 

    # ── Try all fallback levels ────────────────────────────────────────────────
    fallback_levels = [
        ("Full pipeline",          lambda: build_command(encoder, encoder_args)),
        ("libx264 full",           lambda: build_command("libx264", ["-preset", "veryfast", "-crf", "18"])),
        ("libx264 no-thumbnail",   lambda: build_command_no_thumb("libx264", ["-preset", "veryfast", "-crf", "18"])),
        ("libx264 bare-minimum",   lambda: build_command_bare("libx264", ["-preset", "veryfast", "-crf", "18"])),
    ]

    try:
        last_err = None
        for level_name, cmd_fn in fallback_levels:
            cmd = cmd_fn()
            print(f"[FFmpeg] Trying: {level_name}")
            try:
                subprocess.run(cmd, check=True)
                print(f"[FFmpeg] ✓ Success with: {level_name}")
                if level_name != "Full pipeline":
                    # Reset encoder cache so next run tries hardware again
                    global _encoder_cache
                    _encoder_cache = None
                # শেষ গার্ড: কোনো কারণে বার থেকে গেলে নিজেই কেটে ঠিক করি
                try:
                    strip_bars(output_path, target=(_LW, _LH))
                except Exception as _e:
                    print(f"[bars] যাচাই ব্যর্থ (উপেক্ষা): {_e}")
                return output_path
            except subprocess.CalledProcessError as e:
                last_err = e
                print(f"[FFmpeg] ✗ Failed ({level_name}, status {e.returncode}). Trying next fallback...")
                # Remove broken output if it exists
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except Exception:
                        pass

        raise RuntimeError(f"All FFmpeg fallback levels failed. Last error: {last_err}")
    finally:
        if face_cmd_file and os.path.exists(face_cmd_file):
            try:
                os.remove(face_cmd_file)
            except Exception:
                pass

# ── শেষ গার্ড: রেন্ডারের পরেও বার আছে কিনা যাচাই + নিজেই ঠিক করা ──────────
def detect_bars(path, samples=10, size=96, thresh=10, min_frac=0.012):
    """পোড়া বার মাপি — অনেক ফ্রেমের **সর্বোচ্চ** উজ্জ্বলতা দেখে।

    কেন এভাবে: এক ফ্রেমে অন্ধকার দৃশ্য থাকতেই পারে; কিন্তু আসল বার সব
    ফ্রেমেই কালো থাকে। তাই max-over-time ব্যবহার করলে ভুল সনাক্ত হয় না।
    """
    import subprocess as _sp, shutil as _sh
    try:
        import numpy as _np
    except Exception:
        return None
    w, h = probe_size(path)
    if not w or not h:
        return None
    ff = _sh.which("ffmpeg") or "ffmpeg"
    try:
        raw = _sp.run([ff, "-v", "quiet", "-i", str(path),
                       "-vf", f"fps=1/2,scale={size}:{size}",
                       "-frames:v", str(samples), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                      capture_output=True, timeout=120).stdout
    except Exception:
        return None
    a = _np.frombuffer(raw, dtype=_np.uint8)
    n = a.size // (size * size)
    if n < 1:
        return None
    st = a[:n * size * size].reshape(n, size, size)
    rows = st.max(axis=(0, 2))
    cols = st.max(axis=(0, 1))

    def _lead(m):
        k = 0
        while k < len(m) and m[k] < thresh:
            k += 1
        return k

    def _trail(m):
        k = 0
        while k < len(m) and m[-1 - k] < thresh:
            k += 1
        return k

    t, b, l, r = _lead(rows), _trail(rows), _lead(cols), _trail(cols)
    tp, bp = round(t / size * h), round(b / size * h)
    lp, rp = round(l / size * w), round(r / size * w)
    if (tp + bp) < h * min_frac and (lp + rp) < w * min_frac:
        return None
    return w, h, tp, bp, lp, rp


def strip_bars(path, target=None):
    """আউটপুটে বার থাকলে কেটে ফ্রেম পুরো ভরাট করি (ক্রপ + সেন্টার জুম)।

    True ফেরত দেয় যদি ফাইল ঠিক করতে হয়েছে।
    """
    if os.environ.get("FINAL_BAR_GUARD", "1") == "0":
        return False
    info = detect_bars(path)
    if not info:
        return False
    w, h, tp, bp, lp, rp = info
    cw, ch = w - lp - rp, h - tp - bp
    if cw < w * 0.5 or ch < h * 0.5:      # ভুল সনাক্তকরণ — হাত দিই না
        return False
    tw, th = target or (w, h)
    out = str(path) + ".nobar.mp4"
    vf = (f"crop={cw}:{ch}:{lp}:{tp},"
          f"scale={tw}:{th}:force_original_aspect_ratio=increase:flags=lanczos,"
          f"crop={tw}:{th},setsar=1")
    import shutil as _sh
    ff = _sh.which("ffmpeg") or "ffmpeg"
    print(f"[bars] আউটপুটে বার মিলেছে (উপর {tp}px, নিচ {bp}px, বাঁ {lp}px, ডান {rp}px) — কেটে ভরাট করছি")
    try:
        subprocess.run([ff, "-y", "-i", str(path), "-vf", vf,
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                        "-c:a", "copy", "-movflags", "+faststart", out],
                       check=True, capture_output=True)
        os.replace(out, str(path))
        return True
    except Exception as e:
        print(f"[bars] ঠিক করা গেল না: {e}")
        try:
            os.remove(out)
        except Exception:
            pass
        return False

def compress_video_if_needed(input_path, max_size_mb=None):
    """
    ভিডিও কম্প্রেশন — **ডিফল্টে বন্ধ (আনলিমিটেড)**।

    কারণ: Telegram Bot API-তে বটের আপলোড সীমা ৫০ MB; ওই সীমার নিচে আনতে হলে
    রেজোলিউশন/বিটরেট কমাতে হয় — তখন ১০৮০ আর থাকে না। তাই এখন:
      MAX_VIDEO_MB = 0 (ডিফল্ট) → কোনো কম্প্রেশন নেই, অরিজিনাল কোয়ালিটি
      MAX_VIDEO_MB = 49        → আগের আচরণ (৫০MB-র নিচে আনার চেষ্টা)
    """
    set_ffmpeg_path()

    if max_size_mb is None:
        try:
            max_size_mb = float(os.environ.get("MAX_VIDEO_MB", "0"))
        except ValueError:
            max_size_mb = 0.0
    if max_size_mb <= 0:
        mb = os.path.getsize(input_path) / (1024 * 1024)
        print(f"[compress] আনলিমিটেড মোড — কম্প্রেশন বাদ ({mb:.1f} MB, ফুল কোয়ালিটি)")
        return input_path

    file_size = os.path.getsize(input_path)
    file_size_mb = file_size / (1024 * 1024)
    print(f"Video size before compression: {file_size_mb:.2f} MB")
    
    if file_size_mb <= max_size_mb:
        return input_path
        
    print(f"Video size {file_size_mb:.2f} MB exceeds {max_size_mb} MB limit. Compressing...")
    
    # Get video details using VideoFileClip
    duration = 600 # default
    is_vertical = False
    is_square = False
    try:
        clip = VideoFileClip(input_path)
        duration = clip.duration
        w, h = clip.size
        if abs(w - h) < 5:
            is_square = True
        else:
            is_vertical = (w < h)
        clip.close()
    except Exception as e:
        print(f"Error getting clip details: {e}")
        
    # Calculate target bitrate: total bits / duration
    target_total_bitrate = (max_size_mb * 1024 * 1024 * 8) / duration # bits per second
    audio_bitrate = 64 * 1024 # 64kbps
    video_bitrate = int(target_total_bitrate - audio_bitrate)
    
    # Keep video_bitrate in acceptable bounds (allow high quality up to 4 Mbps for short videos/shorts)
    video_bitrate = max(200000, min(4000000, video_bitrate))
    
    output_path = input_path.replace(".mp4", "_compressed.mp4")
    
    encoder, encoder_args = get_best_encoder()
    
    # Clean encoder_args to remove quality overriding parameters (-q:v, -q, -crf) for target bitrate mode
    clean_encoder_args = []
    i = 0
    while i < len(encoder_args):
        arg = encoder_args[i]
        if arg in ["-q:v", "-q", "-crf"]:
            i += 2
        else:
            clean_encoder_args.append(arg)
            i += 1
            
    # ── রেজোলিউশন: আর কখনো ১০৮০-র নিচে নামবে না ─────────────────────────
    # আগে কম বিটরেটে ৪৮০p/৭২০p-তে নামিয়ে দিত → ডাউনলোড করা ভিডিও ১০৮০ থাকত না।
    # এখন রেজোলিউশন **সবসময় ১০৮০** রাখি, কমে শুধু বিটরেট।
    # দরকার হলে MIN_1080=0 দিয়ে পুরোনো আচরণ ফেরানো যায়।
    min_1080 = os.environ.get("MIN_1080", "1") != "0"
    if min_1080:
        if is_square:
            scale_size = "1080x1080"
        else:
            scale_size = "1080x1920" if is_vertical else "1920x1080"
        if video_bitrate < 900000:
            print(f"[compress] ⚠️ {video_bitrate//1000} kbps — ১০৮০ রাখা হচ্ছে, "
                  f"তাই কিছুটা ব্লকি হতে পারে (দৈর্ঘ্য কমালে ভালো)")
    elif is_square:
        if video_bitrate < 400000:
            scale_size = "480x480"
        elif video_bitrate < 700000:
            scale_size = "720x720"
        elif video_bitrate < 1200000:
            scale_size = "1080x1080"
        else:
            scale_size = "1440x1440"
    else:
        if video_bitrate < 400000:
            scale_size = "360x640" if is_vertical else "640x360"
        elif video_bitrate < 700000:
            scale_size = "480x854" if is_vertical else "854x480"
        elif video_bitrate < 1200000:
            scale_size = "720x1280" if is_vertical else "1280x720"
        else:
            scale_size = "1080x1920" if is_vertical else "1920x1080"
    
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-b:v", f"{video_bitrate}",
        "-s", scale_size,
        "-b:a", "64k",
        "-c:v", encoder,
    ] + clean_encoder_args + [
        "-c:a", "aac",
        output_path
    ]
    
    try:
        subprocess.run(cmd, check=True)
    except Exception as e:
        if encoder != "libx264":
            print(f"[Warning] Compression failed with encoder '{encoder}': {e}. Retrying with libx264...")
            global _encoder_cache
            _encoder_cache = ("libx264", ["-preset", "veryfast", "-crf", "18"])
            encoder, encoder_args = _encoder_cache
            clean_encoder_args = ["-preset", "veryfast", "-crf", "18"]
            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-b:v", f"{video_bitrate}",
                "-s", scale_size,
                "-b:a", "64k",
                "-c:v", encoder,
            ] + clean_encoder_args + [
                "-c:a", "aac",
                output_path
            ]
            try:
                subprocess.run(cmd, check=True)
            except Exception as fallback_err:
                print(f"Compression fallback failed: {fallback_err}")
                return input_path
        else:
            print(f"Compression failed: {e}")
            return input_path

    if os.path.exists(output_path):
        new_size = os.path.getsize(output_path) / (1024 * 1024)
        print(f"Compressed video size: {new_size:.2f} MB")
        os.remove(input_path)
        os.rename(output_path, input_path)
        return input_path
        
    return input_path

def mix_bgm_on_merged_video(video_path, output_path, bgm_dir="assets/audio", preferred_bgm=None):
    """
    Overlay a background music track on a video file that already contains dialogue.
    If preferred_bgm is provided, it is used instead of a random track.
    The original audio (dialogue) is kept at 100% volume, and BGM is mixed at 22% volume.
    """
    import shutil
    import random
    set_ffmpeg_path()
    
    bgm_path = None
    if preferred_bgm:
        potential_path = os.path.join(bgm_dir, preferred_bgm)
        if os.path.exists(potential_path):
            bgm_path = potential_path
            
    if not bgm_path:
        bgm_files = _bgm_candidates(bgm_dir)
        bgm_path = random.choice(bgm_files) if bgm_files else None
        
    if not bgm_path or not os.path.exists(bgm_path):
        shutil.copy(video_path, output_path)
        return output_path
        
    # ── অরিজিনাল কণ্ঠ অটুট: হালকা ইকিউ (২০০–৩৫০০ Hz ব্যান্ড-পাস কণ্ঠকে "টেলিফোন"
    #    করে ফেলে) আর BGM আরো নিচে — যাতে শিল্পীর নিজের কথা স্পষ্ট শোনা যায়।
    voice_original = os.environ.get("VOICE_ORIGINAL", "1") != "0"
    mute_dialogue = os.environ.get("MUTE_DIALOGUE", "0") == "1"
    if mute_dialogue:
        # কণ্ঠ বাদ → মূল অডিও চুপ, শুধু গানই শোনা যাবে
        orig_chain = "[0:a]volume=0[orig]"
        bgm_vol = os.environ.get("BGM_VOL_MUTE", "0.85")
    elif voice_original:
        orig_chain = ("[0:a]afftdn=noise_reduction=6,aresample=44100,highpass=f=80,"
                      "lowpass=f=11000,equalizer=f=120:width_type=h:width=50:g=1.0,"
                      "asetpts=N/SR/TB,volume=1.15[orig]")
        bgm_vol = os.environ.get("BGM_VOL", "0.15")
    else:
        orig_chain = ("[0:a]afftdn=noise_reduction=10,aresample=44100,highpass=f=200,"
                      "lowpass=f=3500,equalizer=f=120:width_type=h:width=50:g=2.0,"
                      "equalizer=f=3000:width_type=h:width=1000:g=2.0,"
                      "asetpts=N/SR/TB,volume=1.35[orig]")
        bgm_vol = os.environ.get("BGM_VOL", "0.28")
    # ── নাটকের নিজের BGM বাদ (AI সোর্স সেপারেশন) ───────────────────────────
    # সোর্স ভিডিওর ভেতরে নাটকের নিজের মিউজিক বাঁধা থাকে; ব্যবহারকারী চান শুধু
    # কণ্ঠ + তাঁর নিজের গান। CLEAN_DIALOGUE=1 হলে Demucs দিয়ে কণ্ঠ আলাদা করে
    # সেটাই মিক্স করি (না হলে আগের মতোই আসল অডিও)।
    dlg_in = None
    dlg_idx = 0
    _clean_tmp = None
    try:
        from dialogue_clean import extract_vocals, enabled as _clean_enabled
        if _clean_enabled() and not mute_dialogue:
            print("[clean-dialogue] নাটকের মিউজিক বাদ দিতে কণ্ঠ আলাদা করা হচ্ছে...")
            _clean_tmp = __import__("tempfile").mkdtemp(prefix="dlg_")
            dlg_in = extract_vocals(video_path, workdir=_clean_tmp)
            if dlg_in:
                dlg_idx = 1  # BGM এর আগে ইনপুট
    except Exception as _e:
        print(f"[clean-dialogue] বাদ (উপেক্ষা): {_e}")
        dlg_in = None

    if dlg_in:
        # আলাদা করা কণ্ঠ থেকে মিক্স (আসল অডিওর নাটক-মিউজিক আর আসে না)
        if mute_dialogue:
            orig_chain = f"[{dlg_idx}:a]volume=0[orig]"
        elif voice_original:
            orig_chain = (f"[{dlg_idx}:a]aresample=44100,highpass=f=70,"
                          "lowpass=f=13000,equalizer=f=120:width_type=h:width=50:g=1.0,"
                          f"asetpts=N/SR/TB,volume={os.environ.get('CLEAN_VOICE_VOL','1.6')}[orig]")
        else:
            orig_chain = (f"[{dlg_idx}:a]aresample=44100,highpass=f=150,lowpass=f=6000,"
                          "equalizer=f=120:width_type=h:width=50:g=2.0,"
                          f"asetpts=N/SR/TB,volume={os.environ.get('CLEAN_VOICE_VOL','1.8')}[orig]")
        _bgm_i = dlg_idx + 1
        audio_filter = (f"{orig_chain};[{_bgm_i}:a]asetpts=N/SR/TB,volume={bgm_vol}[bgm];"
                        f"[orig][bgm]amix=inputs=2:duration=first[mix];"
                        "[mix]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[a]")
        cmd = ["ffmpeg", "-y", "-i", video_path, "-i", dlg_in,
               "-stream_loop", "-1", "-ss", "30", "-i", bgm_path,
               "-filter_complex", audio_filter,
               "-map", "0:v", "-map", "[a]",
               "-c:v", "copy", "-c:a", "aac", "-shortest", output_path]
    else:
        audio_filter = (f"{orig_chain};[1:a]asetpts=N/SR/TB,volume={bgm_vol}[bgm];"
                        f"[orig][bgm]amix=inputs=2:duration=first[mix];"
                        "[mix]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[a]")

        # High-quality EQ/compression mixing for flawless crystal clear voice
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-stream_loop", "-1", "-ss", "30", "-i", bgm_path,
            "-filter_complex", audio_filter,
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac",
            "-shortest",
            output_path
        ]
    print(f"Mixing BGM on merged video: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    finally:
        if _clean_tmp:
            __import__("shutil").rmtree(_clean_tmp, ignore_errors=True)
    return output_path


def ensure_snow_overlay():
    import os
    import math
    import numpy as np
    from PIL import Image, ImageDraw
    
    os.makedirs("assets", exist_ok=True)
    snow_path = "assets/snow_overlay.mp4"
    if os.path.exists(snow_path):
        return snow_path
        
    print("Generating snow overlay asset...")
    from moviepy import VideoClip
    import imageio_ffmpeg
    
    w, h = 1080, 1920
    duration = 15.0
    fps = 24
    
    def make_frame(t):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)
        
        for idx in range(35): 
            seed_x = (idx * 17.31) % 1.0
            seed_y = (idx * 29.57) % 1.0
            seed_speed = (idx * 13.93) % 1.0
            seed_radius = (idx * 7.19) % 1.0
            seed_phase = (idx * 3.47) % 1.0
            
            radius = int(5 + seed_radius * 12)  
            x_center = seed_x * w
            speed = 90 + seed_speed * 110       
            
            y = (seed_y * h + speed * t) % h
            sway = 25 * math.sin(1.5 * t + seed_phase * 6.28)
            x = (x_center + sway) % w
            
            alpha_val = int(100 + seed_speed * 125)
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(255, 255, 255, alpha_val))
            
            glow_rad = radius * 2
            draw.ellipse([x - glow_rad, y - glow_rad, x + glow_rad, y + glow_rad], fill=(255, 255, 255, int(alpha_val * 0.25)))
            
        return np.array(img.convert("RGB"))
        
    clip = VideoClip(make_frame, duration=duration)
    
    clip.write_videofile(
        snow_path,
        fps=fps,
        codec="libx264",
        audio=False,
        logger=None,
        ffmpeg_params=["-pix_fmt", "yuv420p"]
    )
    clip.close()
    return snow_path


def extract_audio_from_video(video_path, audio_path):
    """Extract lightweight mono audio from a video using ffmpeg."""
    set_ffmpeg_path()
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-ab", "64k",
        "-f", "mp3",
        audio_path
    ]
    print(f"[Audio Extract] Running: {' '.join(cmd)}")
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return audio_path


def generate_english_srt_from_audio(audio_path, category=None):
    """
    Upload the audio file to Google Gemini, transcribe/translate the Bengali speech to English,
    and return subtitles in valid SRT format.
    """
    from gemini_helper import client, DEFAULT_MODEL
    import time
    
    if not client:
        print("[Gemini Translation] Client not available.")
        return None
        
    category_str = f" ({category})" if category else ""
    prompt = f"""
    You are a professional video translation assistant.
    You are given an audio file containing Bengali speech{category_str}.
    
    Your task is to:
    1. Transcribe the Bengali speech and translate it into clear, natural, and idiomatic English.
    2. Output standard SRT (SubRip Subtitle) format.
    3. Ensure the subtitle timestamps perfectly align with the speech in the audio.
    4. Keep subtitle lines short and readable (max 40 characters per line, up to 2 lines per subtitle block).
    
    Output ONLY valid SRT format. Do not include markdown code block syntax (like ```srt or ```), explanations, or notes.
    """
    
    print(f"[Gemini Translation] Uploading audio file to Gemini: {audio_path}")
    uploaded_file = None
    try:
        uploaded_file = client.files.upload(file=audio_path)
        print(f"[Gemini Translation] File uploaded successfully as: {uploaded_file.name}. Waiting for processing...")
        
        # Wait for file processing if needed (normally fast for audio)
        time.sleep(2)
        
        print("[Gemini Translation] Requesting transcription and translation...")
        response = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=[uploaded_file, prompt]
        )
        
        srt_text = response.text.strip()
        # Clean up any markdown block wrappers if Gemini ignored the instruction
        if "```srt" in srt_text:
            srt_text = srt_text.split("```srt")[1].split("```")[0].strip()
        elif "```" in srt_text:
            srt_text = srt_text.split("```")[1].split("```")[0].strip()
            
        print(f"[Gemini Translation] Received subtitle text. Length: {len(srt_text)} characters.")
        return srt_text
        
    except Exception as e:
        print(f"[Gemini Translation] Error: {e}")
        return None
        
    finally:
        # Crucial: clean up the uploaded file from Gemini server to prevent quota/resource issues
        if uploaded_file:
            try:
                client.files.delete(name=uploaded_file.name)
                print(f"[Gemini Translation] Cleaned up file from Gemini server: {uploaded_file.name}")
            except Exception as delete_err:
                print(f"[Gemini Translation] Failed to delete file {uploaded_file.name}: {delete_err}")



