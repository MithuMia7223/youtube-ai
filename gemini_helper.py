import os
import json
from google import genai
from google.genai import errors, types
from pydantic import BaseModel
from dotenv import load_dotenv

# Define Pydantic Schema for structured Gemini JSON output
class SEOMeta(BaseModel):
    title: str
    description: str
    tags: list[str]

# Load environment variables
load_dotenv()

# Initialize the Gemini client
# It automatically picks up GEMINI_API_KEY from environment
try:
    client = genai.Client()
except Exception as e:
    print(f"Warning: Failed to initialize Gemini Client. Check if GEMINI_API_KEY is set. Error: {e}")
    client = None

# Model configuration
DEFAULT_MODEL = "gemini-3.5-flash"

def generate_script(topic: str) -> str:
    """
    Generates a structured YouTube video script, optimized title, description, and tags for a given topic.
    """
    if not client:
        return "Gemini API key is not configured. Please check your .env file."

    prompt = f"""
    You are an expert YouTube content creator, viral growth specialist, and SEO expert.
    Write a complete, high-converting video script about the topic: "{topic}".
    
    The script should include:
    1. A hook that immediately grabs attention (0-10 seconds).
    2. An introduction, followed by structured, engaging body sections.
    3. Visual cues and prompt suggestions for an AI image generator (e.g., Midjourney/Imagen) for each section.
    4. A strong Call-To-Action (CTA) encouraging viewers to like, comment, and subscribe.
    5. Three viral Title options.
    6. An SEO-optimized Description (explaining what the video is about, using natural keywords).
    7. A list of 15 viral tags/keywords.

    Write the response clearly and format it beautifully in Markdown. Make the tone engaging, lively, and conversational.
    """
    try:
        response = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=prompt
        )
        return response.text
    except errors.APIError as e:
        return f"Gemini API Error: {e.message}"
    except Exception as e:
        return f"An unexpected error occurred: {e}"

def generate_seo_meta(script_content: str) -> dict:
    """
    Analyzes a script draft and generates an optimized Title, Description, and Tags.
    Uses Structured JSON output to guarantee perfect parsing.
    """
    if not client:
        return {
            "title": "Gemini API Error",
            "description": "Gemini API key is not configured.",
            "tags": []
        }

    prompt = f"""
    Analyze the following YouTube video script content and generate:
    1. A single best SEO-optimized title (under 70 characters).
    2. A comprehensive YouTube description (including key topics covered, social CTAs, etc. - approx 150-250 words).
    3. Exactly 10 highly relevant tags/keywords.
    
    Script content:
    {script_content}
    """
    try:
        response = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SEOMeta,
            )
        )
        text = response.text
        res_dict = json.loads(text)
        
        return {
            "title": res_dict.get("title", "Optimized Video Title").strip(),
            "description": res_dict.get("description", "Optimized video description.").strip(),
            "tags": res_dict.get("tags", [])
        }
    except Exception as e:
        print(f"Error generating SEO meta: {e}")
        import re
        fallback_title = "My Story"
        if script_content:
            # Keep Bengali and alphanumeric characters, strip punctuation
            cleaned = re.sub(r'[^\w\s\u0980-\u09ff]', '', script_content)
            words = [w.strip() for w in cleaned.split() if w.strip()]
            if words:
                fallback_title = " ".join(words[:5])
        return {
            "title": fallback_title,
            "description": "Video description.",
            "tags": [],
            "quota_limit": "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e)
        }

def generate_drama_script(topic: str) -> dict:
    """
    Generates a viral Bangla emotional drama script in the style of popular YouTube Shorts
    (like Farhan Mushfiq emotional drama clips).
    Returns a dict with: scenes (list of scene dicts), title, description, tags
    Each scene has: dialogue, emotion, visual_prompt, character (HERO/HEROINE/NARRATOR)
    """
    if not client:
        return {
            "scenes": [],
            "title": "ইমোশনাল নাটক",
            "description": "বাংলা ইমোশনাল শর্টস",
            "tags": ["natok", "emotional", "bangla"]
        }

    prompt = f"""
তুমি একজন বাংলা ভাইরাল YouTube Shorts নাটক স্ক্রিপ্টরাইটার।
নিচের টপিকের উপর ভিত্তি করে একটি অত্যন্ত ইমোশনাল, হৃদয়গ্রাহী বাংলা শর্টস নাটক তৈরি করো:

টপিক: "{topic}"

নাটকটি হতে হবে:
- ৩ থেকে ৪টি দৃশ্য (Scene) থাকবে (যেন ভিডিওর মোট দৈর্ঘ্য ৬০ সেকেন্ডের কম থাকে এবং এটি YouTube Shorts হিসেবে আপলোড হয়)
- প্রতিটি দৃশ্যে HERO/HEROINE/NARRATOR এর ডায়ালগ থাকবে
- অত্যন্ত ইমোশনাল এবং নাটকীয় ভাষায় লেখা
- বাংলাদেশী নাটক স্টাইলে (যেমন: ফারহান-মুশফিক টাইপ)
- সবকিছু বাংলায় লিখবে (রোমান বাংলা নয়, বাংলা হরফে)

JSON ফরম্যাটে রিটার্ন করো:
{{
  "title": "ভাইরাল ইমোশনাল টাইটেল (৬০ অক্ষরের মধ্যে)",
  "description": "YouTube SEO Description (বাংলায়, ১৫০ শব্দের মধ্যে)",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7"],
  "scenes": [
    {{
      "scene_num": 1,
      "character": "NARRATOR",
      "dialogue": "নাটকের শুরুতে পরিচয় দেওয়ার ডায়ালগ...",
      "emotion": "sad",
      "visual_prompt": "English description for AI image generation (cinematic, emotional Bengali scene)"
    }},
    {{
      "scene_num": 2,
      "character": "HERO",
      "dialogue": "হিরোর ইমোশনাল ডায়ালগ...",
      "emotion": "crying",
      "visual_prompt": "English description for AI image generation"
    }}
  ]
}}

- দৃশ্যগুলো হবে: intro hook, conflict buildup, emotional peak, twist, resolution
- সর্বশেষ দৃশ্যে অবশ্যই দর্শককে উৎসাহিত করে এই ডায়ালগটি যোগ করবে: "আমার ভিডিওটি ভালো লেগে থাকলে লাইক, কমেন্ট ও শেয়ার করবেন।"
- visual_prompt অবশ্যই ইংরেজিতে হবে এবং তাতে দৃশ্যটি বিশদভাবে বর্ণনা করবে। যদি দুই চরিত্র কথা বলে বা একসাথে থাকে, তবে দুজনকে একসাথে একটি মিডিয়াম শটে (medium shot of both characters) দেখাবে। ডায়ালগের সময় ক্যারেক্টারদের মুখমণ্ডল এবং মাথা যেন ফ্রেমের বাইরে কেটে না যায়, তা নিশ্চিত করতে prompts-এ 'centered composition, medium shot showing both characters, safe frame margins, faces fully inside the frame' উল্লেখ করবে। মুখমণ্ডল ও ক্যারেক্টার যেন একদম পরিষ্কার, অত্যন্ত স্পষ্ট ও শার্প ফোকাসড (crystal clear faces, sharp focus, highly detailed features) থাকে। ব্যাকগ্রাউন্ডটি নরমভাবে ঝাপসা বা বোকেহ ইফেক্ট সহ (soft blurred background bokeh, f/1.8 shallow depth of field) এবং সিনেম্যাটিক কালার গ্রেডিং (teal and orange color palette) থাকবে।
emotion হতে পারে: sad, crying, angry, shocked, loving, desperate, hopeful
character হতে পারে: HERO, HEROINE, NARRATOR, VILLAIN
"""
    try:
        response = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=prompt
        )
        text = response.text.strip()
        # Strip markdown code block if present
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        import json as _json
        result = _json.loads(text)
        return result
    except Exception as e:
        print(f"[Drama Script] Error: {e}")
        # Fallback
        return {
            "title": f"💔 {topic} - ইমোশনাল শর্টস নাটক",
            "description": f"বাংলা ইমোশনাল নাটক: {topic}",
            "tags": ["natok", "emotional", "bangla", "shorts", "drama", "viral", "bangladesh"],
            "scenes": [
                {
                    "scene_num": 1,
                    "character": "NARRATOR",
                    "dialogue": f"এটি একটি ইমোশনাল গল্প... {topic} নিয়ে।",
                    "emotion": "sad",
                    "visual_prompt": f"Emotional Bengali drama scene about {topic}, cinematic lighting, tears"
                }
            ]
        }


def analyze_and_suggest_growth(stats_data: dict) -> str:

    """
    Provides channel optimization advice based on basic stats data.
    """
    if not client:
        return "Gemini API key is not configured."

    prompt = f"""
    You are a premium YouTube Growth Consultant. Analyze these channel stats and provide 3 actionable, high-impact strategies to grow views and subscribers:
    
    Channel Name: {stats_data.get('channel_title', 'Unknown')}
    Subscribers: {stats_data.get('subscriber_count', 'N/A')}
    Total Views: {stats_data.get('view_count', 'N/A')}
    Total Videos: {stats_data.get('video_count', 'N/A')}
    
    Be direct, helpful, and encourage the creator. Focus on practical viral content suggestions.
    """
    try:
        response = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"Error analyzing growth: {e}")
        return """
⚠️ *Gemini API কোটা শেষ!*
আপনার ফ্রি Gemini API কি-এর দৈনিক ব্যবহারের লিমিট (২০টি রিকোয়েস্ট) শেষ হয়ে গেছে। আপনার চ্যানেলের জন্য এখানে ৩টি অ্যাকশনেবল গ্রোথ টিপস দেওয়া হলো:

১. 📊 *নিয়মিত কন্টেন্ট আপলোড (Consistency):* চ্যানেলের রিচ বাড়ানোর জন্য একটি নির্দিষ্ট রুটিন মেনে ভিডিও আপলোড করতে থাকুন।
২. 🎨 *আকর্ষণীয় থাম্বনেইল (CTR):* ভিডিওর টাইটেল ও থাম্বনেইলে আকর্ষণ বাড়ান যাতে দর্শকরা দেখামাত্রই ক্লিক করে।
৩. 📱 *শর্টস ও ট্রেন্ডিং টপিক:* দ্রুত ভিউ এবং সাবস্ক্রাইবার বাড়াতে নিয়মিত ফানি শর্টস কন্টেন্ট আপলোড করুন।

*(আপনার কোটা সাধারণত ২৪ ঘণ্টা পর স্বয়ংক্রিয়ভাবে রিলিজ হয়ে যাবে অথবা আপনি এপিআই কি পরিবর্তন করে নিতে পারেন।)*
"""
