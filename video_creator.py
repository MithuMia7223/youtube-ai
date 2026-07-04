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


# ── Step 1: Generate Audio ─────────────────────────────────────────────────────
def _generate_audio(text: str, voice_key: str, output_path: str,
                    cb: Callable | None = None) -> str:
    _progress("🎙️ Neural ভয়েসওভার তৈরি হচ্ছে...", cb)

    voice_name = VOICES.get(voice_key, VOICES[DEFAULT_VOICE])
    clean_text = text[:4500].strip()

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


def split_script_offline(script: str, default_voice: str, max_scenes: int = 8) -> list[dict]:
    """
    Splits the narration script into scenes by paragraphs/sentences,
    and extracts dialogues with male/female voice mapping to support multi-character speech.
    """
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
            model="gemini-2.5-flash",
            contents=(
                f"Convert this story scene into a detailed visual image prompt for AI art generation.\n"
                f"Core Subject/Character: {topic}\n"
                f"Scene Action: {scene_text[:300]}\n\n"
                f"Rules:\n"
                f"- The style must be: {style_desc}\n"
                f"- The main character/subject MUST match the Core Subject: '{topic}' in terms of appearance, type, and style to maintain consistency across scenes.\n"
                f"- Visually describe the action: '{scene_text[:300]}'.\n"
                f"- Describe specific setting, lighting, mood, and color.\n"
                f"- Keep it under 60 words. No text, no watermarks."
            )
        )
        return resp.text.strip()[:400]
    except Exception:
        # Simple fallback prompt
        return (
            f"Cartoon illustration of {topic}. {scene_text[:150]}. "
            f"Vivid colors, professional quality, storytelling style, "
            f"dramatic lighting, no text."
            if is_story else
            f"Cinematic illustration of {topic}. {scene_text[:150]}. "
            f"Vivid colors, professional quality, storytelling style, "
            f"dramatic lighting, no text."
        )


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
            ),
        )
        if response.generated_images:
            img_bytes = response.generated_images[0].image.image_bytes
            with open(img_path, "wb") as f:
                f.write(img_bytes)
            _progress(f"✅ দৃশ্য {scene_idx+1}: AI ছবি তৈরি হয়েছে", cb)
            return img_path
    except Exception as e:
        _progress(f"⚠️ AI ছবি তৈরিতে সমস্যা, Pexels ফটো সার্চ করা হচ্ছে...", cb)

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
    
    # If no image path is resolved, we create a fallback blank image
    if not final_img_path:
        w, h = (1080, 1920) if is_short else (1920, 1080)
        pil_img = Image.new("RGB", (w, h), color=(15, 15, 35))
        pil_img.save(img_path)
        final_img_path = img_path

    if did_key and audio_path and os.path.exists(audio_path):
        did_video = _generate_did_talking_avatar(final_img_path, audio_path, did_key, cb)
        if did_video and os.path.exists(did_video):
            return did_video

    return final_img_path if os.path.exists(final_img_path) else None


# ── Step 4: Build Video from Images + Audio ───────────────────────────────────
def draw_subtitle_on_image(pil_img: Image.Image, text: str, is_short: bool) -> Image.Image:
    """
    Draw subtitle text directly on a PIL Image with outlines for high legibility,
    completely eliminating the need for ImageMagick/TextClip.
    """
    from PIL import ImageDraw, ImageFont
    w, h = pil_img.size
    draw = ImageDraw.Draw(pil_img)
    
    # 1. Determine font size and character wrap width
    if is_short:
        font_size = 46
        char_width = 24
    else:
        font_size = 40
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
    
    # Place text in the bottom 25% region
    y_start = h - int(h * 0.25) - (total_height // 2)
    
    # 5. Draw text line by line with a solid black outline/stroke
    current_y = y_start
    for i, line in enumerate(wrapped_lines):
        line_w = line_widths[i]
        line_h = line_heights[i]
        x = (w - line_w) // 2
        
        try:
            # Draw with modern PIL stroke
            draw.text((x, current_y), line, font=font, fill="white", stroke_width=3, stroke_fill="black")
        except TypeError:
            # Fallback manual shadow if stroke_width is not supported
            for ox, oy in [(-2, -2), (2, -2), (-2, 2), (2, 2), (-1, -1), (1, -1), (-1, 1), (1, 1)]:
                draw.text((x + ox, current_y + oy), line, font=font, fill="black")
            draw.text((x, current_y), line, font=font, fill="white")
            
        current_y += line_h

    return pil_img


def _build_image_video(scenes: list[dict], audio_path: str, output_path: str,
                        is_short: bool = False, cb: Callable | None = None) -> str:
    """
    Stitch scene images/videos + audio into a final video with smooth fade transitions.
    """
    _progress("🎬 ভিডিও তৈরি হচ্ছে (ভিডিও/ছবি + অডিও)...", cb)

    from moviepy.editor import (
        AudioFileClip, ImageClip, concatenate_videoclips, ColorClip, VideoFileClip, VideoClip
    )
    from PIL import Image
    import numpy as np

    w, h = (1080, 1920) if is_short else (1920, 1080)
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
                        clip = clip.set_duration(curr_scene_duration)
                    
                    # Resize video to fit target size
                    clip = clip.resize((w, h))
                except Exception as e:
                    _progress(f"⚠️ দৃশ্য {idx+1}: ভিডিও লোড ব্যর্থ: {e}", cb)
                    clip = ColorClip(size=(w, h), color=(15, 15, 35), duration=curr_scene_duration)
            else:
                # Load and resize image to target size
                try:
                    pil_img = Image.open(media_path).convert("RGB")
                    pil_img = pil_img.resize((w, h), Image.LANCZOS)
                    
                    # Add subtitle text overlay directly to the Pillow image
                    if scene_text:
                        try:
                            pil_img = draw_subtitle_on_image(pil_img, scene_text, is_short)
                        except Exception as e:
                            _progress(f"⚠️ দৃশ্য {idx+1}: সাবটাইটেল তৈরিতে সমস্যা: {e}", cb)
                    
                    # Apply Ken Burns zoom-in effect to animate the image (Image to Video)
                    def make_kb_frame(t):
                        # Smooth zoom from 1.0x to 1.12x scale over the scene duration
                        scale = 1.0 + 0.12 * (t / curr_scene_duration)
                        sw = int(w * scale)
                        sh = int(h * scale)
                        scaled_img = pil_img.resize((sw, sh), Image.LANCZOS)
                        dx = (sw - w) // 2
                        dy = (sh - h) // 2
                        cropped_img = scaled_img.crop((dx, dy, dx + w, dy + h))
                        return np.array(cropped_img)
                        
                    clip = VideoClip(make_kb_frame, duration=curr_scene_duration)
                except Exception as e:
                    _progress(f"⚠️ দৃশ্য {idx+1}: ছবি লোড ব্যর্থ: {e}", cb)
                    clip = ColorClip(size=(w, h), color=(15, 15, 35), duration=curr_scene_duration)
        else:
            # Dark background fallback
            pil_img = Image.new("RGB", (w, h), color=(15, 15, 35))
            if scene_text:
                try:
                    pil_img = draw_subtitle_on_image(pil_img, scene_text, is_short)
                except Exception as e:
                    pass
            arr = np.array(pil_img)
            clip = ImageClip(arr).set_duration(curr_scene_duration)

        # Add subtitle overlay using fl_image for video clips
        if is_video and scene_text:
            try:
                def add_subtitles_to_frame(frame_array):
                    pil_img = Image.fromarray(frame_array)
                    pil_img = draw_subtitle_on_image(pil_img, scene_text, is_short)
                    return np.array(pil_img)
                clip = clip.fl_image(add_subtitles_to_frame)
            except Exception as e:
                _progress(f"⚠️ দৃশ্য {idx+1}: ভিডিও ফ্রেম সাবটাইটেল ব্যর্থ: {e}", cb)

        # Add individual audio to this clip
        if scene_audio:
            clip = clip.set_audio(scene_audio)

        # Fade in/out for smooth transitions
        scene_clip = clip.fadein(0.5).fadeout(0.5)
        clips.append(scene_clip)

    if not clips:
        clips = [ColorClip(size=(w, h), color=(15, 15, 35), duration=5.0)]

    final_video = concatenate_videoclips(clips, method="compose")
    
    if not has_scene_audio and audio:
        final_video = final_video.set_audio(audio)

    final_video.write_videofile(
        output_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        logger=None,
        threads=2,
        verbose=False,
    )

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
        scenes = split_script_offline(narration_text, voice_key, max_scenes=8 if not is_short else 5)
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
                from moviepy.editor import AudioFileClip, concatenate_audioclips
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
            is_short=is_short, cb=progress_callback
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
