import os
from google import genai
from google.genai import errors
from dotenv import load_dotenv

load_dotenv()

from google.genai import types
from tools import fetch_webpage, update_google_sheet, send_gmail_email, create_calendar_event, save_lead

SYSTEM_INSTRUCTION_ENGLISH = (
    "You are an Advanced AI Agent and assistant. You help creators and users with various tasks. "
    "You have access to tools that can:\n"
    "1. Fetch webpage contents from URLs (fetch_webpage).\n"
    "2. Update Google Sheets (update_google_sheet).\n"
    "3. Send emails using Gmail (send_gmail_email).\n"
    "4. Schedule Google Calendar events (create_calendar_event).\n"
    "5. Save customer/client leads to the local system (save_lead).\n\n"
    "Always use these tools whenever a user asks to perform these tasks. Once a tool execution completes, "
    "inform the user of the result. Always respond in English."
)

SYSTEM_INSTRUCTION_BANGLA = (
    "তুমি একজন উন্নত AI এজেন্ট এবং সহকারী। তুমি creators এবং users দের বিভিন্ন কাজে সাহায্য করো। "
    "তোমার কাছে নিম্নলিখিত tools আছে:\n"
    "1. ওয়েবপেজ এর কন্টেন্ট পড়া (fetch_webpage)\n"
    "2. Google Sheets আপডেট করা (update_google_sheet)\n"
    "3. Gmail দিয়ে ইমেইল পাঠানো (send_gmail_email)\n"
    "4. Google Calendar এ ইভেন্ট তৈরি করা (create_calendar_event)\n"
    "5. ক্লায়েন্ট লিড সেভ করা (save_lead)\n\n"
    "যখনই user এই কাজগুলো করতে বলবে, সাথে সাথে tools ব্যবহার করো। কাজ সম্পন্ন হলে বাংলায় জানাও। "
    "সবসময় বাংলায় উত্তর দাও। তবে user যদি ইংরেজিতে লেখে তাহলে সেটা বুঝে বাংলায় উত্তর দাও।"
)

SYSTEM_INSTRUCTION_AUTO = (
    "You are an Advanced AI Agent and assistant. You help creators and users with various tasks. "
    "You have access to tools that can:\n"
    "1. Fetch webpage contents from URLs (fetch_webpage).\n"
    "2. Update Google Sheets (update_google_sheet).\n"
    "3. Send emails using Gmail (send_gmail_email).\n"
    "4. Schedule Google Calendar events (create_calendar_event).\n"
    "5. Save customer/client leads to the local system (save_lead).\n\n"
    "Always use these tools whenever a user asks to perform these tasks. Once a tool execution completes, inform the user. "
    "IMPORTANT: Automatically detect the language the user is writing in. "
    "If the user writes in Bangla (Bengali), always respond in Bangla. "
    "If the user writes in English, respond in English. "
    "Always match the user's language automatically."
)

class AIChatbot:
    def __init__(self, model_name="gemini-2.5-flash", system_instruction=None, language="bangla"):
        self.model_name = model_name
        self.language = language  # "auto", "bangla", "english"
        self.system_instruction = system_instruction or self._get_instruction_for_language(language)
        self.client = None

        self._init_client()

    def _get_instruction_for_language(self, language):
        """Returns appropriate system instruction based on selected language."""
        if language == "bangla":
            return SYSTEM_INSTRUCTION_BANGLA
        elif language == "english":
            return SYSTEM_INSTRUCTION_ENGLISH
        else:  # auto
            return SYSTEM_INSTRUCTION_AUTO

    def set_language(self, language):
        """Switch language mode: 'bangla', 'english', or 'auto'"""
        self.language = language
        self.system_instruction = self._get_instruction_for_language(language)

    def _init_client(self):
        try:
            self.client = genai.Client()
        except Exception as e:
            print(f"Warning: Failed to initialize Gemini Client: {e}")
            self.client = None

    def create_session(self):
        """Creates a new conversational chat session with registered tools."""
        if not self.client:
            raise ValueError("Gemini Client is not initialized. Please configure GEMINI_API_KEY.")
        
        # Start a chat session with the default model, system instruction, and agent tools
        return self.client.chats.create(
            model=self.model_name,
            config=types.GenerateContentConfig(
                system_instruction=self.system_instruction,
                tools=[fetch_webpage, update_google_sheet, send_gmail_email, create_calendar_event, save_lead]
            )
        )


