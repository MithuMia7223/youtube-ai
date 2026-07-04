# 🤖 YouTube AI Automation Bot

An advanced, feature-rich Telegram bot designed to fully automate the YouTube content creation and channel growth workflow. Powered by **Google Gemini AI** and **Microsoft Edge Neural TTS**, this bot generates video scripts, compiles stock footage, overlays high-quality voiceovers, designs eye-catching thumbnails, schedules uploads, and posts directly to YouTube.

---

## 🚀 Key Features

*   **🎬 Automated Faceless Video Creation**:
    *   Synthesizes realistic, natural-sounding voiceovers using Microsoft Edge Neural TTS (`edge-tts`).
    *   Downloads relevant high-quality stock footage from Pexels based on topic-relevant keywords.
    *   Automates video editing, text overlays, and audio syncing using `moviepy`.
*   **🧠 Gemini AI Integration**:
    *   Writes engaging video scripts optimized for high retention.
    *   Generates SEO-friendly titles, descriptions, and tag recommendations.
    *   Provides growth suggestions and channel optimization audits.
*   **🎨 AI-Driven Thumbnail Creation**:
    *   Dynamically creates customized, high-contrast thumbnails with smart typography overlay (`Pillow`).
*   **📅 Smart Auto-Post Scheduler**:
    *   Schedules video generations and posts at specified dates/times for hands-free automation.
*   **🔗 Affiliate Marketing Integration**:
    *   Automatically appends custom affiliate links and disclaimers to video descriptions based on target niches.
*   **🔒 Direct YouTube API Uploads**:
    *   Integrated OAuth 2.0 flow (`google-api-python-client`) for direct, secure uploads of videos and thumbnails to your YouTube channel.

---

## 🛠️ Tech Stack & Libraries

*   **Telegram Interface**: `pyTelegramBotAPI` (Telebot)
*   **Language Model**: `google-genai` (Gemini Flash/Pro)
*   **Video Processing**: `moviepy`, `imageio[ffmpeg]`, `requests` (Pexels API)
*   **Text-To-Speech**: `edge-tts` (Neural Voices)
*   **Image Processing**: `Pillow`
*   **Database & Scheduling**: Local JSON stores for configuration & scheduling queues
*   **OAuth / Uploads**: `google-auth-oauthlib`, `google-api-python-client`

---

## 📦 Project Structure

```
├── bot.py                  # Main Telegram Bot file & commands
├── auth.py                 # OAuth webserver / handler for YouTube Auth
├── video_creator.py        # Video assembly engine (Pexels fetcher + Audio overlay + Editing)
├── thumbnail_creator.py    # Auto-generation of thumbnail images
├── gemini_helper.py        # Gemini API script, SEO, and growth analyzers
├── youtube_helper.py       # YouTube API calls (Upload, channel stats, metadata)
├── scheduler_helper.py     # Task queue & cron-like execution scheduler
├── affiliate_helper.py     # Affiliate link insertion engine
├── run_bot.sh              # Shell script to start the bot
├── requirements.txt        # Project dependencies
└── .gitignore              # Git ignore rules (credentials/logs)
```

---

## ⚙️ Installation & Setup

### 1. Prerequisites
Make sure you have **Python 3.9+** and **FFmpeg** installed on your system.
*   *macOS*: `brew install ffmpeg`
*   *Ubuntu/Linux*: `sudo apt install ffmpeg`

### 2. Clone the Repository & Install Dependencies
```bash
git clone https://github.com/YOUR_USERNAME/youtube-ai.git
cd youtube-ai
pip install -r requirements.txt
```

### 3. Environment Configuration
Create a `.env` file in the root directory (refer to `.env.example`):
```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
GEMINI_API_KEY=your_gemini_api_key
PEXELS_API_KEY=your_pexels_api_key
```

### 4. YouTube OAuth Integration
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project, enable the **YouTube Data API v3**.
3. Create OAuth 2.0 Credentials (Desktop App) and download the JSON file.
4. Rename the downloaded file to `client_secrets.json` and place it in the root folder of this project.

---

## 🚦 How to Run

Start the Telegram Bot:
```bash
python bot.py
```
Or use the runner script:
```bash
chmod +x run_bot.sh
./run_bot.sh
```

---

## 📱 Telegram Commands & Usage

*   `/start` - Show welcoming screen and initialize interactive keyboard menu.
*   `/auth` - Start OAuth 2.0 flow to link your YouTube channel.
*   `🎬 Create Video` - Kick off the step-by-step video creator (Topic ➔ Script ➔ Voice ➔ Video ➔ Thumbnail ➔ Upload).
*   `📅 Auto-Post Schedule` - Set or view automatic content creation and publishing queues.
*   `📊 Grow Channel` - Perform channel health check, fetch real-time stats, or analyze viral potential using Gemini.
