import os
from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int = 0) -> int:
    """Read an integer env var without crashing on empty/bad values."""
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _chat_env(name: str):
    """Chat id or @username from env. Numeric ids become int."""
    value = (os.getenv(name) or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return value


# ==========================================
# PRIVATE CONFIGURATION  (.env)
# ==========================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = _int_env("OWNER_ID")          # 0 = nobody is owner

MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("DB_NAME") or "thumbnail_bot"

LOG_CHANNEL = _chat_env("LOG_CHANNEL")   # optional

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing from .env")

if not MONGO_URL:
    raise ValueError("MONGO_URL is missing from .env")


# ==========================================
# PUBLIC CONFIGURATION
# ==========================================

START_TEXT = """
<b>Welcome to Thumbnail Changer Bot!</b>

Send me a photo and then a video or document.
I will add your selected photo as its thumbnail.
"""

START_VIDEO_URL = ""

ABOUT_TEXT = """
<b>About Thumbnail Changer Bot</b>

This bot allows you to change video covers
and document thumbnails directly through Telegram.
"""

ABOUT_VIDEO_URL = ""

HELP_TEXT = """
<b>How to use this bot?</b>

1. Send a photo to the bot.
2. Send your video or document.
3. The bot will return your file with the new thumbnail.

<b>Commands:</b>

/start - Start the bot
/setting - Open settings panel
/thumb - Show saved thumbnail
/clear - Clear saved thumbnail
"""

HELP_VIDEO_URL = ""

# Video (direct URL or Telegram file_id) shown on the /setting panel
SETTING_VIDEO_URL = ""

UPDATE_CHANNEL_URL = "https://t.me/AniWorld_Bots_Hub"
