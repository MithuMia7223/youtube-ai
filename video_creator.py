"""
video_creator.py

Creates AI-powered faceless videos using:
  - Microsoft Edge Neural TTS (edge-tts) for clear, natural voice
  - Gemini / Imagen API for scene-by-scene AI images
  - Pexels as image fallback
  - moviepy to stitch images + audio into a final video

Dependencies:
  edge-tts, moviepy, Pillow, requests, google-genai
"""
import os
import re
import time
import textwrap
import tempfile
import requests
from typing import Callable
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

_encoder_cache = None

def get_best_encoder():
    """Determine the best available video encoder (hardware accelerated if possible)."""
    global _encoder_cache
    if _encoder_cache is not None:
        return _encoder_cache
        
    try:
        import imageio_ffmpeg
        import subprocess
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        res = subprocess.run([ffmpeg_exe, "-encoders"], capture_output=True, text=True, check=True)
        if "h264_videotoolbox" in res.stdout:
            _encoder_cache = "h264_videotoolbox"
            print("[INFO] Hardware acceleration enabled: Using h264_videotoolbox")
        else:
            _encoder_cache = "libx264"
            print("[INFO] Hardware acceleration not found: Using libx264")
    except Exception as e:
        print(f"[Warning] Failed to check encoders: {e}. Defaulting to libx264.")
        _encoder_cache = "libx264"
        
    return _encoder_cache

# ── Voice definitions (Microsoft Edge Neural TTS) ────────────────────────────
# Full neural voice list: https://aka.ms/edge-tts-voices
VOICES = {
    "en_female":   "en-US-JennyNeural",      # স্পষ্ট, প্রাকৃতিক মহিলা কণ্ঠ
    "en_male":     "en-US-GuyNeural",         # পরিষ্কার পুরুষ কণ্ঠ
    "en_aria":     "en-US-AriaNeural",        # উষ্ণ, অভিব্যক্তিময় কণ্ঠ
    "en_davis":    "en-US-DavisNeural",       # গভীর পুরুষ কণ্ঠ
    "bn_female":   "bn-BD-NabanitaNeural",   # বাংলাদেশী বাংলা মহিলা
    "bn_male":     "bn-BD-PradeepNeural",    # বাংলাদেশী বাংলা পুরুষ
    "hi_female":   "hi-IN-SwaraNeural",      # হিন্দি মহিলা কণ্ঠ
    "hi_male":     "hi-IN-MadhurNeural",     # হিন্দি পুরুষ কণ্ঠ
}

VOICE_LABELS = {
    "en_female":   "🇺🇸 English Female (Jenny)",
    "en_male":     "🇺🇸 English Male (Guy)",
    "en_aria":     "🇺🇸 English Female (Aria)",
    "en_davis":    "🇺🇸 English Male Deep (Davis)",
    "bn_female":   "🇧🇩 Bangla Female (Nabanita)",
    "bn_male":     "🇧🇩 Bangla Male (Pradeep)",
    "hi_female":   "🇮🇳 Hindi Female (Swara)",
    "hi_male":     "🇮🇳 Hindi Male (Madhur)",
}

DEFAULT_VOICE = "bn_female"


def _progress(msg: str, cb: Callable | None):
    if cb:
        try:
            cb(msg)
        except Exception:
            pass


def clean_tts_text(text: str) -> str:
    """
    Cleans the script text to be spoken by neural TTS:
    - Removes parenthetical stage directions like (কান্নাজড়িত কণ্ঠে) or [screaming]
    - Removes emojis
    - Removes speaker prefixes like 'HERO:', 'HEROINE:', 'রাখাল:'
    - Cleans duplicate whitespace
    """
    # 1. Remove text inside parentheses, brackets, or braces
    text = re.sub(r'[\(\[（【\{].*?[\)\]）】\}]', '', text)
    
    # 2. Remove emojis and keep only Bengali, English, numbers, basic punctuation
    text = re.sub(r'[^\w\s\u0980-\u09ff.,!?:;\"\'\-।\u0964]', '', text)
    
    # 3. Remove speaker prefixes at start (e.g. 'HERO:', 'রাখাল:')
    text = re.sub(r'^[a-zA-Z\u0980-\u09ff]+\s*:\s*', '', text)
    
    # 4. Clean multiple spaces/newlines
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ── Step 1: Generate Audio ─────────────────────────────────────────────────────
def _generate_audio(text: str, voice_key: str, output_path: str,
                    cb: Callable | None = None) -> str:
    _progress("🎙️ Neural ভয়েসওভার তৈরি হচ্ছে...", cb)

    voice_name = VOICES.get(voice_key, VOICES[DEFAULT_VOICE])
    clean_text = clean_tts_text(text)[:4500].strip()

    # Use edge-tts (Microsoft Neural TTS) — free & very clear
    try:
        import asyncio
        import edge_tts

        async def _tts_async():
            communicate = edge_tts.Communicate(clean_text, voice_name)
            await communicate.save(output_path)

        asyncio.run(_tts_async())
        _progress("✅ Neural ভয়েসওভার সম্পন্ন (Microsoft Edge TTS)", cb)
        return output_path

    except Exception as e:
        _progress(f"⚠️ Edge TTS ব্যর্থ, gTTS দিয়ে চেষ্টা করা হচ্ছে... ({e})", cb)
        # Fallback to gTTS
        try:
            from gtts import gTTS
            lang = "bn" if "bn" in voice_key else ("hi" if "hi" in voice_key else "en")
            tts = gTTS(text=clean_text[:4000], lang=lang)
            tts.save(output_path)
            _progress("✅ ভয়েসওভার সম্পন্ন (gTTS fallback)", cb)
            return output_path
        except Exception as e2:
            raise RuntimeError(f"TTS সম্পূর্ণ ব্যর্থ: {e2}")


# ── Step 2: Split Script into Scenes ───────────────────────────────────
def _split_into_scenes(script: str, max_scenes: int = 8) -> list[dict]:
    """
    Split the narration script into scenes using smart paragraph/sentence splitting.
    Each scene = {"text": "...", "image_path": None}
    """
    # First try paragraph splitting
    paragraphs = [p.strip() for p in script.split("\n\n") if len(p.strip()) > 20]

    if len(paragraphs) < 2:
        # Try single newline splitting
        paragraphs = [p.strip() for p in script.split("\n") if len(p.strip()) > 20]

    if len(paragraphs) < 2:
        # Fall back to sentence-based splitting
        sentences = re.split(r'(?<=[.!?\u0964])\s+', script)
        chunk_size = max(2, len(sentences) // max_scenes)
        paragraphs = [
            " ".join(sentences[i:i+chunk_size])
            for i in range(0, len(sentences), chunk_size)
        ]

    # Limit to max_scenes
    paragraphs = [p for p in paragraphs if p.strip()][:max_scenes]

    scenes = []
    for para in paragraphs:
        scenes.append({
            "text": para.strip(),
            "image_path": None,
        })
    return scenes


def split_script_offline(script: str, default_voice: str, max_scenes: int = 8, is_short: bool = False) -> list[dict]:
    """
    Splits the narration script into scenes by paragraphs/sentences,
    and extracts dialogues with male/female voice mapping to support multi-character speech.
    """
    if is_short:
        # For viral Shorts, split at sentence level to keep the visual pacing extremely fast (pattern interrupt every 2-4 seconds)
        sentences = re.split(r'(?<=[.!?\u0964])\s+', script)
        paragraphs = [s.strip() for s in sentences if len(s.strip()) > 5]
        max_scenes = 15
    else:
        paragraphs = [p.strip() for p in script.split("\n") if len(p.strip()) > 8]
        if not paragraphs:
            paragraphs = [script.strip()]

        if len(paragraphs) < 2:
            # Fall back to sentence-based splitting
            sentences = re.split(r'(?<=[.!?\u0964])\s+', script)
            chunk_size = max(2, len(sentences) // max_scenes)
            paragraphs = [
                " ".join(sentences[i:i+chunk_size])
                for i in range(0, len(sentences), chunk_size)
            ]

    paragraphs = [p for p in paragraphs if p.strip()][:max_scenes]

    # Map voice gender based on default voice key
    voice_gender_map = {
        "bn_female": {"female": "bn_female", "male": "bn_male"},
        "bn_male": {"female": "bn_female", "male": "bn_male"},
        "en_female": {"female": "en_female", "male": "en_male"},
        "en_male": {"female": "en_female", "male": "en_male"},
    }
    gender_map = voice_gender_map.get(default_voice, {"female": "bn_female", "male": "bn_male"})

    scenes = []
    for para in paragraphs:
        dialogues = []
        # Find quotes like "..." or '...' or Bengali quotes “...”
        quotes = re.findall(r'["“]([^"”]+)["”]', para)
        
        if quotes:
            remaining_text = para
            for q in quotes:
                gender = "female"  # default
                
                # Check for male keywords
                male_keywords = ["রাখাল", "শিকারী", "ছেলে", "বাবা", "ভাই", "hunter", "boy", "man", "father", "brother", "he", "his", "him", "shepherd"]
                for kw in male_keywords:
                    if kw in para.lower():
                        gender = "male"
                        break
                
                voice = gender_map["male"] if gender == "male" else gender_map["female"]
                dialogues.append({"text": q.strip(), "voice": voice})
                remaining_text = remaining_text.replace(f'"{q}"', "").replace(f'“{q}”', "")
            
            # Add narrative text if present
            narrative = remaining_text.strip().strip(",").strip("।").strip()
            if narrative and len(narrative) > 5:
                dialogues.insert(0, {"text": narrative, "voice": gender_map["female"]})
        else:
            # Check for speaker name like "রাখাল: আমি যাব।"
            colon_match = re.match(r'^([^:]+):\s*(.+)$', para)
            if colon_match:
                speaker = colon_match.group(1).strip()
                dialogue_text = colon_match.group(2).strip()
                
                gender = "female"
                male_keywords = ["রাখাল", "শিকারী", "ছেলে", "বাবা", "ভাই", "hunter", "boy", "man", "father", "brother", "he", "his", "him", "shepherd"]
                for kw in male_keywords:
                    if kw in speaker.lower():
                        gender = "male"
                        break
                
                voice = gender_map["male"] if gender == "male" else gender_map["female"]
                dialogues.append({"text": dialogue_text, "voice": voice})
            else:
                dialogues.append({"text": para, "voice": default_voice})
                
        scenes.append({
            "text": para,
            "image_path": None,
            "audio_path": None,
            "dialogues": dialogues
        })
    return scenes


# ── Build image prompt using Gemini AI ──────────────────────────────────────
def _build_image_prompt(scene_text: str, topic: str, is_story: bool = False) -> str:
    """
    Use Gemini to convert scene text into a rich visual image prompt.
    Falls back to a simple prompt if Gemini fails.
    """
    is_funny = "funny" in topic.lower() or "comedy" in topic.lower() or "hasnat" in topic.lower() or "পাকনামি" in topic.lower()
    
    if is_funny:
        style_desc = "Highly detailed, expressive comical cartoon style. Characters must have exaggerated, funny, cute expressions (like a funny-looking toddler or baby with a cap)."
    elif is_story:
        style_desc = "A beautiful, detailed, colorful children's storybook cartoon illustration style."
    else:
        style_desc = "Cinematic, professional quality, storytelling style."

    try:
        from google import genai
        client = genai.Client()
        resp = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=(
                f"Convert this story scene into a detailed visual image prompt for AI art generation.\n"
                f"Core Subject/Character: {topic}\n"
                f"Scene Action: {scene_text[:300]}\n\n"
                f"Rules:\n"
                f"- The style must be: {style_desc}\n"
                f"- The main character/subject MUST match the Core Subject: '{topic}' in terms of appearance, type, and style to maintain consistency across scenes.\n"
                f"- Visually describe the action: '{scene_text[:300]}'.\n"
                f"- Character face/upper body MUST be perfectly centered in the frame with clear safe margins around the head so they are not cut off. Face must be clean and extremely clear, highly attractive facial features, sharp focus, expressive emotion, photorealistic, no face blur or distortion.\n"
                f"- Background MUST be softly blurred, beautiful bokeh, cinematic shallow depth of field (f/1.8 aperture, 35mm lens shot).\n"
                f"- Use cinematic color grading with professional warm skin tones and a rich teal and orange color palette.\n"
                f"- Describe specific setting, lighting, mood, and color.\n"
                f"- Keep it under 60 words. No text, no watermarks."
            )
        )
        return resp.text.strip()[:400]
    except Exception:
        # Simple fallback prompt requesting clear, detailed faces
        return (
            f"Cartoon illustration of {topic}. {scene_text[:150]}. "
            f"Crystal clear face and features, vivid colors, professional quality, storytelling style, "
            f"dramatic lighting, no text."
            if is_story else
            f"Cinematic masterpiece still of {topic}, photorealistic, {scene_text[:150]}. "
            f"Crystal clear sharp face and eyes, highly detailed facial features, warm skin tones, "
            f"soft blurred background bokeh, f/1.8 shallow depth of field, "
            f"teal and orange cinematic color grading, vivid colors, professional quality, no face blur, no text."
        )


def _generate_pollinations_ai_image(prompt: str, output_path: str, is_short: bool = True) -> bool:
    """
    Generate ultra-high definition 8K AI image via Pollinations Flux API.
    Guarantees 100% successful generation of sharp face portraits when Imagen is rate-limited.
    """
    import urllib.parse
    w, h = (1080, 1920) if is_short else (1920, 1080)
    encoded_prompt = urllib.parse.quote(prompt)
    models = ["flux", "turbo"]
    
    for m in models:
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={w}&height={h}&nologo=true&model={m}&seed={int(time.time() * 1000) % 100000}"
        try:
            r = requests.get(url, timeout=25)
            if r.status_code == 200 and len(r.content) > 10000:
                with open(output_path, "wb") as f:
                    f.write(r.content)
                return True
        except Exception as e:
            print(f"[Pollinations AI] Model '{m}' failed: {e}")
            continue
    return False


def _generate_did_talking_avatar(image_path: str, audio_path: str, api_key: str, cb: Callable | None = None) -> str | None:
    """
    Calls D-ID API to generate a lip-synced talking avatar video clip.
    """
    import base64
    import time
    
    # D-ID uses Basic Auth: "Basic <base64_encoded_api_key:>"
    encoded_key = base64.b64encode(f"{api_key}:".encode('utf-8')).decode('utf-8')
    headers = {
        "Authorization": f"Basic {encoded_key}"
    }
    
    try:
        # Step 1: Upload Image
        _progress("👤 D-ID: ক্যারেক্টার ইমেজ আপলোড হচ্ছে...", cb)
        with open(image_path, "rb") as f:
            r = requests.post(
                "https://api.d-id.com/images",
                headers=headers,
                files={"image": f},
                timeout=30
            )
        if r.status_code not in [200, 201]:
            raise Exception(f"Image upload failed ({r.status_code}): {r.text}")
        image_url = r.json().get("url")
        
        # Step 2: Upload Audio
        _progress("🎙️ D-ID: ডায়ালগ অডিও আপলোড হচ্ছে...", cb)
        with open(audio_path, "rb") as f:
            r = requests.post(
                "https://api.d-id.com/audios",
                headers=headers,
                files={"audio": f},
                timeout=30
            )
        if r.status_code not in [200, 201]:
            raise Exception(f"Audio upload failed ({r.status_code}): {r.text}")
        audio_url = r.json().get("url")
        
        # Step 3: Trigger Talk generation
        _progress("👄 D-ID: ঠোঁট নাড়ানোর ভিডিও তৈরি শুরু হচ্ছে...", cb)
        payload = {
            "source_url": image_url,
            "script": {
                "type": "audio",
                "audio_url": audio_url
            },
            "config": {
                "fluent": True,
                "pad_audio": "0.0"
            }
        }
        r = requests.post(
            "https://api.d-id.com/talks",
            headers={**headers, "Content-Type": "application/json"},
            json=payload,
            timeout=30
        )
        if r.status_code not in [200, 201]:
            raise Exception(f"Talk trigger failed ({r.status_code}): {r.text}")
        talk_id = r.json().get("id")
        
        # Step 4: Poll status until done
        _progress("⏳ D-ID: ভিডিও এডিটিং সম্পন্ন হচ্ছে (ধৈর্য ধরুন)...", cb)
        status_url = f"https://api.d-id.com/talks/{talk_id}"
        
        # Poll up to 25 times
        for attempt in range(25):
            time.sleep(4)
            r = requests.get(status_url, headers=headers, timeout=15)
            if r.status_code == 200:
                res = r.json()
                status = res.get("status")
                if status == "done":
                    video_url = res.get("result_url")
                    _progress("📥 D-ID: ভিডিও প্রস্তুত! ডাউনলোড হচ্ছে...", cb)
                    
                    v_res = requests.get(video_url, timeout=30)
                    out_video_path = image_path.replace(".jpg", "_did.mp4")
                    with open(out_video_path, "wb") as f:
                        f.write(v_res.content)
                    _progress("✅ D-ID: লিপ-সিঙ্ক ভিডিও ক্লিপ তৈরি সম্পন্ন!", cb)
                    return out_video_path
                elif status == "error":
                    raise Exception(f"D-ID generation returned error status: {res}")
            else:
                print(f"D-ID polling error: {r.status_code}")
                
        raise Exception("D-ID generation timed out.")
    except Exception as e:
        _progress(f"⚠️ D-ID লিপ-সিঙ্ক ব্যর্থ: {e} (মোশন ফ্যালব্যাকে ফিরে যাওয়া হচ্ছে...)", cb)
        return None


# ── Step 3: Generate Visual Media for each Scene ──────────────────────────────
def _generate_scene_media(scene_text: str, topic: str, scene_idx: int,
                           output_dir: str, is_short: bool = False, is_story: bool = False,
                           audio_path: str = None, cb: Callable | None = None) -> str | None:
    """
    Finds/Generates visual media for a scene:
    1. Try to search and download a Pexels Video clip (for dynamic motion).
    2. Fallback to Gemini Imagen AI Image generation.
    3. Fallback to Pexels Stock Photo.
    """
    pexels_key = os.environ.get("PEXELS_API_KEY", "")
    
    # Clean and generate search keywords from scene text (up to 4 words, alphanumeric only)
    stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with", "by", "of", "from", "is", "are", "was", "were", "this", "that", "these", "those"}
    
    # Extract the main topic subject (first 3 words of topic) to maintain character consistency
    topic_clean = re.sub(r'[^a-zA-Z0-9\s]', '', topic)
    topic_keywords = [w for w in topic_clean.split() if w.lower() not in stop_words][:3]
    topic_prefix = " ".join(topic_keywords)
    
    # Get scene keywords
    words = re.sub(r'[^a-zA-Z0-9\s]', '', scene_text).split()
    search_keywords = [w for w in words if w.lower() not in stop_words][:4]
    
    # Combine main character/topic with scene action keywords
    if topic_prefix:
        query = f"{topic_prefix} " + " ".join(search_keywords)
    else:
        query = " ".join(search_keywords) if search_keywords else topic[:50]
    
    # ── 1. Try Pexels Video Search (Dynamic motion - skipped for Story Mode to maintain cartoon illustrations) ──────────────────
    if pexels_key and not is_story:
        _progress(f"🎥 দৃশ্য {scene_idx+1} এর জন্য Pexels ভিডিও খোঁজা হচ্ছে (Query: '{query}')...", cb)
        try:
            video_path = os.path.join(output_dir, f"scene_{scene_idx:02d}.mp4")
            r = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": pexels_key},
                params={
                    "query": query,
                    "per_page": 1,
                    "orientation": "portrait" if is_short else "landscape"
                },
                timeout=12,
            )
            if r.status_code == 200:
                videos = r.json().get("videos", [])
                if videos:
                    video_files = videos[0].get("video_files", [])
                    # Find a good MP4 link
                    download_url = None
                    for vf in video_files:
                        link = vf.get("link", "")
                        # Prefer mp4 under 1920 width to speed up download
                        if ("video/mp4" in vf.get("file_type", "") or ".mp4" in link) and vf.get("width", 0) <= 1920:
                            download_url = link
                            break
                    if not download_url and video_files:
                        download_url = video_files[0].get("link")
                        
                    if download_url:
                        _progress(f"📥 দৃশ্য {scene_idx+1}: ভিডিও ডাউনলোড হচ্ছে...", cb)
                        v_data = requests.get(download_url, timeout=25).content
                        with open(video_path, "wb") as f:
                            v_data_file = v_data # assign to local variable for clarity
                            f.write(v_data_file)
                        _progress(f"✅ দৃশ্য {scene_idx+1}: Pexels ভিডিও পাওয়া গেছে", cb)
                        return video_path
        except Exception as e:
            _progress(f"⚠️ দৃশ্য {scene_idx+1} ভিডিও সার্চ ব্যর্থ: {e}", cb)

    # ── 2. Fallback to Gemini Imagen (AI Image generation) ───────────────────────
    _progress(f"🎨 দৃশ্য {scene_idx+1} এর জন্য AI ছবি তৈরি হচ্ছে...", cb)
    img_path = os.path.join(output_dir, f"scene_{scene_idx:02d}.jpg")
    
    # Generate image prompt using Gemini if possible
    image_prompt = _build_image_prompt(scene_text, topic, is_story)
    
    try:
        from google import genai
        from google.genai import types as gtypes

        client = genai.Client()
        response = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=image_prompt,
            config=gtypes.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="9:16" if is_short else "16:9",
                negative_prompt="blurry, blurred face, out of focus, low resolution, noise, distorted features, anime, cartoon, illustration, low quality, deformed eyes, extra limbs, bad anatomy, double heads, motion blur, haze",
                person_generation="ALLOW_ADULT",
            ),
        )
        if response.generated_images:
            img_bytes = response.generated_images[0].image.image_bytes
            with open(img_path, "wb") as f:
                f.write(img_bytes)
            _progress(f"✅ দৃশ্য {scene_idx+1}: AI ছবি তৈরি হয়েছে", cb)
            return img_path
    except Exception as e:
        _progress(f"⚠️ Imagen এ সমস্যা, Pollinations Flux AI দিয়ে ছবি তৈরি করা হচ্ছে...", cb)
        if _generate_pollinations_ai_image(image_prompt, img_path, is_short=is_short):
            _progress(f"✅ দৃশ্য {scene_idx+1}: Flux AI 8K ছবি তৈরি হয়েছে", cb)
            return img_path

    # ── 3. Fallback to Pexels Photo Search ─────────────────────────────────────
    if pexels_key:
        try:
            r = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": pexels_key},
                params={
                    "query": query,
                    "per_page": 1,
                    "orientation": "portrait" if is_short else "landscape"
                },
                timeout=10,
            )
            if r.status_code == 200:
                photos = r.json().get("photos", [])
                if photos:
                    img_url = photos[0]["src"]["large2x"]
                    img_data = requests.get(img_url, timeout=15).content
                    with open(img_path, "wb") as f:
                        f.write(img_data)
                    _progress(f"✅ দৃশ্য {scene_idx+1}: Pexels ফটো পাওয়া গেছে", cb)
        except Exception as e:
            _progress(f"⚠️ দৃশ্য {scene_idx+1}: ফটো পাওয়া যায়নি, ব্ল্যাঙ্ক কালার ব্যাকগ্রাউন্ড ব্যবহার করা হবে", cb)

    # D-ID Talking Avatar generation (if API key is present in .env)
    did_key = os.environ.get("D_ID_API_KEY", "")
    final_img_path = img_path if os.path.exists(img_path) else None
    
    # If no image path is resolved, we create a fallback blank image in 4K HD
    if not final_img_path:
        w, h = (2160, 3840) if is_short else (3840, 2160)
        pil_img = Image.new("RGB", (w, h), color=(15, 15, 35))
        pil_img.save(img_path)
        final_img_path = img_path

    if did_key and audio_path and os.path.exists(audio_path):
        did_video = _generate_did_talking_avatar(final_img_path, audio_path, did_key, cb)
        if did_video and os.path.exists(did_video):
            return did_video

    return final_img_path if os.path.exists(final_img_path) else None


def prepare_image_for_frame(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    Resizes and crops the image to fit the target dimensions.
    If the source image is landscape and target is portrait, it fits the image in the center
    with a blurred background of the same image to prevent cutting off characters on the sides.
    Otherwise, it does a center crop with a safe margin.
    """
    from PIL import ImageFilter
    iw, ih = img.size
    
    # Check if we are fitting a landscape image into a portrait screen
    if iw > ih and target_h > target_w:
        # Create blurred background
        scale_bg = max(target_w / iw, target_h / ih)
        bg_w, bg_h = int(iw * scale_bg), int(ih * scale_bg)
        bg = img.resize((bg_w, bg_h), Image.LANCZOS)
        # Crop background to target size
        bg_x = (bg_w - target_w) // 2
        bg_y = (bg_h - target_h) // 2
        bg = bg.crop((bg_x, bg_y, bg_x + target_w, bg_y + target_h))
        # Blur the background
        bg = bg.filter(ImageFilter.GaussianBlur(radius=25))
        
        # Fit original image inside target_w width
        scale_fg = target_w / iw
        fg_w = target_w
        fg_h = int(ih * scale_fg)
        fg = img.resize((fg_w, fg_h), Image.LANCZOS)
        
        # Paste fg onto centered y-position of bg
        fg_y = (target_h - fg_h) // 2
        bg.paste(fg, (0, fg_y))
        return bg
    else:
        # standard crop to target_w, target_h
        scale = max(target_w / iw, target_h / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        resized = img.resize((nw, nh), Image.LANCZOS)
        x0 = (nw - target_w) // 2
        y0 = (nh - target_h) // 2
        return resized.crop((x0, y0, x0 + target_w, y0 + target_h))


# ── Step 3.5: Professional Cinematic Camera Engine ───────────────────────────
import math

class CinematicShotType:
    DOLLY_IN    = "dolly_in"     # Dramatic slow push into character face/eyes
    DOLLY_OUT   = "dolly_out"    # Smooth wide reveal pull-out
    PAN_RIGHT   = "pan_right"    # Hollywood tracking glide left to right
    PAN_LEFT    = "pan_left"     # Hollywood tracking glide right to left
    PEDESTAL_UP = "pedestal_up"  # Smooth crane/pedestal glide up to face
    TILT_DOWN   = "tilt_down"    # Slow tilt down from eyes to action
    DIAGONAL    = "diagonal"     # Dramatic diagonal dynamic dolly

CINEMATIC_SHOT_CYCLE = [
    CinematicShotType.DOLLY_IN,
    CinematicShotType.PAN_RIGHT,
    CinematicShotType.PEDESTAL_UP,
    CinematicShotType.DOLLY_OUT,
    CinematicShotType.PAN_LEFT,
    CinematicShotType.DIAGONAL,
    CinematicShotType.TILT_DOWN,
]

def prepare_cinematic_source(img: Image.Image, target_w: int, target_h: int, overscan: float = 1.25) -> Image.Image:
    """
    Prepares an over-scanned high-resolution canvas with proper framing and aspect ratio.
    The overscan margin provides room for cinematic camera pans, tilts,
    dolly moves, and organic handheld micro-drift without encountering black borders.
    """
    base_canvas = prepare_image_for_frame(img, target_w, target_h)
    os_w = int(target_w * overscan)
    os_h = int(target_h * overscan)
    return base_canvas.resize((os_w, os_h), Image.LANCZOS)

def render_cinematic_camera_frame(
    source_overscan: Image.Image,
    target_w: int,
    target_h: int,
    t: float,
    duration: float,
    shot_idx: int = 0,
    shot_type: str | None = None,
    overscan: float = 1.25,
) -> Image.Image:
    """
    Simulates real Hollywood cinematic camera movement (ARRI/RED cinema camera with 35mm prime lens):
      1. Non-linear smoothstep acceleration/deceleration (inertia curve)
      2. Dynamic camera motion per shot type (dolly push, reveal pull-out, tracking pans, pedestal crane)
      3. Organic camera 'breathing' & subtle handheld micro-drift (sinusoidal frequency harmonics)
      4. Safe boundary bounds prevention
    """
    if shot_type is None:
        shot_type = CINEMATIC_SHOT_CYCLE[shot_idx % len(CINEMATIC_SHOT_CYCLE)]

    dur = max(duration, 0.1)
    progress = min(max(t / dur, 0.0), 1.0)
    
    # Cinematic smoothstep curve: ease-in, smooth constant velocity, ease-out
    smooth_p = progress * progress * (3.0 - 2.0 * progress)

    os_w, os_h = source_overscan.size
    max_dx = max(os_w - target_w, 0)
    max_dy = max(os_h - target_h, 0)
    center_x = max_dx / 2.0
    center_y = max_dy / 2.0

    # Organic handheld camera micro-drift (simulating human Steadicam operator breathing)
    seed = (shot_idx + 1) * 23.47
    drift_x = (math.sin(t * 1.4 + seed) * 0.003 + math.sin(t * 0.65 + seed * 2) * 0.0018) * target_w
    drift_y = (math.cos(t * 1.2 + seed) * 0.003 + math.sin(t * 0.81 + seed * 3) * 0.0015) * target_h

    # Calculate scale factor and camera focal position
    if shot_type == CinematicShotType.DOLLY_IN:
        # Start at 1.0 (relative to target) and smoothly push in to 1.12 towards upper third (face)
        zoom = 1.0 + 0.10 * smooth_p
        pan_x = center_x + drift_x
        pan_y = center_y * 0.85 + drift_y  # Biased slightly upwards toward eye-line

    elif shot_type == CinematicShotType.DOLLY_OUT:
        # Start zoomed in 1.12 and smoothly pull back to reveal scene
        zoom = 1.10 - 0.09 * smooth_p
        pan_x = center_x + drift_x
        pan_y = center_y + drift_y

    elif shot_type == CinematicShotType.PAN_RIGHT:
        # Steady cinematic tracking shot left to right
        zoom = 1.06
        pan_x = center_x - (max_dx * 0.35) + (max_dx * 0.70) * smooth_p + drift_x
        pan_y = center_y + drift_y

    elif shot_type == CinematicShotType.PAN_LEFT:
        # Steady cinematic tracking shot right to left
        zoom = 1.06
        pan_x = center_x + (max_dx * 0.35) - (max_dx * 0.70) * smooth_p + drift_x
        pan_y = center_y + drift_y

    elif shot_type == CinematicShotType.PEDESTAL_UP:
        # Crane / pedestal glide up from mid torso to eyes
        zoom = 1.07
        pan_x = center_x + drift_x
        pan_y = center_y + (max_dy * 0.30) - (max_dy * 0.60) * smooth_p + drift_y

    elif shot_type == CinematicShotType.TILT_DOWN:
        # Smooth tilt down from face to lower action
        zoom = 1.07
        pan_x = center_x + drift_x
        pan_y = center_y - (max_dy * 0.25) + (max_dy * 0.50) * smooth_p + drift_y

    else:  # DIAGONAL
        # Dramatic diagonal dolly + micro push
        zoom = 1.02 + 0.08 * smooth_p
        pan_x = center_x - (max_dx * 0.25) + (max_dx * 0.50) * smooth_p + drift_x
        pan_y = center_y - (max_dy * 0.20) + (max_dy * 0.40) * smooth_p + drift_y

    # Calculate crop window based on current zoom and pan
    crop_w = target_w / zoom
    crop_h = target_h / zoom

    left = pan_x - (crop_w - target_w) / 2.0
    top = pan_y - (crop_h - target_h) / 2.0

    # Clamp safely inside overscan canvas
    left = max(0.0, min(float(max(os_w - crop_w, 0)), left))
    top = max(0.0, min(float(max(os_h - crop_h), top)) )

    crop_box = (int(left), int(top), int(left + crop_w), int(top + crop_h))
    cropped = source_overscan.crop(crop_box)
    
    if cropped.size != (target_w, target_h):
        cropped = cropped.resize((target_w, target_h), Image.BILINEAR)

    return cropped


# ── Step 4: Build Video from Images + Audio ───────────────────────────────────
def apply_short_romantic_template(pil_img: Image.Image, title: str, subtitle: str, t: float) -> Image.Image:
    """
    Apply top/bottom black bars, title text with red stroke, yellow subtitle with black stroke,
    deterministic falling snow particles, and the bottom 'ME ❤ JAN' watermark.
    """
    import math
    from PIL import ImageDraw, ImageFont, Image
    w, h = pil_img.size
    
    # Create copy to draw on
    canvas = pil_img.copy()
    draw = ImageDraw.Draw(canvas)
    
    # 1. Draw top & bottom dark semi-transparent cinematic gradients (not solid black boxes)
    top_h = int(h * 0.12)
    bot_h = int(h * 0.28)
    bot_start = h - bot_h
    for row in range(bot_h):
        alpha = int(210 * (row / bot_h) ** 0.7)
        draw.line([(0, bot_start + row), (w, bot_start + row)], fill=(0, 0, 0))
    draw.rectangle([0, 0, w, top_h], fill=(0, 0, 0))
    
    # 2. Load fonts
    font_paths = [
        "/System/Library/Fonts/KohinoorBangla.ttc",
        "/System/Library/Fonts/Supplemental/Bangla Sangam MN.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf"
    ]
    
    def get_font(size):
        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
        return ImageFont.load_default(size=size)
        
    font_title = get_font(96)
    font_sub = get_font(84)
    font_watermark = get_font(72)
    
    # 3. Draw title text in top bar (white with red outline / stroke)
    if title:
        import textwrap
        wrapped_title = textwrap.wrap(title.strip(), width=24)
        title_y = 250 - (len(wrapped_title) * 110) // 2
        for line in wrapped_title:
            try:
                bbox = draw.textbbox((0, 0), line, font=font_title)
                line_w = bbox[2] - bbox[0]
                line_h = bbox[3] - bbox[1]
            except AttributeError:
                line_w, line_h = draw.textsize(line, font=font_title)
            
            x = (w - line_w) // 2
            try:
                draw.text((x, title_y), line, font=font_title, fill="white", stroke_width=8, stroke_fill="#D32F2F")
            except TypeError:
                for ox, oy in [(-3, -3), (3, -3), (-3, 3), (3, 3)]:
                    draw.text((x+ox, title_y+oy), line, font=font_title, fill="#D32F2F")
                draw.text((x, title_y), line, font=font_title, fill="white")
            title_y += 110

    # 4. Draw subtitle text in the middle area (yellow with black outline)
    if subtitle:
        import textwrap
        wrapped_sub = textwrap.wrap(subtitle.strip(), width=26)
        total_sub_h = len(wrapped_sub) * 95
        sub_y = 3000 - total_sub_h
        for line in wrapped_sub:
            try:
                bbox = draw.textbbox((0, 0), line, font=font_sub)
                line_w = bbox[2] - bbox[0]
                line_h = bbox[3] - bbox[1]
            except AttributeError:
                line_w, line_h = draw.textsize(line, font=font_sub)
            x = (w - line_w) // 2
            try:
                draw.text((x, sub_y), line, font=font_sub, fill="yellow", stroke_width=6, stroke_fill="black")
            except TypeError:
                for ox, oy in [(-2, -2), (2, -2), (-2, 2), (2, 2)]:
                    draw.text((x+ox, sub_y+oy), line, font=font_sub, fill="black")
                draw.text((x, sub_y), line, font=font_sub, fill="yellow")
            sub_y += 95

    # 5. Draw snow particles (floating in the middle area: y=500 to y=3320)
    for idx in range(35):
        seed_x = (idx * 17.31) % 1.0
        seed_y = (idx * 29.57) % 1.0
        seed_speed = (idx * 13.93) % 1.0
        seed_radius = (idx * 7.19) % 1.0
        seed_phase = (idx * 3.47) % 1.0
        
        h_start = 500
        h_end = 3320
        h_span = h_end - h_start
        
        radius = int(8 + seed_radius * 16)
        x_center = seed_x * w
        speed = 100 + seed_speed * 120
        
        y = h_start + (seed_y * h_span + speed * t) % h_span
        sway = 30 * math.sin(1.5 * t + seed_phase * 6.28)
        x = (x_center + sway) % w
        
        try:
            overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            ol_draw = ImageDraw.Draw(overlay)
            alpha_val = int(80 + seed_speed * 120)
            
            ol_draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(255, 255, 255, alpha_val))
            glow_rad = radius * 2
            ol_draw.ellipse([x - glow_rad, y - glow_rad, x + glow_rad, y + glow_rad], fill=(255, 255, 255, int(alpha_val * 0.3)))
            
            canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
            draw = ImageDraw.Draw(canvas)
        except Exception:
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(255, 255, 255))
            
    # 6. Draw romantic watermark at the bottom of the middle video
    watermark = "ME ❤ JAN"
    try:
        bbox = draw.textbbox((0, 0), watermark, font=font_watermark)
        wm_w = bbox[2] - bbox[0]
        wm_h = bbox[3] - bbox[1]
    except AttributeError:
        wm_w, wm_h = draw.textsize(watermark, font=font_watermark)
    
    wm_x = (w - wm_w) // 2
    wm_y = 3200
    
    try:
        draw.text((wm_x, wm_y), watermark, font=font_watermark, fill="white", stroke_width=5, stroke_fill="#E53935")
    except TypeError:
        for ox, oy in [(-2, -2), (2, -2), (-2, 2), (2, 2)]:
            draw.text((wm_x+ox, wm_y+oy), watermark, font=font_watermark, fill="#E53935")
        draw.text((wm_x, wm_y), watermark, font=font_watermark, fill="white")
        
    return canvas


# ── Step 4: Build Video from Images + Audio ───────────────────────────────────
def draw_subtitle_on_image(pil_img: Image.Image, text: str, is_short: bool) -> Image.Image:
    """
    Draw subtitle text directly on a PIL Image with outlines for high legibility,
    completely eliminating the need for ImageMagick/TextClip.
    """
    from PIL import ImageDraw, ImageFont
    w, h = pil_img.size
    draw = ImageDraw.Draw(pil_img)
    
    # 1. Determine font size and character wrap width (scaled for 4K HD resolution)
    if is_short:
        font_size = 92
        char_width = 24
    else:
        font_size = 80
        char_width = 52
        
    # 2. Try loading a bold system font (macOS standard bold fonts supporting English and Bengali)
    font_paths = [
        "/System/Library/Fonts/KohinoorBangla.ttc",
        "/System/Library/Fonts/Supplemental/Bangla MN.ttc",
        "/System/Library/Fonts/Supplemental/Bangla Sangam MN.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf"
    ]
    font = None
    for path in font_paths:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, font_size)
                break
            except Exception:
                continue
    if not font:
        try:
            # Fallback to default pillow font with size
            font = ImageFont.load_default(size=font_size)
        except Exception:
            font = ImageFont.load_default()

    # 3. Wrap text
    wrapped_lines = textwrap.wrap(text.strip()[:120], width=char_width)
    if not wrapped_lines:
        return pil_img

    # 4. Calculate heights and widths of lines
    line_heights = []
    line_widths = []
    for line in wrapped_lines:
        try:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_w = bbox[2] - bbox[0]
            line_h = bbox[3] - bbox[1]
        except AttributeError:
            line_w, line_h = draw.textsize(line, font=font)
        line_widths.append(line_w)
        line_heights.append(line_h + 10)  # text height + line gap

    total_height = sum(line_heights)
    
    # Place text in the middle safe-zone for Shorts, and bottom 25% for long videos
    if is_short:
        y_start = (h - total_height) // 2
    else:
        y_start = h - int(h * 0.25) - (total_height // 2)
    
    # 5. Draw text line by line with a solid black outline/stroke
    current_y = y_start
    text_color = "yellow" if is_short else "white"
    for i, line in enumerate(wrapped_lines):
        line_w = line_widths[i]
        line_h = line_heights[i]
        x = (w - line_w) // 2
        
        try:
            # Draw with modern PIL stroke
            draw.text((x, current_y), line, font=font, fill=text_color, stroke_width=4, stroke_fill="black")
        except TypeError:
            # Fallback manual shadow if stroke_width is not supported
            for ox, oy in [(-2, -2), (2, -2), (-2, 2), (2, 2), (-1, -1), (1, -1), (-1, 1), (1, 1)]:
                draw.text((x + ox, current_y + oy), line, font=font, fill="black")
            draw.text((x, current_y), line, font=font, fill=text_color)
            
        current_y += line_h

    return pil_img


def _build_image_video(scenes: list[dict], audio_path: str, output_path: str,
                        is_short: bool = False, topic: str = "", cb: Callable | None = None) -> str:
    """
    Stitch scene images/videos + audio into a final video with smooth fade transitions.
    """
    _progress("🎬 ভিডিও তৈরি হচ্ছে (ভিডিও/ছবি + অডিও)...", cb)

    from moviepy import (
        AudioFileClip, ImageClip, concatenate_videoclips, ColorClip, VideoFileClip, VideoClip, CompositeVideoClip
    )
    from PIL import Image
    import numpy as np

    # Render in premium 4K HD resolution (2160x3840 for Shorts, 3840x2160 for Long)
    w, h = (2160, 3840) if is_short else (3840, 2160)
    clips = []

    # Check if we have individual scene audio files
    has_scene_audio = any("audio_path" in s for s in scenes)

    if not has_scene_audio:
        try:
            audio = AudioFileClip(audio_path)
            total_duration = audio.duration
            num_scenes = len(scenes)
            scene_duration = total_duration / max(num_scenes, 1)
        except Exception as e:
            _progress(f"⚠️ মূল অডিও লোড ব্যর্থ: {e}", cb)
            audio = None
            scene_duration = 5.0
    else:
        audio = None
        scene_duration = 5.0

    for idx, scene in enumerate(scenes):
        media_path = scene.get("image_path")
        scene_text = scene.get("text", "")
        
        # Determine scene duration based on its dialogue audio clip
        if has_scene_audio and "audio_path" in scene and scene["audio_path"] and os.path.exists(scene["audio_path"]):
            try:
                scene_audio = AudioFileClip(scene["audio_path"])
                curr_scene_duration = scene_audio.duration
            except Exception as e:
                _progress(f"⚠️ দৃশ্য {idx+1}: অডিও লোড ব্যর্থ: {e}", cb)
                scene_audio = None
                curr_scene_duration = scene_duration
        else:
            scene_audio = None
            curr_scene_duration = scene_duration

        is_video = media_path and media_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv'))

        if media_path and os.path.exists(media_path):
            if is_video:
                try:
                    clip = VideoFileClip(media_path).without_audio()
                    
                    # Trim or pad to scene_duration
                    if clip.duration > curr_scene_duration:
                        clip = clip.subclip(0, curr_scene_duration)
                    else:
                        clip = clip.with_duration(curr_scene_duration)
                    
                    if is_short:
                        middle_w, middle_h = 2160, 2820
                        clip_w, clip_h = clip.size
                        scale = middle_w / clip_w
                        new_w = middle_w
                        new_h = int(clip_h * scale)
                        if new_h > middle_h:
                            scale = middle_h / clip_h
                            new_h = middle_h
                            new_w = int(clip_w * scale)
                        clip = clip.resize((new_w, new_h))
                        
                        black_bg = ColorClip(size=(w, h), color=(0, 0, 0), duration=curr_scene_duration)
                        y_pos = 500 + (middle_h - new_h) // 2
                        x_pos = (middle_w - new_w) // 2
                        clip = CompositeVideoClip([black_bg, clip.set_position((x_pos, y_pos))])
                        
                        # Apply template to video frames
                        clip = clip.fl(lambda gf, t: np.array(apply_short_romantic_template(Image.fromarray(gf(t)), topic, scene_text, t)))
                    else:
                        clip = clip.resize((w, h))
                except Exception as e:
                    _progress(f"⚠️ দৃশ্য {idx+1}: ভিডিও লোড ব্যর্থ: {e}", cb)
                    clip = ColorClip(size=(w, h), color=(15, 15, 35), duration=curr_scene_duration)
            else:
                # Load image
                try:
                    pil_img = Image.open(media_path).convert("RGB")
                    
                    overscan_src = prepare_cinematic_source(pil_img, w, h, overscan=1.25)
                    
                    if is_short:
                        def make_kb_frame(t, _src=overscan_src, _s_idx=idx, _dur=curr_scene_duration):
                            cam_frame = render_cinematic_camera_frame(
                                _src, w, h, t, _dur, shot_idx=_s_idx, overscan=1.25
                            )
                            frame_canvas = apply_short_romantic_template(cam_frame, topic, scene_text, t)
                            return np.array(frame_canvas)
                            
                        clip = VideoClip(make_kb_frame, duration=curr_scene_duration)
                    else:
                        def make_kb_frame(t, _src=overscan_src, _s_idx=idx, _dur=curr_scene_duration):
                            cam_frame = render_cinematic_camera_frame(
                                _src, w, h, t, _dur, shot_idx=_s_idx, overscan=1.25
                            )
                            if scene_text:
                                try:
                                    cam_frame = draw_subtitle_on_image(cam_frame, scene_text, is_short)
                                except Exception as e:
                                    pass
                            return np.array(cam_frame)
                            
                        clip = VideoClip(make_kb_frame, duration=curr_scene_duration)
                except Exception as e:
                    _progress(f"⚠️ দৃশ্য {idx+1}: ছবি লোড ব্যর্থ: {e}", cb)
                    clip = ColorClip(size=(w, h), color=(15, 15, 35), duration=curr_scene_duration)
        else:
            # Fallback
            if is_short:
                def make_fallback_frame(t):
                    canvas = Image.new("RGB", (w, h), color=(15, 15, 35))
                    canvas = apply_short_romantic_template(canvas, topic, scene_text, t)
                    return np.array(canvas)
                clip = VideoClip(make_fallback_frame, duration=curr_scene_duration)
            else:
                pil_img = Image.new("RGB", (w, h), color=(15, 15, 35))
                if scene_text:
                    try:
                        pil_img = draw_subtitle_on_image(pil_img, scene_text, is_short)
                    except Exception as e:
                        pass
                arr = np.array(pil_img)
                clip = ImageClip(arr).with_duration(curr_scene_duration)

        # Add subtitle overlay using fl_image for video clips (only if not short, since short is handled inside fl_image/make_kb_frame above)
        if not is_short and is_video and scene_text:
            try:
                def add_subtitles_to_frame(frame_array):
                    pil_img = Image.fromarray(frame_array)
                    pil_img = draw_subtitle_on_image(pil_img, scene_text, is_short)
                    return np.array(pil_img)
                clip = clip.fl_image(add_subtitles_to_frame)
            except Exception as e:
                _progress(f"⚠️ দৃশ্য {idx+1}: ভিডিও ফ্রেম সাবটাইটেল ব্যর্থ: {e}", cb)

        # Fade in/out for smooth visual transitions
        import moviepy.video.fx as fx
        scene_clip = clip.with_effects([fx.FadeIn(0.3), fx.FadeOut(0.3)])

        # Add individual clean audio to this clip without audio fade distortion
        if scene_audio:
            scene_clip = scene_clip.with_audio(scene_audio)

        clips.append(scene_clip)

    if not clips:
        clips = [ColorClip(size=(w, h), color=(15, 15, 35), duration=5.0)]

    final_video = concatenate_videoclips(clips, method="compose")
    
    if not has_scene_audio and audio:
        final_video = final_video.with_audio(audio)

    codec_choice = get_best_encoder()
    try:
        final_video.write_videofile(
            output_path,
            fps=24,
            codec=codec_choice,
            audio_codec="aac",
            logger=None,
            threads=2,
            verbose=False,
        )
    except Exception as e:
        if codec_choice != "libx264":
            print(f"[Warning] Video render failed with codec '{codec_choice}': {e}. Retrying with libx264...")
            global _encoder_cache
            _encoder_cache = "libx264"
            final_video.write_videofile(
                output_path,
                fps=24,
                codec="libx264",
                audio_codec="aac",
                logger=None,
                threads=2,
                verbose=False,
            )
        else:
            raise e

    if audio:
        audio.close()
    final_video.close()
    _progress("✅ ভিডিও রেন্ডার সম্পন্ন!", cb)
    return output_path



# ── Main Entry Point ──────────────────────────────────────────────────────────
def create_faceless_video(
    topic: str,
    narration_text: str,
    voice_key: str = DEFAULT_VOICE,
    output_dir: str = ".",
    is_short: bool = False,
    is_story: bool = False,
    progress_callback: Callable | None = None,
) -> str:
    """
    Main function: creates a full AI image-based video.
    Returns path to the final MP4 file.
    """
    ts = int(time.time())
    audio_path = os.path.join(output_dir, f"narration_{ts}.mp3")
    output_path = os.path.join(output_dir, f"video_{ts}.mp4")
    tmp_dir = tempfile.mkdtemp()

    try:
        # ── 1. Split script into scenes with dialogue voice tags ─────────────
        _progress("📖 স্ক্রিপ্ট দৃশ্যে ভাগ করা হচ্ছে...", progress_callback)
        scenes = split_script_offline(narration_text, voice_key, is_short=is_short)
        _progress(f"✅ {len(scenes)}টি দৃশ্য পাওয়া গেছে", progress_callback)

        # ── 2. Generate voiceover audio for each scene's dialogues ───────────
        for idx, scene in enumerate(scenes):
            scene_audio_path = os.path.join(tmp_dir, f"scene_{idx:02d}_audio.mp3")
            temp_dialogue_files = []
            
            for d_idx, dial in enumerate(scene["dialogues"]):
                dial_path = os.path.join(tmp_dir, f"scene_{idx:02d}_dial_{d_idx:02d}.mp3")
                _generate_audio(dial["text"], dial["voice"], dial_path, progress_callback)
                temp_dialogue_files.append(dial_path)
                
            if len(temp_dialogue_files) == 1:
                import shutil
                shutil.copy2(temp_dialogue_files[0], scene_audio_path)
            elif len(temp_dialogue_files) > 1:
                from moviepy import AudioFileClip, concatenate_audioclips
                clips = []
                for f in temp_dialogue_files:
                    try:
                        clips.append(AudioFileClip(f))
                    except Exception:
                        pass
                if clips:
                    final_scene_audio = concatenate_audioclips(clips)
                    final_scene_audio.write_audiofile(scene_audio_path, logger=None)
                    for clip in clips:
                        clip.close()
                    final_scene_audio.close()
                else:
                    _generate_audio("...", voice_key, scene_audio_path, progress_callback)
            else:
                _generate_audio("...", voice_key, scene_audio_path, progress_callback)
                
            scenes[idx]["audio_path"] = scene_audio_path

        # ── 3. Generate visual media for each scene ───────────────────────────
        for idx, scene in enumerate(scenes):
            media_path = _generate_scene_media(
                scene["text"], topic, idx, tmp_dir, is_short=is_short, is_story=is_story,
                audio_path=scene.get("audio_path"), cb=progress_callback
            )
            scenes[idx]["image_path"] = media_path

        # ── 4. Build final video ──────────────────────────────────────────────
        _build_image_video(
            scenes, audio_path, output_path,
            is_short=is_short, topic=topic, cb=progress_callback
        )

        return output_path

    finally:
        # Cleanup
        for path in [audio_path]:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║          DRAMA SHORT VIDEO CREATOR                                           ║
# ║  Replicates viral Bangla emotional natok shorts style                        ║
# ║  (like Farhan-Mushfiq emotional drama clips on YouTube)                      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# Emotion → background color mapping (top gradient)
EMOTION_COLORS = {
    "sad":       ((20, 30, 90),   (90, 20, 40)),    # brighter blue → bright muted red
    "crying":    ((15, 20, 75),   (75, 15, 75)),    # deep royal blue → bright purple
    "angry":     ((90, 10, 10),   (160, 40, 10)),   # vivid crimson → bright orange-red
    "shocked":   ((10, 75, 75),   (75, 75, 10)),    # cyan → bright amber
    "loving":    ((90, 15, 50),   (50, 15, 90)),    # vibrant rose → deep violet
    "desperate": ((15, 15, 15),   (50, 50, 50)),    # dark grey → medium silver
    "hopeful":   ((15, 45, 90),   (15, 90, 45)),    # royal blue → vibrant emerald
}

CHARACTER_COLORS = {
    "HERO":     "#00E5FF",   # neon cyan
    "HEROINE":  "#FF4081",   # vibrant pink
    "NARRATOR": "#FFD700",   # gold
    "VILLAIN":  "#E040FB",   # neon purple
}


def draw_drama_frame(
    pil_img: Image.Image,
    character: str,
    dialogue: str,
    emotion: str,
    t: float,
    scene_duration: float,
) -> Image.Image:
    """
    Applies the viral Bangla emotional natok (drama) template to a PIL image:
      1. Cinematic top+bottom dark gradient bars
      2. Character name badge (colored by role)
      3. Emotional dialogue subtitle in the lower third
      4. Subtle vignette + film grain effect for cinematic feel
      5. Animated text reveal (fade-in based on t)

    This replicates the visual style of popular Bangla emotional YouTube Shorts.
    """
    import math
    import numpy as _np
    from PIL import ImageDraw, ImageFont, ImageFilter

    w, h = pil_img.size

    # ── 1. Apply cinematic vignette overlay ─────────────────────────────────
    try:
        # Radial vignette: only darken corners/edges, leave center 100% clear (where character faces are)
        mask = Image.new("L", (w, h), 0)
        mdraw = ImageDraw.Draw(mask)
        cx, cy = w // 2, h // 2
        max_r = math.sqrt(cx**2 + cy**2)
        
        # Draw concentric ellipses from outer to inner to build the gradient
        # Outer radius max_r (alpha 180), inner radius 0.45 * max_r (alpha 0)
        # Draw from max_r down to 0, overwriting inner areas with lower opacity values
        for r_pixel in range(int(max_r), 0, -10):
            frac = r_pixel / max_r
            if frac < 0.45:
                break
            # Map frac from [0.45, 1.0] to alpha [0, 180]
            alpha_val = int(180 * ((frac - 0.45) / 0.55) ** 2)
            rx = int(cx * frac)
            ry = int(cy * frac)
            mdraw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=alpha_val)
            
        black_overlay = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        vignette = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        vignette.paste(black_overlay, (0, 0), mask)
        pil_img = Image.alpha_composite(pil_img.convert("RGBA"), vignette).convert("RGB")
    except Exception:
        pass

    draw = ImageDraw.Draw(pil_img)

    # ── 2. Top gradient bar (emotion color) ─────────────────────────────────
    top_h = int(h * 0.13)   # top 13%
    bot_h = int(h * 0.36)   # bottom 36%
    top_clr, _ = EMOTION_COLORS.get(emotion, ((10, 10, 30), (10, 10, 30)))

    # Draw semi-transparent top bar
    try:
        overlay = Image.new("RGBA", (w, top_h), (*top_clr, 200))
        pil_img.paste(Image.fromarray(
            __import__('numpy').array(overlay)[:, :, :3], 'RGB'), (0, 0))
    except Exception:
        draw.rectangle([0, 0, w, top_h], fill=(*top_clr, ))

    # ── 3. Bottom dark gradient for subtitle area ────────────────────────────
    bot_start = h - bot_h
    try:
        for row in range(bot_h):
            alpha = int(220 * (row / bot_h) ** 0.7)
            draw.line([(0, bot_start + row), (w, bot_start + row)],
                      fill=(0, 0, 0))
    except Exception:
        draw.rectangle([0, bot_start, w, h], fill=(0, 0, 0))

    # ── 4. Load fonts ────────────────────────────────────────────────────────
    font_paths = [
        "/System/Library/Fonts/KohinoorBangla.ttc",
        "/System/Library/Fonts/Supplemental/Bangla Sangam MN.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
    ]

    def get_font(size):
        for p in font_paths:
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    continue
        return ImageFont.load_default(size=size)

    font_name = get_font(int(w * 0.055))    # character name
    font_dial = get_font(int(w * 0.072))    # dialogue subtitle
    font_ep   = get_font(int(w * 0.038))    # episode / emotion tag

    # ── 5. Text reveal animation alpha (0→1 over first 0.4s of scene) ───────
    reveal_alpha = min(1.0, t / 0.4)

    def draw_text_stroke(d, x, y, txt, fnt, fill, stroke_fill, stroke_w=6):
        """Draw text with stroke (outline) for legibility."""
        try:
            d.text((x, y), txt, font=fnt, fill=fill,
                   stroke_width=stroke_w, stroke_fill=stroke_fill)
        except TypeError:
            for ox, oy in [(-stroke_w, 0), (stroke_w, 0),
                           (0, -stroke_w), (0, stroke_w),
                           (-stroke_w, -stroke_w), (stroke_w, stroke_w)]:
                d.text((x + ox, y + oy), txt, font=fnt, fill=stroke_fill)
            d.text((x, y), txt, font=fnt, fill=fill)

    # ── 6. Character name badge (top bar) ────────────────────────────────────
    char_display = character if character != "NARRATOR" else "💬 বর্ণনা"
    char_color = CHARACTER_COLORS.get(character, "#FFFFFF")

    try:
        bbox = draw.textbbox((0, 0), char_display, font=font_name)
        name_w = bbox[2] - bbox[0]
        name_h = bbox[3] - bbox[1]
    except AttributeError:
        name_w, name_h = draw.textsize(char_display, font=font_name)

    name_x = int(w * 0.06)
    name_y = int(top_h * 0.15)

    # Badge background pill
    pad = int(w * 0.02)
    badge_rect = [name_x - pad, name_y - pad // 2,
                  name_x + name_w + pad, name_y + name_h + pad // 2]
    try:
        # Draw rounded rectangle badge
        br = int(w * 0.025)
        draw.rounded_rectangle(badge_rect, radius=br,
                                fill=(0, 0, 0, 180), outline=char_color, width=4)
    except AttributeError:
        draw.rectangle(badge_rect, fill=(0, 0, 0), outline=char_color, width=3)

    draw_text_stroke(draw, name_x, name_y, char_display, font_name,
                     fill=char_color, stroke_fill=(0, 0, 0), stroke_w=3)

    # ── 7. Emotion badge (top-right corner) ─────────────────────────────────
    emotion_emoji = {
        "sad": "😢 দুঃখ", "crying": "😭 কান্না", "angry": "😠 রাগ",
        "shocked": "😱 অবাক", "loving": "❤️ ভালোবাসা",
        "desperate": "💔 হতাশ", "hopeful": "🌟 আশা",
    }.get(emotion, f"🎭 {emotion}")
    try:
        ebbox = draw.textbbox((0, 0), emotion_emoji, font=font_ep)
        em_w = ebbox[2] - ebbox[0]
    except AttributeError:
        em_w, _ = draw.textsize(emotion_emoji, font=font_ep)
    draw_text_stroke(draw, w - em_w - int(w * 0.06), name_y,
                     emotion_emoji, font_ep, fill="white", stroke_fill=(0, 0, 0), stroke_w=3)

    # ── 8. Dialogue subtitle (lower third) ──────────────────────────────────
    if dialogue:
        max_chars = 20   # shorter wrap for vertical short
        wrapped = textwrap.wrap(dialogue.strip()[:200], width=max_chars)
        if not wrapped:
            wrapped = [dialogue.strip()[:40]]

        # Calculate total text block height
        line_heights = []
        line_widths = []
        for line in wrapped:
            try:
                bb = draw.textbbox((0, 0), line, font=font_dial)
                line_heights.append(bb[3] - bb[1] + int(h * 0.018))
                line_widths.append(bb[2] - bb[0])
            except AttributeError:
                lw, lh = draw.textsize(line, font=font_dial)
                line_heights.append(lh + int(h * 0.018))
                line_widths.append(lw)

        total_h = sum(line_heights)
        # Position: 72% down from top (within bottom gradient)
        sub_y = int(h * 0.72) - total_h // 2
        sub_y = max(bot_start + int(h * 0.02), sub_y)

        # Draw a beautiful clean semi-transparent background behind text for high legibility
        try:
            pad_x = int(w * 0.05)
            pad_y = int(h * 0.015)
            max_w = max(line_widths)
            box_x0 = (w - max_w) // 2 - pad_x
            box_y0 = sub_y - pad_y
            box_x1 = (w + max_w) // 2 + pad_x
            box_y1 = sub_y + total_h + pad_y
            draw.rectangle([box_x0, box_y0, box_x1, box_y1], fill=(0, 0, 0, 110))
        except Exception:
            pass

        current_y = sub_y
        for i, line in enumerate(wrapped):
            lw = line_widths[i]
            lh = line_heights[i]
            x = (w - lw) // 2
            draw_text_stroke(draw, x, current_y, line, font_dial,
                             fill="#FFEA00", stroke_fill=(0, 0, 0), stroke_w=7)
            current_y += lh

    # ── 9. Subtle film grain for cinematic feel ──────────────────────────────
    try:
        import numpy as _np2
        arr = _np2.array(pil_img).astype(_np2.int16)
        grain = _np2.random.randint(-8, 8, arr.shape, dtype=_np2.int16)
        arr = _np2.clip(arr + grain, 0, 255).astype(_np2.uint8)
        pil_img = Image.fromarray(arr)
    except Exception:
        pass

    return pil_img


def create_drama_short_video(
    scenes: list,          # list of scene dicts from generate_drama_script()
    voice_key: str = "bn_female",
    output_dir: str = ".",
    progress_callback: Callable | None = None,
) -> str:
    """
    Creates a viral Bangla emotional drama short video from structured scene data.
    Each scene has: dialogue, character, emotion, visual_prompt.
    Returns path to final MP4.
    """
    from moviepy import (
        AudioFileClip, ImageClip, concatenate_videoclips,
        ColorClip, VideoClip, CompositeVideoClip
    )
    import numpy as np

    ts = int(time.time())
    output_path = os.path.join(output_dir, f"drama_{ts}.mp4")
    tmp_dir = tempfile.mkdtemp()

    # Shorts resolution: 1080×1920 (standard, faster render)
    W, H = 1080, 1920

    _progress("🎭 নাটকের দৃশ্যগুলো প্রস্তুত করা হচ্ছে...", progress_callback)

    video_clips = []

    try:
        for idx, scene in enumerate(scenes):
            dialogue    = scene.get("dialogue", "")
            character   = scene.get("character", "NARRATOR")
            emotion     = scene.get("emotion", "sad")
            vis_prompt  = scene.get("visual_prompt", "")
            scene_num   = scene.get("scene_num", idx + 1)

            _progress(f"🎬 দৃশ্য {scene_num}/{len(scenes)}: {character} — অডিও তৈরি হচ্ছে...",
                      progress_callback)

            # ── A. Generate voice audio ─────────────────────────────────────
            # HERO/VILLAIN → male voice; HEROINE/NARRATOR → female voice
            if character in ("HERO", "VILLAIN"):
                v_key = "bn_male" if voice_key.startswith("bn") else "en_male"
            else:
                v_key = "bn_female" if voice_key.startswith("bn") else "en_female"

            audio_path = os.path.join(tmp_dir, f"drama_audio_{idx:02d}.mp3")
            try:
                _generate_audio(dialogue, v_key, audio_path, progress_callback)
                scene_audio = AudioFileClip(audio_path)
                scene_dur = max(scene_audio.duration + 0.5, 3.0)
            except Exception as e:
                _progress(f"⚠️ অডিও ব্যর্থ দৃশ্য {scene_num}: {e}", progress_callback)
                scene_audio = None
                scene_dur = 4.0

            # ── B. Generate or fetch background image ───────────────────────
            _progress(f"🎨 দৃশ্য {scene_num}: AI ছবি তৈরি হচ্ছে...", progress_callback)
            img_path = os.path.join(tmp_dir, f"drama_img_{idx:02d}.jpg")

            # Construct a highly detailed, professional photorealistic face portrait prompt
            char_desc = "dramatic Bengali character"
            if character == "HERO":
                char_desc = "handsome young Bengali man (actor hero)"
            elif character == "HEROINE":
                char_desc = "beautiful young Bengali woman (actress heroine)"
            elif character == "VILLAIN":
                char_desc = "angry young Bengali man (villain role)"
            elif character == "NARRATOR":
                char_desc = "emotional young Bengali storyteller (narrator)"
            elif character:
                char_desc = f"dramatic Bengali {character.lower()} character"

            char_prompt = (
                f"A premium cinematic photorealistic 8k scene of a {char_desc} in an emotional drama. "
                f"Centered composition, medium shot showing head and shoulders with safe margins around the borders so they are not cut off. "
                f"Face is clean and extremely clear, highly attractive facial features, sharp focus, expressive emotion, realistic detailed skin texture, no face blur, no distortion. "
                f"Shot on a professional 35mm camera, f/1.8 aperture, shallow depth of field, beautiful soft blurred background bokeh. "
                f"Cinematic color grading with professional warm skin tones and a rich teal and orange color palette, high dynamic range."
            )

            # Construct full prompt with actions and explicit negative guidance embedded to ensure all engines produce clear faces
            full_prompt = (
                f"{char_prompt} Scene action: {vis_prompt}. Emotion: {emotion}. "
                f"Vertical 9:16 composition. Masterpiece photography, dramatic studio lighting, 8k resolution, ultra detailed, rich colors. "
                f"(Avoid: blurry, blurred face, out of focus, cartoon, illustration, drawing, double heads, deformed features, low quality, motion blur, haze)."
            )

            img_generated = False
            try:
                from google import genai as _genai
                from google.genai import types as _gtypes
                _client = _genai.Client()
                resp = _client.models.generate_images(
                    model="imagen-3.0-generate-002",
                    prompt=full_prompt,
                    config=_gtypes.GenerateImagesConfig(
                        number_of_images=1,
                        aspect_ratio="9:16",
                        negative_prompt="blurry, blurred face, out of focus, low resolution, noise, distorted features, anime, cartoon, illustration, low quality, deformed eyes, extra limbs, bad anatomy, double heads, motion blur, haze",
                        person_generation="ALLOW_ADULT",
                    ),
                )
                if resp.generated_images:
                    with open(img_path, "wb") as f:
                        f.write(resp.generated_images[0].image.image_bytes)
                    img_generated = True
                    _progress(f"✅ দৃশ্য {scene_num}: AI ছবি তৈরি হয়েছে", progress_callback)
            except Exception as e:
                _progress(f"⚠️ দৃশ্য {scene_num}: Imagen ফুলব্যাক, Flux AI চেষ্টা করা হচ্ছে...", progress_callback)

            # Tier 2 Fallback: Pollinations Flux AI (Guaranteed 8K HD Face Portrait)
            if not img_generated:
                if _generate_pollinations_ai_image(full_prompt, img_path, is_short=True):
                    img_generated = True
                    _progress(f"✅ দৃশ্য {scene_num}: Flux AI 8K ফেস পোর্ট্রেট তৈরি হয়েছে", progress_callback)

            # Tier 3 Fallback: Pexels photo search
            if not img_generated:
                pexels_key = os.environ.get("PEXELS_API_KEY", "")
                if pexels_key:
                    try:
                        kw = f"bengali portrait {emotion}" if not vis_prompt else vis_prompt[:60]
                        r = requests.get(
                            "https://api.pexels.com/v1/search",
                            headers={"Authorization": pexels_key},
                            params={"query": kw, "per_page": 1, "orientation": "portrait"},
                            timeout=10,
                        )
                        if r.status_code == 200:
                            photos = r.json().get("photos", [])
                            if photos:
                                img_data = requests.get(
                                    photos[0]["src"]["large2x"], timeout=12).content
                                with open(img_path, "wb") as f:
                                    f.write(img_data)
                                img_generated = True
                    except Exception:
                        pass

            # Fallback: solid dark gradient background
            if not img_generated:
                top_c, _ = EMOTION_COLORS.get(emotion, ((10, 10, 30), (10, 10, 30)))
                bg = Image.new("RGB", (W, H), color=top_c)
                bg.save(img_path)

            # ── C. Build animated video clip for this scene ─────────────────
            try:
                raw_img = Image.open(img_path).convert("RGB")
                
                # Enhance sharpness & contrast for razor-sharp facial details
                from PIL import ImageEnhance
                raw_img = ImageEnhance.Sharpness(raw_img).enhance(1.6)
                raw_img = ImageEnhance.Contrast(raw_img).enhance(1.12)

                # Prepare image for vertical frame (with blurred letterboxing if landscape)
                raw_img = prepare_image_for_frame(raw_img, W, H)
            except Exception:
                raw_img = Image.new("RGB", (W, H), color=(10, 10, 30))

            # Prepare cinematic overscan source for dynamic camera movement
            overscan_src = prepare_cinematic_source(raw_img, W, H, overscan=1.25)

            # High-end cinematic camera frame with dynamic motion, easing and organic drift
            def make_drama_frame(t, _src=overscan_src, _dur=scene_dur,
                                 _s_idx=idx, _char=character, _dial=dialogue,
                                 _emo=emotion):
                cam_frame = render_cinematic_camera_frame(
                    _src, W, H, t, _dur, shot_idx=_s_idx, overscan=1.25
                )
                frame = draw_drama_frame(cam_frame, _char, _dial, _emo, t, _dur)
                return np.array(frame)

            scene_clip = VideoClip(make_drama_frame, duration=scene_dur)

            if scene_audio:
                scene_clip = scene_clip.with_audio(scene_audio)

            # Fade transitions
            import moviepy.video.fx as vfx
            scene_clip = scene_clip.with_effects([vfx.FadeIn(0.4), vfx.FadeOut(0.4)])
            video_clips.append(scene_clip)

        if not video_clips:
            raise RuntimeError("কোনো দৃশ্য তৈরি হয়নি।")

        _progress("🔗 সকল দৃশ্য একত্রিত হচ্ছে...", progress_callback)
        final = concatenate_videoclips(video_clips, method="compose")

        codec = get_best_encoder()
        _progress("⚙️ ভিডিও রেন্ডার হচ্ছে (৩-৭ মিনিট সময় লাগতে পারে)...", progress_callback)
        try:
            final.write_videofile(
                output_path, fps=24, codec=codec,
                audio_codec="aac", logger=None, threads=2, verbose=False,
            )
        except Exception as e:
            if codec != "libx264":
                final.write_videofile(
                    output_path, fps=24, codec="libx264",
                    audio_codec="aac", logger=None, threads=2, verbose=False,
                )
            else:
                raise e

        final.close()
        _progress("🎵 আকর্ষণীয় ব্যাকগ্রাউন্ড মিউজিক (BGM) মিক্স করা হচ্ছে...", progress_callback)
        try:
            from youtube_processor import mix_bgm_on_merged_video
            bgm_temp_path = output_path.replace(".mp4", "_bgm_temp.mp4")
            mix_bgm_on_merged_video(output_path, bgm_temp_path)
            if os.path.exists(bgm_temp_path):
                os.replace(bgm_temp_path, output_path)
                _progress("✅ আকর্ষনীয় ব্যাকগ্রাউন্ড মিউজিক মিক্স সম্পন্ন!", progress_callback)
        except Exception as e:
            _progress(f"⚠️ BGM মিক্সে সমস্যা: {e}", progress_callback)

        _progress("✅ ড্রামা ভিডিও রেন্ডার সম্পন্ন!", progress_callback)
        return output_path

    finally:
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
