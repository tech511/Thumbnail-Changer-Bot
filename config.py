
import os
from dotenv import load_dotenv

# Load private environment variables
load_dotenv()


# ==========================================
# PRIVATE CONFIGURATION
# ==========================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("DB_NAME")

LOG_CHANNEL = os.getenv("LOG_CHANNEL")


# Validate required credentials
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing from .env")


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
/thumb - Show saved thumbnail
/clear - Clear saved thumbnail
"""

HELP_VIDEO_URL = ""


# Update channel link
UPDATE_CHANNEL_URL = "https://t.me/your_channel"
