import os
import time
import threading
from datetime import datetime
from dotenv import load_dotenv
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ── Import helpers ────────────────────────────────────────────────────────────
from gemini_helper import generate_script, generate_seo_meta, analyze_and_suggest_growth
from youtube_helper import (
    get_auth_url, save_token_from_code,
    get_youtube_service, get_channel_stats, upload_video, upload_thumbnail
)
from video_creator import create_faceless_video, VOICE_LABELS, DEFAULT_VOICE
from thumbnail_creator import create_thumbnail
from scheduler_helper import (
    set_schedule, remove_schedule, get_schedule, get_all_schedules,
    get_due_schedules, mark_run
)
from affiliate_helper import get_affiliate_text, save_link, load_links

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    print("[ERROR] TELEGRAM_BOT_TOKEN is not set in the .env file!")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

# ── User session store ────────────────────────────────────────────────────────
user_sessions = {}


def get_session(chat_id: int) -> dict:
    if chat_id not in user_sessions:
        user_sessions[chat_id] = {
            'last_seo': None,
            'video_path': None,
            'video_title': None,
            'video_desc': None,
            'video_tags': [],
            'voice': DEFAULT_VOICE,
            'pending_topic': None,
            'pending_is_short': False,
        }
    return user_sessions[chat_id]


# ╔══════════════════════════════════════════════════════════╗
# ║              START & HELP                                ║
# ╚══════════════════════════════════════════════════════════╝

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    
    # Create persistent menu buttons on user keyboard
    from telebot.types import ReplyKeyboardMarkup, KeyboardButton
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    
    btn_create   = KeyboardButton("🎬 Create Video")
    btn_schedule = KeyboardButton("📅 Auto-Post Schedule")
    btn_grow     = KeyboardButton("📊 Grow Channel")

    markup.add(btn_create, btn_schedule, btn_grow)

    text = """
👋 *হ্যালো! আমি আপনার AI YouTube Bot!*

🤖 আমি আপনাকে সাহায্য করব:
• AI দিয়ে আকর্ষণীয় ভিডিও তৈরি করতে
• প্রতিদিন নির্দিষ্ট সময়ে অটো-পোস্ট করতে
• আপনার ইউটিউব চ্যানেল গ্রো করতে সাহায্য করতে

━━━━━━━━━━━━━━━━━━━━
👇 *নিচের বাটনগুলো ক্লিক করে কাজ শুরু করুন:*
━━━━━━━━━━━━━━━━━━━━
⚙️ *ইউটিউব কানেক্ট না থাকলে প্রথমে /auth লিখে কানেক্ট করুন।*
    """
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')


@bot.message_handler(commands=['help'])
def send_help(message):
    send_welcome(message)


# ╔══════════════════════════════════════════════════════════╗
# ║              YOUTUBE AUTH                                ║
# ╚══════════════════════════════════════════════════════════╝

@bot.message_handler(commands=['auth'])
def handle_auth(message):
    chat_id = message.chat.id
    if not os.path.exists('client_secrets.json'):
        bot.send_message(chat_id, "❌ *client_secrets.json* ফাইল পাওয়া যায়নি। প্রজেক্ট ফোল্ডারে এই ফাইলটি রাখো।", parse_mode='Markdown')
        return
    try:
        auth_url = get_auth_url()
        instruction = f"""
🔐 *YouTube চ্যানেল অথোরাইজেশন:*

১. এই লিংকে ক্লিক করো:
👉 [এখানে ক্লিক করো]({auth_url})

২. Google অ্যাকাউন্টে লগইন করে Permission দাও
৩. Browser redirect হলে URL-টি কপি করে এখানে পাঠাও
        """
        sent = bot.send_message(chat_id, instruction, parse_mode='Markdown', disable_web_page_preview=True)
        bot.register_next_step_handler(sent, process_auth_url)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {e}")


def process_auth_url(message):
    chat_id = message.chat.id
    user_input = message.text.strip()
    if user_input.startswith('/'):
        bot.send_message(chat_id, "❌ বাতিল। নতুনভাবে /auth লিখুন।")
        return
    code = user_input
    if "code=" in user_input:
        import urllib.parse as urlparse
        parsed = urlparse.urlparse(user_input)
        code_list = urlparse.parse_qs(parsed.query).get('code')
        if code_list:
            code = code_list[0]
    bot.send_message(chat_id, "⏳ কোড যাচাই হচ্ছে...")
    try:
        save_token_from_code(code)
        bot.send_message(chat_id, "🎉 *সাফল্য!* YouTube Channel সফলভাবে কানেক্ট হয়েছে!\n\nএখন `/create <topic>` দিয়ে প্রথম Faceless ভিডিও তৈরি করো! 🚀", parse_mode='Markdown')
    except Exception as e:
        bot.send_message(chat_id, f"❌ কোড Error: {e}\n\nআবার /auth দিয়ে চেষ্টা করো।")


# ╔══════════════════════════════════════════════════════════╗
# ║          AI FACELESS VIDEO CREATION                      ║
# ╚══════════════════════════════════════════════════════════╝

@bot.message_handler(commands=['create'])
def handle_create(message):
    chat_id = message.chat.id
    topic = message.text.replace('/create', '').strip()

    youtube = get_youtube_service()
    if not youtube:
        bot.send_message(chat_id, "❌ প্রথমে /auth দিয়ে YouTube Channel কানেক্ট করো।")
        return

    if not topic:
        sent = bot.send_message(chat_id, "✍️ কোন টপিকে Faceless Video বানাবে? টপিক লিখো:")
        bot.register_next_step_handler(sent, lambda m: _start_video_creation(m.chat.id, m.text.strip(), is_short=False))
        return

    _start_video_creation(chat_id, topic, is_short=False)


@bot.message_handler(commands=['short'])
def handle_short(message):
    chat_id = message.chat.id
    topic = message.text.replace('/short', '').strip()

    youtube = get_youtube_service()
    if not youtube:
        bot.send_message(chat_id, "❌ প্রথমে /auth দিয়ে YouTube Channel কানেক্ট করো।")
        return

    if not topic:
        sent = bot.send_message(chat_id, "✍️ কোন টপিকে YouTube Short বানাবে? টপিক লিখো:")
        bot.register_next_step_handler(sent, lambda m: _start_video_creation(m.chat.id, m.text.strip(), is_short=True))
        return

    _start_video_creation(chat_id, topic, is_short=True)


def _start_video_creation(chat_id: int, topic: str, is_short: bool = False):
    """Launch video creation pipeline in a background thread."""
    if not topic or topic.startswith('/'):
        bot.send_message(chat_id, "❌ বৈধ টপিক দাও।")
        return

    session = get_session(chat_id)
    session['pending_topic'] = topic
    session['pending_is_short'] = is_short

    kind = "YouTube Short (60s)" if is_short else "Faceless Video"
    bot.send_message(
        chat_id,
        f"🚀 *{kind} তৈরি শুরু হয়েছে!*\n\n"
        f"📌 Topic: *{topic}*\n\n"
        f"⏳ Steps:\n"
        f"1️⃣ Gemini AI দিয়ে Script তৈরি হবে\n"
        f"2️⃣ AI Voice Narration তৈরি হবে\n"
        f"3️⃣ Stock Footage ডাউনলোড হবে\n"
        f"4️⃣ Video Render হবে (2-5 মিনিট)\n"
        f"5️⃣ Thumbnail তৈরি হবে\n"
        f"6️⃣ YouTube-এ Upload হবে\n\n"
        f"_অনুগ্রহ করে অপেক্ষা করো..._",
        parse_mode='Markdown'
    )

    thread = threading.Thread(
        target=_full_video_pipeline,
        args=(chat_id, topic, is_short),
        daemon=True
    )
    thread.start()


def _full_video_pipeline(chat_id: int, topic: str, is_short: bool, custom_script: str = None):
    """
    Full pipeline:
    Script → AI Images per Scene → TTS → Render → Thumbnail → YouTube Upload
    Supports custom_script for Story Mode.
    """
    session = get_session(chat_id)
    voice = session.get('voice', DEFAULT_VOICE)
    tmp_files = []

    def _notify(msg):
        try:
            bot.send_message(chat_id, msg, parse_mode='Markdown')
        except Exception:
            pass

    try:
        # Step 1: Generate or use provided Script
        if custom_script:
            # Story mode: use the user's story directly
            _notify("🎨 *Step 1/5:* তোমার গল্প ব্যবহার করা হচ্ছে...")
            script = custom_script
            seo = generate_seo_meta(script)
        else:
            _notify("🧠 *Step 1/5:* Gemini AI দিয়ে Script তৈরি হচ্ছে...")
            script = generate_script(topic)
            if script.startswith("Gemini API Error") or script.startswith("An unexpected error occurred"):
                _notify(f"❌ *Gemini API ব্যর্থ হয়েছে:*\n\n{script}\n\nআপনার ফ্রি এপিআই কোটা (প্রতিদিন ২০টি রিকোয়েস্ট) শেষ হয়ে থাকতে পারে। কিছুক্ষণ পর চেষ্টা করুন বা এপিআই কি পরিবর্তন করুন।")
                return
            seo = generate_seo_meta(script)
        session['last_seo'] = seo
        if seo.get("quota_limit"):
            _notify("⚠️ *Gemini API কোটা শেষ!* আপনার Gemini API ফ্রি-কোটা শেষ হয়ে গেছে। ব্যাকআপ টাইটেল দিয়ে ভিডিও তৈরি হচ্ছে।")

        video_title = seo.get('title', topic)[:100]
        raw_desc = seo.get('description', '')
        
        # 💸 Auto affiliate link insertion based on niche
        affiliate_promo = get_affiliate_text(topic)
        video_desc = (raw_desc + affiliate_promo)[:5000]
        
        video_tags = seo.get('tags', [])[:15]

        _notify(f"✅ Script তৈরি!\n📌 Title: *{video_title}*\n💸 ডেসক্রিপশনে অটো-অ্যাফিলিয়েট লিংক যোগ করা হয়েছে।")

        # Step 2-4: Create Faceless Video
        _notify("🎬 *Step 2-4/5:* AI Voice + Stock Footage + Rendering শুরু হয়েছে...\n_(এটি ২-৫ মিনিট নিতে পারে)_")

        def _progress(msg):
            try:
                bot.send_message(chat_id, f"  ↳ {msg}")
            except Exception:
                pass

        video_path = create_faceless_video(
            topic=topic,
            narration_text=script,
            voice_key=voice,
            output_dir=".",
            is_short=is_short,
            is_story=(custom_script is not None),
            progress_callback=_progress
        )
        tmp_files.append(video_path)

        # Step 5: Create Thumbnail
        _notify("🖼️ *Step 5/5:* Thumbnail তৈরি হচ্ছে...")
        thumb_path = f"thumb_{int(time.time())}.jpg"
        create_thumbnail(title=video_title, topic=topic[:20], output_path=thumb_path)
        tmp_files.append(thumb_path)

        # Step 6: Upload to YouTube
        _notify("🚀 *YouTube Upload শুরু হয়েছে...*")
        privacy = "public"
        video_id = upload_video(
            file_path=video_path,
            title=video_title,
            description=video_desc,
            tags=video_tags,
            privacy_status=privacy
        )

        if video_id and os.path.exists(thumb_path):
            _notify("🖼️ *Custom Thumbnail আপলোড করা হচ্ছে...*")
            try:
                upload_thumbnail(video_id, thumb_path)
            except Exception as e:
                print(f"Thumbnail upload failed: {e}")

        success_text = f"""
🎉 *ভিডিও সফলভাবে YouTube-এ আপলোড হয়েছে!*

🔗 লিংক: https://youtu.be/{video_id}
📌 Title: *{video_title}*
⚙️ Status: *PUBLIC*
🎤 Voice: *{VOICE_LABELS.get(voice, voice)}*
💸 Monetization: *Affiliate Link Inserted!*

💰 *Income টিপস:*
• প্রতিদিন ২টি করে ভিডিও আপলোড করো
• `/autoschedule` দিয়ে Auto-post সেট করো
• `/mystatus` দিয়ে স্ট্যাটাস চেক করো
        """
        bot.send_message(chat_id, success_text, parse_mode='Markdown')

        # Send thumbnail as preview
        try:
            with open(thumb_path, 'rb') as th:
                bot.send_photo(chat_id, th, caption=f"🖼️ Thumbnail: {video_title}")
        except Exception:
            pass

    except Exception as e:
        bot.send_message(chat_id, f"❌ ভিডিও তৈরিতে সমস্যা হয়েছে:\n`{e}`\n\nআবার চেষ্টা করো।", parse_mode='Markdown')

    finally:
        # Cleanup temp files
        for f in tmp_files:
            try:
                if f and os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass


# ╔══════════════════════════════════════════════════════════╗
# ║          AUTO SCHEDULE SYSTEM                            ║
# ╚══════════════════════════════════════════════════════════╝

@bot.message_handler(commands=['autoschedule'])
def handle_autoschedule(message):
    chat_id = message.chat.id

    youtube = get_youtube_service()
    if not youtube:
        bot.send_message(chat_id, "❌ প্রথমে /auth দিয়ে YouTube Channel কানেক্ট করো।")
        return

    text = """
📅 *Auto-Upload Schedule সেটআপ*

প্রতিদিন নির্ধারিত সময়ে আমি স্বয়ংক্রিয়ভাবে:
• AI দিয়ে Script তৈরি করব
• Faceless Video বানাব (Shorts বা Long)
• ডেসক্রিপশনে অটো-অ্যাফিলিয়েট লিংক বসাব
• YouTube-এ Upload করব

✍️ নিচের ফরম্যাটে তথ্য পাঠাও:
`NICHE | HH:MM | TYPE`

• `TYPE` হতে পারে `short` অথবা `video`

উদাহরণ:
`AI Technology | 08:00 | video` (প্রতিদিন সকাল ৮টায় বড় ভিডিও)
`Motivation | 20:00 | short` (প্রতিদিন রাত ৮টায় শর্টস)
`Finance Tips | 12:30 | video`
    """
    sent = bot.send_message(chat_id, text, parse_mode='Markdown')
    bot.register_next_step_handler(sent, process_schedule_input)


def process_schedule_input(message):
    chat_id = message.chat.id
    text = message.text.strip()

    if text.startswith('/'):
        bot.send_message(chat_id, "❌ Schedule সেটআপ বাতিল।")
        return

    try:
        parts = [p.strip() for p in text.split('|')]
        if len(parts) < 2:
            raise ValueError("Format ঠিক নেই")

        niche = parts[0]
        time_parts = parts[1].split(':')
        hour = int(time_parts[0])
        minute = int(time_parts[1])

        is_short = False
        if len(parts) >= 3:
            is_short = parts[2].lower() == 'short'

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("সময় ঠিক নেই")

        session = get_session(chat_id)
        voice = session.get('voice', DEFAULT_VOICE)

        set_schedule(chat_id, hour, minute, niche, voice, is_short=is_short)

        type_label = "Shorts (Vertical)" if is_short else "Video (Landscape)"
        confirm = f"""
✅ *Auto-Upload Schedule সেট হয়েছে!*

📌 Niche: *{niche}*
⏰ সময়: *{hour:02d}:{minute:02d}* (প্রতিদিন)
🎬 ধরণ: *{type_label}*
🎤 Voice: *{VOICE_LABELS.get(voice, voice)}*
💸 Affiliate: *Enabled ✅*

🚀 Bot প্রতিদিন এই সময়ে নিজে নিজে সব বানিয়ে আপলোড করবে।

⛔ বন্ধ করতে: /stopschedule
        """
        bot.send_message(chat_id, confirm, parse_mode='Markdown')

    except Exception as e:
        bot.send_message(
            chat_id,
            f"❌ ফরম্যাট Error: {e}\n\nএভাবে পাঠাও:\n`AI Technology | 08:00 | video`",
            parse_mode='Markdown'
        )


@bot.message_handler(commands=['stopschedule'])
def handle_stop_schedule(message):
    chat_id = message.chat.id
    removed = remove_schedule(chat_id)
    if removed:
        bot.send_message(chat_id, "✅ Auto-Upload Schedule বন্ধ করা হয়েছে।")
    else:
        bot.send_message(chat_id, "⚠️ তোমার কোনো Active Schedule নেই।")


@bot.message_handler(commands=['mystatus'])
def handle_my_status(message):
    chat_id = message.chat.id
    sched = get_schedule(chat_id)

    if not sched:
        text = "📊 তোমার কোনো Auto-Schedule সেট নেই।\n`/autoschedule` দিয়ে সেট করো।"
    else:
        from datetime import datetime
        last = sched.get('last_run')
        last_str = datetime.fromisoformat(last).strftime('%Y-%m-%d %H:%M') if last else 'কোনোটি না'
        type_lbl = "Shorts 📱" if sched.get('is_short') else "Video 📺"
        text = f"""
📊 *তোমার Bot Status:*

📌 Niche: *{sched['niche']}*
🎬 Type: *{type_lbl}*
⏰ Schedule: *{sched['hour']:02d}:{sched['minute']:02d}* (প্রতিদিন)
🎤 Voice: *{VOICE_LABELS.get(sched.get('voice', DEFAULT_VOICE), 'English Female')}*
🎥 মোট তৈরি ভিডিও: *{sched.get('videos_created', 0)}*
🕐 সর্বশেষ Upload: *{last_str}*
✅ Status: *{'Active ✅' if sched.get('enabled') else 'Inactive ❌'}*
💸 Auto-Affiliate: *Active*
        """
    bot.send_message(chat_id, text, parse_mode='Markdown')


# ╔══════════════════════════════════════════════════════════╗
# ║          AFFILIATE MANAGEMENT                            ║
# ╚══════════════════════════════════════════════════════════╝

@bot.message_handler(commands=['affiliate'])
def handle_affiliate(message):
    chat_id = message.chat.id
    text = """
💸 *Custom Affiliate Link সেটিংস*

তুমি চাইলে নিজের কাস্টম Amazon, Fiverr বা অন্য যেকোনো অ্যাফিলিয়েট লিংক বটের সাথে সেট করতে পারো। 

নিচের ফরম্যাটে তথ্য পাঠাও:
`NICHE | PRODUCT_NAME | URL | DESCRIPTION`

* ক্যাটাগরিগুলো (NICHE) হতে পারে: `AI`, `Finance`, `Motivation`, `Tech`, `General`

উদাহরণ:
`AI | Jasper AI Copywriter | https://jasper.ai?special_ref | AI writing tool with free trial`
    """
    sent = bot.send_message(chat_id, text, parse_mode='Markdown')
    bot.register_next_step_handler(sent, process_affiliate_input)


def process_affiliate_input(message):
    chat_id = message.chat.id
    text = message.text.strip()

    if text.startswith('/'):
        bot.send_message(chat_id, "❌ কাস্টম অ্যাফিলিয়েট সেটআপ বাতিল।")
        return

    try:
        parts = [p.strip() for p in text.split('|')]
        if len(parts) < 3:
            raise ValueError("অন্তত NICHE, PRODUCT_NAME এবং URL দিতে হবে।")

        niche = parts[0]
        prod_name = parts[1]
        url = parts[2]
        desc = parts[3] if len(parts) >= 4 else ""

        save_link(niche, prod_name, url, desc)
        bot.send_message(chat_id, f"✅ সফলভাবে `{niche}` ক্যাটাগরির জন্য কাস্টম লিংক সেট হয়েছে!\n\n👉 *{prod_name}*: {url}")
    except Exception as e:
        bot.send_message(chat_id, f"❌ সেট করতে সমস্যা হয়েছে: {e}\n\nফরম্যাট ঠিক রেখে আবার চেষ্টা করো।")


# ╔══════════════════════════════════════════════════════════╗
# ║          VOICE SELECTION                                 ║
# ╚══════════════════════════════════════════════════════════╝

@bot.message_handler(commands=['voices'])
def handle_voices(message):
    chat_id = message.chat.id
    session = get_session(chat_id)
    current = session.get('voice', DEFAULT_VOICE)

    markup = InlineKeyboardMarkup(row_width=1)
    for key, label in VOICE_LABELS.items():
        btn_text = f"✅ {label}" if key == current else label
        markup.add(InlineKeyboardButton(btn_text, callback_data=f"voice_{key}"))

    bot.send_message(
        chat_id,
        f"🎤 *Narration Voice বেছে নাও:*\n\n_(বর্তমান: {VOICE_LABELS.get(current, current)})_",
        reply_markup=markup,
        parse_mode='Markdown'
    )


# ╔══════════════════════════════════════════════════════════╗
# ║          TOPIC SUGGESTIONS                               ║
# ╚══════════════════════════════════════════════════════════╝

@bot.message_handler(commands=['topics'])
def handle_topics(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "🤖 AI দিয়ে সেরা Trending Topic suggestions তৈরি হচ্ছে...")

    thread = threading.Thread(target=_generate_topics, args=(chat_id,), daemon=True)
    thread.start()


def _generate_topics(chat_id: int):
    from google import genai
    client = genai.Client()
    prompt = """
You are a YouTube income expert. List 15 HIGH-INCOME faceless YouTube video topics for 2025.
For each topic:
- Category name
- 3 specific video ideas under it
- Why it's profitable (briefly)

Focus on: AI, Finance, Motivation, Facts, Health, Technology.
Format nicely with emojis. Keep it concise but actionable.
    """
    try:
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        result = response.text
        if len(result) > 4000:
            for i in range(0, len(result), 4000):
                bot.send_message(chat_id, result[i:i+4000])
        else:
            bot.send_message(chat_id, result)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {e}")


# ╔══════════════════════════════════════════════════════════╗
# ║          INCOME ROADMAP                                  ║
# ╚══════════════════════════════════════════════════════════╝

@bot.message_handler(commands=['income'])
def handle_income(message):
    chat_id = message.chat.id
    text = """
💰 *২ মাসে ৫০,০০০ টাকা আয়ের পূর্ণাঙ্গ গাইডলাইন!*

বট তো রেডি, এখন দরকার সঠিক স্ট্র্যাটেজি। এই রোডম্যাপটি ফলো করলে তুমি ২ মাসে ৫০ হাজার টাকা আয়ের টার্গেট পূরণ করতে পারবে:

━━━━━━━━━━━━━━━━━━━━
📅 *১-১৫ দিন: ফাউন্ডেশন ও ফাস্ট ট্র্যাকিং*
✅ প্রতিদিন বটের শিডিউলার ব্যবহার করে ২টি Shorts ও ১টি Long Video আপলোড করো।
✅ ক্যাটাগরি হিসেবে `AI Tech` অথবা `Finance Tips` বেছে নাও (এগুলোতে আয়ের সুযোগ সবচেয়ে বেশি)।
✅ ডেসক্রিপশনে বটের ডিফল্ট অ্যাফিলিয়েট লিংকগুলো সচল রাখো।
🎯 লক্ষ্য: প্রথম ৫০০ সাবস্ক্রাইবার ও প্রাথমিক ট্রাফিক।

━━━━━━━━━━━━━━━━━━━━
📅 *১৬-৩০ দিন: অ্যাফিলিয়েট সেলস স্টার্ট*
✅ বট দিয়ে প্রতিদিন হাই-কোয়ালিটি ভিডিও রেডি করো।
✅ কমেন্ট বক্সে তোমার লিংকের ওপর ফোকাস করতে বলো (যেমন: "ভিডিওর টুলসগুলোর ফ্রি ট্রায়াল লিংক প্রথম কমেন্টে আছে!")।
✅ `/affiliate` দিয়ে তোমার নিজস্ব কাস্টম আমাজন বা ফাইবার অ্যাফিলিয়েট লিংক অ্যাড করো।
🎯 লক্ষ্য: প্রতিদিন অন্তত ২-৩ ডলার ডিরেক্ট অ্যাফিলিয়েট সেলস থেকে ইনকাম শুরু।

━━━━━━━━━━━━━━━━━━━━
📅 *৩১-৪৫ দিন: বুস্টিং ও রিচ*
✅ বটের `/stats` চেক করে দেখবে এআই কী সাজেশন দিচ্ছে। যে ভিডিওতে ভিউ বেশি, বটকে ওই রিলেটেড টপিক বেশি দিতে বলবে।
✅ বড় ভিডিওগুলো ৮ মিনিটের বেশি বানাবে, যাতে বেশি বিজ্ঞাপন বসানো যায়।
🎯 লক্ষ্য: প্রথম অ্যাফিলিয়েট পে-আউট (১০০$-১৫০$) এবং মনিটাইজেশনের কাছাকাছি পৌঁছানো।

━━━━━━━━━━━━━━━━━━━━
📅 *৪৬-৬০ দিন: মনিটাইজেশন ও ফিক্সড ইনকাম*
✅ চ্যানেলে ১০০০ সাবস্ক্রাইবার ও ওয়াচ আওয়ার শেষ হলে YouTube Partner Program-এ অ্যাপ্লাই করো।
✅ এখন অ্যাডসেন্স রেভিনিউ + অ্যাফিলিয়েট ইনকাম দুটোই একসাথে চালু হবে।
🎯 লক্ষ্য: ২ মাসের মাথায় টোটাল ৫০,০০০ টাকা আয়ের মাইলফলক স্পর্শ করা!

🚀 শুরু করতে এখনই প্রথম ভিডিও বানাও: `/create AI tools to make money`
    """
    bot.send_message(chat_id, text, parse_mode='Markdown')


# ╔══════════════════════════════════════════════════════════╗
# ║          CHANNEL STATS                                   ║
# ╚══════════════════════════════════════════════════════════╝

@bot.message_handler(commands=['stats'])
def handle_stats(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "📊 Channel Analytics লোড হচ্ছে...")

    stats = get_channel_stats()
    if not stats:
        bot.send_message(chat_id, "❌ YouTube channel কানেক্ট নেই। /auth দিয়ে কানেক্ট করো।")
        return

    stats_text = f"""
📈 *Channel Analytics:*
🏷️ চ্যানেল: *{stats['channel_title']}*
👥 Subscribers: *{int(stats['subscriber_count']):,}*
👁️ Total Views: *{int(stats['view_count']):,}*
🎥 Total Videos: *{stats['video_count']}*
    """
    bot.send_message(chat_id, stats_text, parse_mode='Markdown')

    bot.send_message(chat_id, "🤖 AI Growth Analysis তৈরি হচ্ছে...")
    tips = analyze_and_suggest_growth(stats)
    if len(tips) > 4000:
        for i in range(0, len(tips), 4000):
            bot.send_message(chat_id, tips[i:i+4000], parse_mode='Markdown')
    else:
        bot.send_message(chat_id, tips, parse_mode='Markdown')


# ╔══════════════════════════════════════════════════════════╗
# ║          SCRIPT GENERATION                               ║
# ╚══════════════════════════════════════════════════════════╝

@bot.message_handler(commands=['script'])
def handle_script(message):
    chat_id = message.chat.id
    topic = message.text.replace('/script', '').strip()

    if not topic:
        sent = bot.send_message(chat_id, "✍️ কোন টপিকে Script লিখব? লিখো:")
        bot.register_next_step_handler(sent, process_script_topic)
        return

    _generate_and_send_script(chat_id, topic)


def process_script_topic(message):
    chat_id = message.chat.id
    topic = message.text.strip()
    if topic.startswith('/'):
        bot.send_message(chat_id, "❌ বাতিল।")
        return
    _generate_and_send_script(chat_id, topic)


def _generate_and_send_script(chat_id: int, topic: str):
    bot.send_message(chat_id, f"🧠 Gemini AI দিয়ে *'{topic}'* এর Script তৈরি হচ্ছে...", parse_mode='Markdown')
    script = generate_script(topic)
    seo = generate_seo_meta(script)
    get_session(chat_id)['last_seo'] = seo

    if len(script) > 4000:
        for i in range(0, len(script), 4000):
            bot.send_message(chat_id, script[i:i+4000])
    else:
        bot.send_message(chat_id, script)

    bot.send_message(
        chat_id,
        "💡 Script তৈরি! এখন `/video` দিয়ে এই script থেকে Video বানাও অথবা `/thumbnail` দিয়ে থাম্বনেইল তৈরি করো!",
        parse_mode='Markdown'
    )


@bot.message_handler(commands=['story'])
def handle_story(message):
    chat_id = message.chat.id
    topic = message.text.replace('/story', '').strip()

    if not topic:
        sent = bot.send_message(chat_id, "✍️ কোন টপিক বা বিষয়ের ওপর গল্প (Story) লিখব? টপিকটি লিখো:")
        bot.register_next_step_handler(sent, process_story_topic)
        return

    _generate_and_send_story(chat_id, topic)


def process_story_topic(message):
    chat_id = message.chat.id
    topic = message.text.strip()
    if topic.startswith('/'):
        bot.send_message(chat_id, "❌ বাতিল।")
        return
    _generate_and_send_story(chat_id, topic)


def _generate_and_send_story(chat_id: int, topic: str):
    bot.send_message(chat_id, f"🧠 Gemini AI দিয়ে *'{topic}'* এর গল্প তৈরি হচ্ছে...", parse_mode='Markdown')
    script = generate_script(topic)
    seo = generate_seo_meta(script)
    session = get_session(chat_id)
    session['last_seo'] = seo
    session['last_script'] = script
    session['last_topic'] = topic

    if len(script) > 4000:
        for i in range(0, len(script), 4000):
            bot.send_message(chat_id, script[i:i+4000])
    else:
        bot.send_message(chat_id, script)

    bot.send_message(
        chat_id,
        "💡 গল্প তৈরি হয়েছে!\n\n🎬 এখন `/video` দিয়ে এই গল্প থেকে ভিডিও বানাও, অথবা `/thumbnail` দিয়ে থাম্বনেইল তৈরি করো।",
        parse_mode='Markdown'
    )


@bot.message_handler(commands=['video'])
def handle_video(message):
    chat_id = message.chat.id
    topic_or_script = message.text.replace('/video', '').strip()
    session = get_session(chat_id)

    script = session.get('last_script')
    topic = session.get('last_topic', 'My Story')

    if not script:
        if not topic_or_script:
            sent = bot.send_message(
                chat_id, 
                "🎬 আপনি কি নিয়ে ভিডিও বানাতে চান? টপিক বা পুরো স্ক্রিপ্টটি চ্যাটে লিখুন:"
            )
            bot.register_next_step_handler(sent, process_video_generation)
            return
        else:
            topic = topic_or_script[:50]
            script = topic_or_script
            
    import threading
    threading.Thread(
        target=_full_video_pipeline,
        args=(chat_id, topic, False, script),
        daemon=True
    ).start()


def process_video_generation(message):
    chat_id = message.chat.id
    topic_or_script = message.text.strip()
    if topic_or_script.startswith('/'):
        bot.send_message(chat_id, "❌ বাতিল।")
        return
        
    topic = topic_or_script[:50]
    script = topic_or_script
    
    import threading
    threading.Thread(
        target=_full_video_pipeline,
        args=(chat_id, topic, False, script),
        daemon=True
    ).start()


@bot.message_handler(commands=['thumbnail'])
def handle_thumbnail_cmd(message):
    chat_id = message.chat.id
    provided_title = message.text.replace('/thumbnail', '').strip()
    session = get_session(chat_id)
    
    seo = session.get('last_seo', {})
    title = provided_title if provided_title else seo.get('title', 'My Video')
    topic = session.get('last_topic', 'AI Video')
    
    bot.send_message(chat_id, f"🖼️ *'{title}'* এর জন্য থাম্বনেইল তৈরি হচ্ছে...", parse_mode='Markdown')
    try:
        thumb_path = f"thumb_{int(time.time())}.jpg"
        create_thumbnail(title=title, topic=topic[:20], output_path=thumb_path)
        if os.path.exists(thumb_path):
            with open(thumb_path, 'rb') as f:
                bot.send_photo(chat_id, f, caption="🎉 আপনার থাম্বনেইল তৈরি সম্পন্ন হয়েছে!")
            try:
                os.remove(thumb_path)
            except Exception:
                pass
        else:
            bot.send_message(chat_id, "❌ থাম্বনেইল ফাইল তৈরি হতে সমস্যা হয়েছে।")
    except Exception as e:
        bot.send_message(chat_id, f"❌ থাম্বনেইল তৈরি ব্যর্থ: {e}")


# ╔══════════════════════════════════════════════════════════╗
# ║          MANUAL VIDEO UPLOAD                             ║
# ╚══════════════════════════════════════════════════════════╝

@bot.message_handler(commands=['upload'])
def handle_upload_instruction(message):
    bot.send_message(
        message.chat.id,
        "📤 Manual Upload:\n\nসরাসরি চ্যাটে একটি *.mp4* ভিডিও ফাইল পাঠাও (সর্বোচ্চ ২০MB)। আমি সেটি YouTube-এ upload করে দেব।",
        parse_mode='Markdown'
    )


@bot.message_handler(content_types=['video', 'document'])
def handle_video_upload(message):
    chat_id = message.chat.id

    youtube = get_youtube_service()
    if not youtube:
        bot.send_message(chat_id, "❌ প্রথমে /auth দিয়ে YouTube Channel কানেক্ট করো।")
        return

    video = None
    if message.content_type == 'video':
        video = message.video
    elif message.content_type == 'document' and message.document.mime_type.startswith('video/'):
        video = message.document

    if not video:
        bot.send_message(chat_id, "❌ শুধু ভিডিও ফাইল পাঠাও।")
        return

    if video.file_size > 20971520:
        bot.send_message(chat_id, "⚠️ ফাইল ২০MB-এর বেশি! ছোট করে পাঠাও।")
        return

    bot.send_message(chat_id, "⏳ ভিডিও ডাউনলোড হচ্ছে...")

    try:
        file_info = bot.get_file(video.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        ext = file_info.file_path.split('.')[-1]
        temp_filename = f"temp_{chat_id}.{ext}"

        with open(temp_filename, 'wb') as f:
            f.write(downloaded_file)

        session = get_session(chat_id)
        session['video_path'] = temp_filename

        markup = InlineKeyboardMarkup()
        if session['last_seo']:
            markup.add(InlineKeyboardButton("🤖 AI জেনারেটেড Title ব্যবহার করো", callback_data="use_ai_title"))
        markup.add(InlineKeyboardButton("✏️ নিজে Title লিখো", callback_data="input_custom_title"))

        bot.send_message(chat_id, "✅ ডাউনলোড সম্পন্ন! ভিডিওর Title বেছে নাও:", reply_markup=markup)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {e}")


# ╔══════════════════════════════════════════════════════════╗
# ║          CALLBACK QUERY HANDLER                          ║
# ╚══════════════════════════════════════════════════════════╝

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    chat_id = call.message.chat.id
    session = get_session(chat_id)

    # ── Voice selection ──────────────────────────────────────────────────────
    if call.data.startswith("voice_"):
        voice_key = call.data.replace("voice_", "")
        from video_creator import VOICES
        if voice_key in VOICES:
            session['voice'] = voice_key
            bot.answer_callback_query(call.id, f"✅ Voice পরিবর্তিত: {VOICE_LABELS.get(voice_key, voice_key)}")
            bot.edit_message_text(
                f"✅ Narration Voice সেট হয়েছে:\n*{VOICE_LABELS.get(voice_key, voice_key)}*",
                chat_id, call.message.message_id, parse_mode='Markdown'
            )
        return

    # ── Manual upload title ──────────────────────────────────────────────────
    if call.data == "use_ai_title":
        if session['last_seo']:
            session['video_title'] = session['last_seo']['title']
            session['video_desc'] = session['last_seo']['description']
            session['video_tags'] = session['last_seo']['tags']
            show_privacy_options(chat_id)
        else:
            bot.send_message(chat_id, "❌ AI data নেই। নিজে title লিখো।")
            ask_custom_title(chat_id)

    elif call.data == "input_custom_title":
        ask_custom_title(chat_id)

    elif call.data.startswith("privacy_"):
        privacy = call.data.split("_")[1]
        if not session.get('video_path'):
            bot.send_message(chat_id, "❌ কোনো ভিডিও নেই। আবার পাঠাও।")
            return
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        threading.Thread(
            target=perform_youtube_upload,
            args=(chat_id, privacy),
            daemon=True
        ).start()


def ask_custom_title(chat_id):
    sent = bot.send_message(chat_id, "✍️ ভিডিওর Title লিখো:")
    bot.register_next_step_handler(sent, process_custom_title)


def process_custom_title(message):
    chat_id = message.chat.id
    title = message.text.strip()
    if title.startswith('/'):
        bot.send_message(chat_id, "❌ বাতিল।")
        return
    session = get_session(chat_id)
    session['video_title'] = title
    sent = bot.send_message(chat_id, "✍️ Description লিখো (অথবা /skip):")
    bot.register_next_step_handler(sent, process_custom_desc)


def process_custom_desc(message):
    chat_id = message.chat.id
    desc = message.text.strip()
    session = get_session(chat_id)
    session['video_desc'] = "" if desc == '/skip' else desc
    sent = bot.send_message(chat_id, "✍️ Tags লিখো (comma দিয়ে) অথবা /skip:")
    bot.register_next_step_handler(sent, process_custom_tags)


def process_custom_tags(message):
    chat_id = message.chat.id
    tags_text = message.text.strip()
    session = get_session(chat_id)
    session['video_tags'] = [] if tags_text == '/skip' else [t.strip() for t in tags_text.split(",") if t.strip()]
    show_privacy_options(chat_id)


def show_privacy_options(chat_id):
    session = get_session(chat_id)
    text = f"""
📁 *Upload Confirmation:*
📌 Title: {session.get('video_title', 'N/A')}
📝 Desc: {(session.get('video_desc') or '')[:150]}...
🏷️ Tags: {', '.join(session.get('video_tags', [])[:5]) or 'নেই'}

Privacy বেছে নাও:
    """
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("🔒 Private", callback_data="privacy_private"),
        InlineKeyboardButton("🔗 Unlisted", callback_data="privacy_unlisted"),
        InlineKeyboardButton("👁️ Public", callback_data="privacy_public")
    )
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')


def perform_youtube_upload(chat_id, privacy):
    session = get_session(chat_id)
    file_path = session.get('video_path')
    title = session.get('video_title', 'My Video')
    desc = session.get('video_desc', '')
    tags = session.get('video_tags', [])

    bot.send_message(chat_id, f"🚀 YouTube-এ Upload হচ্ছে... ({privacy.capitalize()} mode)\nঅনুগ্রহ করে অপেক্ষা করো।")

    try:
        video_id = upload_video(file_path=file_path, title=title, description=desc, tags=tags, privacy_status=privacy)
        bot.send_message(
            chat_id,
            f"🎉 *Upload সম্পন্ন!*\n\n🔗 https://youtu.be/{video_id}\n⚙️ Status: *{privacy.upper()}*",
            parse_mode='Markdown'
        )
    except Exception as e:
        bot.send_message(chat_id, f"❌ Upload Error: {e}")
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        session['video_path'] = None


# ╔══════════════════════════════════════════════════════════╗
# ║          AUTO-SCHEDULE BACKGROUND WORKER                 ║
# ╚══════════════════════════════════════════════════════════╝

def _auto_schedule_worker():
    """Runs every minute and triggers due schedules."""
    import time as _time
    while True:
        try:
            due = get_due_schedules()
            for sched in due:
                chat_id = sched.get('chat_id')
                mark_run(chat_id)
                niche = sched.get('niche', 'AI Technology')
                voice = sched.get('voice', DEFAULT_VOICE)
                is_short = sched.get('is_short', False)

                bot.send_message(
                    chat_id,
                    f"⏰ *Auto-Schedule Triggered!*\n\n"
                    f"📌 Niche: *{niche}*\n"
                    f"🤖 AI topic বেছে Video তৈরি শুরু হচ্ছে...",
                    parse_mode='Markdown'
                )

                # Generate a fresh topic using Gemini
                threading.Thread(
                    target=_auto_create_and_upload,
                    args=(chat_id, niche, voice, is_short),
                    daemon=True
                ).start()

        except Exception as e:
            print(f"[Scheduler] Error: {e}")

        _time.sleep(60)  # Check every minute


def _auto_create_and_upload(chat_id: int, niche: str, voice: str, is_short: bool):
    """Pick a trending topic and run the full video pipeline."""
    from google import genai
    try:
        client = genai.Client()
        prompt = f"""
        You are a viral YouTube automation research bot. 
        Analyze the current YouTube trends, high retention formats, and high-CPM categories for the niche: "{niche}".
        
        Generate ONE highly clickbait, viral, and psychological-hook based video topic.
        It must be something that people immediately want to click when they see it on their feed.
        
        Rules:
        - Return ONLY the video title/topic.
        - Do NOT write quotes, intros, or markdown formatting around it.
        - Keep it under 80 characters.
        
        Example outputs for "Finance": "How to Turn $100 into $5000 (The Lazy Way)"
        Example outputs for "AI": "5 AI Tools That Will Make You Rich in 2026"
        """
        resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        topic = resp.text.strip().strip('"').strip("'").strip("`").strip()[:100]
    except Exception:
        topic = f"{niche} Secrets You Weren't Supposed to Know"

    session = get_session(chat_id)
    session['voice'] = voice

    bot.send_message(chat_id, f"🎯 Auto-Topic: *{topic}*", parse_mode='Markdown')
    _full_video_pipeline(chat_id, topic, is_short)


# ╔══════════════════════════════════════════════════════════╗
# ║          BUTTON CLICKS HANDLER                           ║
# ╚══════════════════════════════════════════════════════════╝

@bot.message_handler(func=lambda message: message.text in [
    "🎬 Create Video",
    "📅 Auto-Post Schedule",
    "📊 Grow Channel"
])
def handle_button_clicks(message):
    chat_id = message.chat.id
    text = message.text
    
    if text == "🎬 Create Video":
        sent = bot.send_message(
            chat_id,
            "✍️ **ভিডিওর টপিক অথবা আপনার নিজের গল্পটি লিখুন:**\n\n"
            "• আপনি চাইলে শুধু টপিক লিখতে পারেন (যেমন: `মহাকাশের রহস্য`)\n"
            "• অথবা আপনার পুরো গল্পটি এখানে লিখতে পারেন।",
            parse_mode='Markdown'
        )
        def _handle_unified_creation(m):
            user_input = m.text.strip()
            if user_input.startswith('/'):
                bot.send_message(m.chat.id, "❌ বাতিল করা হয়েছে।")
                return
                
            # If the user input is long or contains sentence ends, treat as Story Mode
            if len(user_input) > 45 or any(c in user_input for c in ["।", "\n", "\r", "?", "!"]):
                bot.send_message(m.chat.id, "✅ গল্প পেয়েছি! এআই দিয়ে ভিডিও তৈরি শুরু হচ্ছে...\n\n⏳ অনুগ্রহ করে অপেক্ষা করুন (৩-৫ মিনিট)")
                _full_video_pipeline(m.chat.id, user_input[:40], is_short=False, custom_script=user_input)
            else:
                _start_video_creation(m.chat.id, user_input, is_short=False)
                
        bot.register_next_step_handler(sent, _handle_unified_creation)
        
    elif text == "📅 Auto-Post Schedule":
        handle_autoschedule(message)
        
    elif text == "📊 Grow Channel":
        handle_stats(message)


# ╔══════════════════════════════════════════════════════════╗
# ║          FALLBACK & MAIN                                 ║
# ╚══════════════════════════════════════════════════════════╝

@bot.message_handler(func=lambda message: True)
def fallback_text(message):
    bot.reply_to(
        message,
        "আমি বুঝতে পারিনি। চ্যাটের নিচের বাটনগুলো ক্লিক করে কাজ শুরু করতে পারো অথবা সাহায্যের জন্য /help লিখো।",
        parse_mode='Markdown'
    )


if __name__ == '__main__':
    print("=" * 50)
    print("  YouTube AI Income Bot Starting...")
    print("=" * 50)

    # Start auto-schedule background worker
    schedule_thread = threading.Thread(target=_auto_schedule_worker, daemon=True)
    schedule_thread.start()
    print("[✓] Auto-Schedule worker started")

    print("[✓] Bot is running! Waiting for messages...")
    bot.infinity_polling()
