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

START_VIDEO_URL = os.getenv("START_VIDEO_URL")
HELP_VIDEO_URL = os.getenv("HELP_VIDEO_URL")
ABOUT_VIDEO_URL = os.getenv("ABOUT_VIDEO_URL")
SETTING_VIDEO_URL = os.getenv("SETTING_VIDEO_URL")
UPDATE_CHANNEL_URL = os.getenv("UPDATE_CHANNEL_URL")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing from .env")

if not MONGO_URL:
    raise ValueError("MONGO_URL is missing from .env")


# ==========================================
# PUBLIC CONFIGURATION
# ==========================================


START_TEXT = """
<b>ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴛʜᴜᴍʙɴᴀɪʟ ᴄʜᴀɴɢᴇʀ ʙᴏᴛ!</b>

<blockquote>
sᴇɴᴅ ᴍᴇ ᴀ ᴠɪᴅᴇᴏ ᴀɴᴅ ɪ ᴡɪʟʟ ᴀᴅᴅ ʏᴏᴜʀ ᴄᴜsᴛᴏᴍ ᴛʜᴜᴍʙɴᴀɪʟ ᴛᴏ ɪᴛ. 
ʏᴏᴜ ᴄᴀɴ ꜱᴇᴛ ʏᴏᴜʀ ᴄᴀᴘᴛɪᴏɴ ꜱᴛʏʟᴇ ᴜꜱɪɴɢ ᴄᴏᴍᴍᴀɴᴅꜱ ᴍᴇɴᴜᴇ.
</blockquote>
<b>ʜᴏᴡ ᴛᴏ ᴜsᴇ:</b>
<blockquote>
• sᴇᴛ ʏᴏᴜʀ ᴛʜᴜᴍʙɴᴀɪʟ ɪɴ sᴇᴛᴛɪɴɢs
• sᴇɴᴅ ᴀɴʏ ᴠɪᴅᴇᴏ
• ɢᴇᴛ ᴠɪᴅᴇᴏ ᴡɪᴛʜ ʏᴏᴜʀ ᴛʜᴜᴍʙɴᴀɪʟ!
</blockquote>
"""
ABOUT_TEXT = """
<b>✨ ᴀʙᴏᴜᴛ ᴍᴇ</b>

✰ ᴍʏ ɴᴀᴍᴇ: <a href="http://t.me/Tg_Thumbnail_changer_bot">ᴛʜᴜᴍʙɴᴀɪʟ ʙᴏᴛ</a>

✰ ᴍʏ ᴏᴡɴᴇʀ: <a href="https://t.me/H_IN_A_TA">ADMIN</a>

✰ ᴜᴘᴅᴀᴛᴇs: <a href="https://t.me/Bot_Arena_Official">ARENA BOT</a>

✰ sᴜᴘᴘᴏʀᴛ: <a href="https://t.me/ARENA_GROUP">ARENA GROUP</a>

✰ ᴠᴇʀsɪᴏɴ: 9.11.10 [V1.0]
"""
HELP_TEXT = """
<b>❓ ʜᴏᴡ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ʙᴏᴛ?</b>

<blockquote>
1️⃣ ꜱᴇɴᴅ ᴀ ᴘʜᴏᴛᴏ ᴛᴏ ᴛʜᴇ ʙᴏᴛ.
2️⃣ ꜱᴇɴᴅ ʏᴏᴜʀ ᴠɪᴅᴇᴏ ᴏʀ ᴅᴏᴄᴜᴍᴇɴᴛ.
3️⃣ ᴛʜᴇ ʙᴏᴛ ᴡɪʟʟ ʀᴇᴛᴜʀɴ ʏᴏᴜʀ ꜰɪʟᴇ ᴡɪᴛʜ ᴛʜᴇ ɴᴇᴡ ᴛʜᴜᴍʙɴᴀɪʟ.
</blockquote>

<b>⚙️ ᴄᴏᴍᴍᴀɴᴅꜱ:</b>

<code>/start</code> - ꜱᴛᴀʀᴛ ᴛʜᴇ ʙᴏᴛ
<code>/setting</code> - ᴏᴘᴇɴ ꜱᴇᴛᴛɪɴɢꜱ ᴘᴀɴᴇʟ
<code>/thumb</code> - ꜱʜᴏᴡ ꜱᴀᴠᴇᴅ ᴛʜᴜᴍʙɴᴀɪʟ
<code>/clear</code> - ᴄʟᴇᴀʀ ꜱᴀᴠᴇᴅ ᴛʜᴜᴍʙɴᴀɪʟ
"""
