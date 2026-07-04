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
DEFAULT_MODEL = "gemini-2.5-flash"

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
