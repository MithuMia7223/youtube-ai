import os
import io
import time
import telebot
from dotenv import load_dotenv
from google.genai import errors
from chatbot import AIChatbot

# Load env variables from local .env inside the project folder
load_dotenv()

BOT_TOKEN = os.getenv("CHATBOT_TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    print("[ERROR] TELEGRAM_BOT_TOKEN is not set in the .env file!")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)
chatbot_engine = AIChatbot(language="bangla")
user_sessions = {}
user_language = {}  # Tracks language preference per user: "auto", "bangla", "english"


def safe_send_message(chat_id, text, **kwargs):
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except telebot.apihelper.ApiTelegramException as e:
        if "parse entities" in str(e) or "can't parse" in str(e):
            kwargs.pop('parse_mode', None)
            return bot.send_message(chat_id, text, **kwargs)
        raise e

def send_to_gemini_with_retry(chat_session, text_or_content, chat_id, max_retries=3):
    """
    Sends a message to Gemini with automatic retry on quota exceeded errors.
    """
    for attempt in range(max_retries):
        try:
            response = chat_session.send_message(text_or_content)
            return response
        except errors.ClientError as e:
            err_str = str(e)
            if '429' in err_str or 'RESOURCE_EXHAUSTED' in err_str or 'quota' in err_str.lower():
                # Extract retry delay if available
                wait_time = 10 * (attempt + 1)  # 10s, 20s, 30s
                if attempt < max_retries - 1:
                    safe_send_message(
                        chat_id,
                        f"⏳ *Rate limit reached.* Free tier allows 20 requests/min.\n"
                        f"Retrying in {wait_time} seconds... (Attempt {attempt + 1}/{max_retries})",
                        parse_mode='Markdown'
                    )
                    time.sleep(wait_time)
                else:
                    safe_send_message(
                        chat_id,
                        "⚠️ *Gemini API Quota Exceeded!*\n\n"
                        "You have hit the free tier limit (20 requests/min).\n"
                        "Please wait 1 minute and try again, or upgrade your Gemini API plan.\n\n"
                        "🔗 Check usage: https://ai.dev/rate-limit",
                        parse_mode='Markdown'
                    )
                    return None
            else:
                raise e
    return None

# Allowed admin username
ADMIN_USERNAMES = ['Mdmithun731']

def is_admin(username):
    if not username:
        return False
    return username.lower() in [admin.lower() for admin in ADMIN_USERNAMES]

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    chat_id = message.chat.id
    if not is_admin(message.from_user.username):
        safe_send_message(chat_id, "❌ Access Denied: You are not authorized to use this bot.")
        return

    lang = user_language.get(chat_id, "bangla")
    
    # Create session with correct language mode
    from chatbot import AIChatbot as _AIChatbot
    engine = _AIChatbot(language=lang)
    user_sessions[chat_id] = {
        'chat_session': engine.create_session(),
        'engine': engine
    }
    
    if lang == "bangla":
        welcome_text = (
            "🤖 *স্বাগতম আপনার Advanced AI Chatbot এ!*\n\n"
            "আমি আপনার প্রশ্নের উত্তর দিতে এবং বিভিন্ন কাজে সাহায্য করতে পারি।\n\n"
            "👉 *আমি যা করতে পারি:*\n"
            "• 📄 PDF বিশ্লেষণ (যেকোনো PDF পাঠান)\n"
            "• 📷 ছবি বোঝা (যেকোনো ছবি পাঠান)\n"
            "• 🔗 ওয়েব লিংক থেকে তথ্য পড়া\n"
            "• 📧 Gmail দিয়ে ইমেইল পাঠানো\n"
            "• 📊 Google Sheets আপডেট করা\n"
            "• 📅 Google Calendar এ ইভেন্ট তৈরি করা\n"
            "• 💾 ক্লায়েন্ট লিড সেভ করা\n\n"
            "🌐 *ভাষা পরিবর্তন করুন:*\n"
            "• /bangla — সবসময় বাংলায় উত্তর\n"
            "• /english — সবসময় ইংরেজিতে উত্তর\n"
            "• /auto — ভাষা স্বয়ংক্রিয়ভাবে detect করবে\n\n"
            "আমাকে একটি বার্তা পাঠান! `/reset` টাইপ করলে কথোপকথনের ইতিহাস মুছে যাবে।"
        )
    else:
        welcome_text = (
            "🤖 *Welcome to your Advanced AI Agent Chatbot!*\n\n"
            "I can answer your questions, assist you with tasks, and perform agent actions.\n\n"
            "👉 *What I can do:*\n"
            "• 📄 PDF Analysis (send any PDF)\n"
            "• 📷 Image Understanding (send any photo)\n"
            "• 🔗 Read content from web links\n"
            "• 📧 Send emails using Gmail\n"
            "• 📊 Update Google Sheets\n"
            "• 📅 Create Google Calendar events\n"
            "• 💾 Save client leads locally\n\n"
            "🌐 *Change Language:*\n"
            "• /bangla — Always reply in Bangla\n"
            "• /english — Always reply in English\n"
            "• /auto — Auto-detect your language\n\n"
            "Send me a message to get started! Type `/reset` to clear the conversation memory."
        )
    safe_send_message(chat_id, welcome_text, parse_mode='Markdown')


@bot.message_handler(commands=['reset'])
def handle_reset(message):
    chat_id = message.chat.id
    if not is_admin(message.from_user.username):
        safe_send_message(chat_id, "❌ Access Denied: You are not authorized to use this bot.")
        return

    try:
        lang = user_language.get(chat_id, "bangla")
        from chatbot import AIChatbot as _AIChatbot
        engine = _AIChatbot(language=lang)
        user_sessions[chat_id] = {
            'chat_session': engine.create_session(),
            'engine': engine
        }
        if lang == "bangla":
            safe_send_message(chat_id, "🧹 *কথোপকথনের ইতিহাস মুছে ফেলা হয়েছে!* নতুন করে শুরু করুন।", parse_mode='Markdown')
        else:
            safe_send_message(chat_id, "🧹 *Conversation history has been reset!* Ready to start fresh.", parse_mode='Markdown')
    except Exception as e:
        safe_send_message(chat_id, f"❌ Failed to reset chat: {e}")

@bot.message_handler(commands=['bangla'])
def set_bangla(message):
    chat_id = message.chat.id
    if not is_admin(message.from_user.username):
        safe_send_message(chat_id, "❌ Access Denied.")
        return
    user_language[chat_id] = "bangla"
    from chatbot import AIChatbot as _AIChatbot
    engine = _AIChatbot(language="bangla")
    user_sessions[chat_id] = {'chat_session': engine.create_session(), 'engine': engine}
    safe_send_message(chat_id, "✅ *ভাষা পরিবর্তন হয়েছে!* এখন থেকে আমি সবসময় বাংলায় উত্তর দেব। 🇧🇩", parse_mode='Markdown')

@bot.message_handler(commands=['english'])
def set_english(message):
    chat_id = message.chat.id
    if not is_admin(message.from_user.username):
        safe_send_message(chat_id, "❌ Access Denied.")
        return
    user_language[chat_id] = "english"
    from chatbot import AIChatbot as _AIChatbot
    engine = _AIChatbot(language="english")
    user_sessions[chat_id] = {'chat_session': engine.create_session(), 'engine': engine}
    safe_send_message(chat_id, "✅ *Language changed!* I will now always respond in English. 🇬🇧", parse_mode='Markdown')

@bot.message_handler(commands=['auto'])
def set_auto(message):
    chat_id = message.chat.id
    if not is_admin(message.from_user.username):
        safe_send_message(chat_id, "❌ Access Denied.")
        return
    user_language[chat_id] = "auto"
    from chatbot import AIChatbot as _AIChatbot
    engine = _AIChatbot(language="auto")
    user_sessions[chat_id] = {'chat_session': engine.create_session(), 'engine': engine}
    safe_send_message(chat_id, "✅ *Auto mode enabled!* I will now detect your language automatically.\n✅ *অটো মোড চালু!* এখন ভাষা স্বয়ংক্রিয়ভাবে বোঝা যাবে। 🌐", parse_mode='Markdown')

@bot.message_handler(commands=['language'])
def show_language(message):
    chat_id = message.chat.id
    if not is_admin(message.from_user.username):
        safe_send_message(chat_id, "❌ Access Denied.")
        return
    lang = user_language.get(chat_id, "bangla")
    lang_display = {"bangla": "🇧🇩 বাংলা (Bangla)", "english": "🇬🇧 English", "auto": "🌐 Auto-detect"}
    safe_send_message(
        chat_id,
        f"🌐 *Current Language Mode:* {lang_display.get(lang, 'Auto')}\n\n"
        f"Change with:\n• /bangla\n• /english\n• /auto",
        parse_mode='Markdown'
    )


# Text Handler
@bot.message_handler(func=lambda msg: True)
def handle_text_messages(message):
    chat_id = message.chat.id
    if not is_admin(message.from_user.username):
        safe_send_message(chat_id, "❌ Access Denied: You are not authorized to use this bot.")
        return

    text = message.text.strip()
    if text.startswith('/'):
        return

    if chat_id not in user_sessions:
        lang = user_language.get(chat_id, "bangla")
        from chatbot import AIChatbot as _AIChatbot
        engine = _AIChatbot(language=lang)
        user_sessions[chat_id] = {
            'chat_session': engine.create_session(),
            'engine': engine
        }

    bot.send_chat_action(chat_id, 'typing')
    
    try:
        chat_session = user_sessions[chat_id]['chat_session']
        response = send_to_gemini_with_retry(chat_session, text, chat_id)
        if response:
            safe_send_message(chat_id, response.text, parse_mode='Markdown')
    except errors.APIError as e:
        safe_send_message(chat_id, f"⚠️ *Gemini API Error:* {e.message}", parse_mode='Markdown')
    except Exception as e:
        safe_send_message(chat_id, f"❌ Sorry, an error occurred: {e}")

# Photo and Document Handler
@bot.message_handler(content_types=['photo', 'document'])
def handle_multimodal_messages(message):
    chat_id = message.chat.id
    if not is_admin(message.from_user.username):
        safe_send_message(chat_id, "❌ Access Denied: You are not authorized to use this bot.")
        return

    if chat_id not in user_sessions:
        try:
            lang = user_language.get(chat_id, "bangla")
            from chatbot import AIChatbot as _AIChatbot
            engine = _AIChatbot(language=lang)
            user_sessions[chat_id] = {
                'chat_session': engine.create_session(),
                'engine': engine
            }
        except Exception as e:
            safe_send_message(chat_id, f"❌ Failed to start AI session: {e}")
            return

    try:
        # Photo Upload
        if message.content_type == 'photo':
            from PIL import Image
            
            bot.send_chat_action(chat_id, 'upload_photo')
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            image = Image.open(io.BytesIO(downloaded_file))
            
            caption = message.caption or "Analyze this image."
            bot.send_chat_action(chat_id, 'typing')
            
            chat_session = user_sessions[chat_id]['chat_session']
            response = send_to_gemini_with_retry(chat_session, [image, caption], chat_id)
            if response:
                safe_send_message(chat_id, response.text, parse_mode='Markdown')
            
        # PDF Document Upload
        elif message.content_type == 'document':
            import pypdf
            
            file_name = message.document.file_name
            if not file_name.lower().endswith('.pdf'):
                safe_send_message(chat_id, "⚠️ Sorry, I can only analyze PDF documents in chat mode.")
                return
            
            safe_send_message(chat_id, "⏳ Downloading and reading the PDF file...")
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            
            pdf_file = io.BytesIO(downloaded_file)
            reader = pypdf.PdfReader(pdf_file)
            
            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            
            if not text.strip():
                safe_send_message(chat_id, "⚠️ No readable text found in the PDF. It might be a scanned image PDF.")
                return
            
            prompt = (
                f"User uploaded a PDF document named '{file_name}'. Here is the text content extracted from it:\n\n"
                f"{text[:15000]}\n\n"
                f"Please analyze this document content. Let the user know you read it and summarize or answer questions they ask about it."
            )
            
            bot.send_chat_action(chat_id, 'typing')
            chat_session = user_sessions[chat_id]['chat_session']
            response = send_to_gemini_with_retry(chat_session, prompt, chat_id)
            if response:
                safe_send_message(chat_id, response.text, parse_mode='Markdown')

    except errors.APIError as e:
        safe_send_message(chat_id, f"⚠️ *Gemini API Error:* {e.message}", parse_mode='Markdown')
    except Exception as e:
        safe_send_message(chat_id, f"❌ Sorry, an error occurred: {e}")

if __name__ == '__main__':
    print("=" * 50)
    print("  Standalone AI Chatbot Agent Starting...")
    print("=" * 50)
    print("[✓] Bot is running! Waiting for messages...")
    bot.infinity_polling()


