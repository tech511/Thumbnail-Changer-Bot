import logging
import os
from urllib.parse import urlparse

from dotenv import load_dotenv
load_dotenv()

_log = logging.getLogger(__name__)


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

def _optional_env(name: str):
    """Optional text env var: stripped, or None when missing/blank."""
    return (os.getenv(name) or "").strip() or None


def _button_url_env(name: str):
    """Optional URL used for an inline URL button.

    Returns None when the variable is missing, blank or not a usable link,
    so callers can simply skip the button. Telegram accepts http(s):// and
    tg:// links on URL buttons.
    """
    value = _optional_env(name)

    if value is None:
        return None

    parsed = urlparse(value)
    valid = (
        parsed.scheme.lower() in ("http", "https", "tg")
        and bool(parsed.netloc)
        and not any(ch.isspace() for ch in value)
    )

    if not valid:
        _log.warning("%s is not a valid URL and will be ignored", name)
        return None

    return value


# ==========================================
# PRIVATE CONFIGURATION  (.env)
# ==========================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = _int_env("OWNER_ID")          # 0 = nobody is owner

MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("DB_NAME") or "thumbnail_bot"

LOG_CHANNEL = _chat_env("LOG_CHANNEL")   # optional

# All optional. Despite the names (kept for compatibility) these are IMAGE
# links (direct https link to a jpg/png) or a Telegram photo file_id. They are
# only trimmed; a missing/blank value means "send the page as text".
START_VIDEO_URL = _optional_env("START_VIDEO_URL")
HELP_VIDEO_URL = _optional_env("HELP_VIDEO_URL")
ABOUT_VIDEO_URL = _optional_env("ABOUT_VIDEO_URL")
SETTING_VIDEO_URL = _optional_env("SETTING_VIDEO_URL")

# Optional. None when missing or invalid -> the button is not shown.
UPDATE_CHANNEL_URL = _button_url_env("UPDATE_CHANNEL_URL")

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
