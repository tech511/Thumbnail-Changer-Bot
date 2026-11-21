import asyncio
import logging
import time
from io import BytesIO

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from database import setting_info
from logic import channel as channel_access
from utils.caption import style_caption
from utils.ui import tiny

log = logging.getLogger(__name__)

# Bot API cannot download files bigger than this
MAX_DOWNLOAD = 20 * 1024 * 1024

# Telegram thumbnail limits: JPEG, at most 200 KB, at most 320x320
MAX_THUMB_BYTES = 200 * 1024
MAX_THUMB_SIDE = 320

# Network timeouts (seconds)
THUMB_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 120

# A file waiting for the user's thumbnail photo is dropped after this long
PENDING_KEY = "pending"
PENDING_TTL = 600

NO_THUMB_TEXT = tiny("you have no thumbnail set yet")

# Why a document was resent without the requested thumbnail
REASON_TOO_LARGE = "too_large"
REASON_DOWNLOAD_FAILED = "download_failed"
REASON_NO_THUMB_DATA = "no_thumb_data"

UNAPPLIED_TEXT = {
    REASON_TOO_LARGE: (
        "this file is too large for me to re-upload, so telegram could not "
        "apply your thumbnail. it was resent without the new thumbnail."
    ),
    REASON_DOWNLOAD_FAILED: (
        "i could not download this file to apply your thumbnail. "
        "it was resent without the new thumbnail."
    ),
    REASON_NO_THUMB_DATA: (
        "your saved thumbnail data is missing, so the file was resent "
        "without it. please set your thumbnail again."
    ),
}


class ThumbnailError(Exception):
    """A problem with the thumbnail that is safe to show to the user."""

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


# ==========================================
# PENDING FILE  (a file waiting for a thumbnail photo)
# ==========================================

def set_pending(context: ContextTypes.DEFAULT_TYPE, item: dict):
    """Remember the file; replaces any earlier pending file."""
    context.user_data[PENDING_KEY] = {
        "item": item,
        "expires": time.time() + PENDING_TTL,
    }


def pop_pending(context: ContextTypes.DEFAULT_TYPE):
    """Take the pending file, or None when there is none / it expired."""
    entry = context.user_data.pop(PENDING_KEY, None)

    if not entry or entry["expires"] < time.time():
        return None

    return entry["item"]


def clear_pending(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(PENDING_KEY, None)


# ==========================================
# THUMBNAIL VALIDATION
# ==========================================

# JPEG start-of-frame markers we accept (baseline, extended, progressive)
_SOF_OK = (0xC0, 0xC1, 0xC2)
# Other start-of-frame markers (lossless, arithmetic, ...) are unsupported
_SOF_BAD = (0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF)

_ERR_INVALID = "that photo could not be read. please send a different one."
_ERR_FORMAT = "only jpeg photos can be used as a thumbnail."
_ERR_SIZE = "that photo is too big to use as a thumbnail."


def inspect_jpeg(data: bytes) -> tuple[int, int]:
    """Check that `data` is a complete, supported JPEG.

    Walks the JPEG segment headers (no image library needed) and returns
    (width, height). Raises ThumbnailError for anything else.
    """
    n = len(data)

    if n < 4 or data[:2] != b"\xff\xd8":
        raise ThumbnailError(_ERR_FORMAT)

    i = 2
    size = None
    seen_scan = False

    while i < n:
        if data[i] != 0xFF:
            raise ThumbnailError(_ERR_INVALID)

        while i < n and data[i] == 0xFF:  # optional fill bytes
            i += 1

        if i >= n:
            raise ThumbnailError(_ERR_INVALID)

        marker = data[i]
        i += 1

        if marker == 0xD9:  # EOI before any image data
            break

        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # no length field
            continue

        if i + 2 > n:
            raise ThumbnailError(_ERR_INVALID)

        seg_len = int.from_bytes(data[i:i + 2], "big")

        if seg_len < 2 or i + seg_len > n:
            raise ThumbnailError(_ERR_INVALID)

        if marker in _SOF_BAD:
            raise ThumbnailError(_ERR_FORMAT)

        if marker in _SOF_OK:
            if seg_len < 8:
                raise ThumbnailError(_ERR_INVALID)

            precision = data[i + 2]
            height = int.from_bytes(data[i + 3:i + 5], "big")
            width = int.from_bytes(data[i + 5:i + 7], "big")

            if precision != 8 or not width or not height:
                raise ThumbnailError(_ERR_INVALID)

            size = (width, height)

        elif marker == 0xDA:  # start of scan: header part is over
            seen_scan = True
            break

        i += seg_len

    if size is None or not seen_scan:
        raise ThumbnailError(_ERR_INVALID)

    # A complete JPEG ends with the EOI marker (truncated files do not)
    if not data.rstrip(b"\x00").endswith(b"\xff\xd9"):
        raise ThumbnailError(_ERR_INVALID)

    return size


def _pick_size(sizes):
    """Largest photo size that fits Telegram's thumbnail limits."""
    fitting = [
        s for s in sizes
        if max(s.width, s.height) <= MAX_THUMB_SIDE
        and (s.file_size is None or s.file_size <= MAX_THUMB_BYTES)
    ]

    if not fitting:
        raise ThumbnailError(_ERR_SIZE)

    return max(fitting, key=lambda s: s.width * s.height)


async def _download_thumbnail(photo_size) -> bytes:
    tg_file = await photo_size.get_file()

    if tg_file.file_size is not None and tg_file.file_size > MAX_THUMB_BYTES:
        raise ThumbnailError(_ERR_SIZE)

    buffer = BytesIO()
    await tg_file.download_to_memory(buffer)
    return buffer.getvalue()


async def prepare_thumbnail(sizes):
    """Return (file_id of best size, validated JPEG bytes of the small size).

    Raises ThumbnailError (safe to show) when the photo cannot be used as
    a Telegram thumbnail, so callers never save or report a bad one.
    """
    small = _pick_size(sizes)

    try:
        thumb_bytes = await asyncio.wait_for(
            _download_thumbnail(small), timeout=THUMB_TIMEOUT
        )
    except asyncio.TimeoutError:
        raise ThumbnailError(
            "downloading your photo took too long. please try again."
        )
    except TelegramError:
        log.exception("Thumbnail download failed")
        raise ThumbnailError(
            "i could not download your photo. please try again."
        )

    if not thumb_bytes or len(thumb_bytes) > MAX_THUMB_BYTES:
        raise ThumbnailError(_ERR_SIZE)

    width, height = inspect_jpeg(thumb_bytes)

    if width > MAX_THUMB_SIDE or height > MAX_THUMB_SIDE:
        raise ThumbnailError(_ERR_SIZE)

    return sizes[-1].file_id, thumb_bytes


# ==========================================
# HELPERS
# ==========================================

def _caption_kwargs(item: dict, style: str) -> dict:
    styled = style_caption(item.get("caption"), style)

    if styled:
        return {"caption": styled, "parse_mode": ParseMode.HTML}

    # style "none": keep the original caption and its formatting
    return {
        "caption": item.get("caption"),
        "caption_entities": item.get("caption_entities"),
    }


async def _load_document(bot, item: dict):
    """Download a document once so it can be re-uploaded with a thumbnail.

    Returns (BytesIO, None) on success or (None, reason) when the file
    cannot be re-uploaded. Oversized files are rejected from the known
    size before any download starts.
    """
    size = item.get("file_size")

    if size is not None and size > MAX_DOWNLOAD:
        return None, REASON_TOO_LARGE

    try:
        tg_file = await asyncio.wait_for(
            bot.get_file(item["file_id"]), timeout=DOWNLOAD_TIMEOUT
        )

        if tg_file.file_size is not None and tg_file.file_size > MAX_DOWNLOAD:
            return None, REASON_TOO_LARGE

        buffer = BytesIO()
        await asyncio.wait_for(
            tg_file.download_to_memory(buffer), timeout=DOWNLOAD_TIMEOUT
        )
    except asyncio.TimeoutError:
        log.warning("Document download timed out")
        return None, REASON_DOWNLOAD_FAILED
    except TelegramError as exc:
        log.warning("Document download failed: %s", exc)
        if "too big" in str(exc).lower():
            return None, REASON_TOO_LARGE
        return None, REASON_DOWNLOAD_FAILED

    return buffer, None


async def _send_item(bot, chat_id, item: dict, cfg: dict, payload=None) -> bool:
    """Send the item. Returns True when the new thumbnail was applied.

    A document re-sent by file_id keeps its old thumbnail (Telegram
    ignores a new one), so the new thumbnail is only applied when the
    document bytes (`payload`) are re-uploaded.
    """
    caption = _caption_kwargs(item, cfg["caption_style"])

    if item["kind"] == "video":
        await bot.send_video(
            chat_id=chat_id,
            video=item["file_id"],
            cover=cfg["thumb_file_id"],
            duration=item.get("duration"),
            width=item.get("width"),
            height=item.get("height"),
            supports_streaming=True,
            **caption,
        )
        return True

    if payload is not None and cfg["thumb_bytes"]:
        payload.seek(0)
        await bot.send_document(
            chat_id=chat_id,
            document=payload,
            filename=item.get("file_name"),
            thumbnail=cfg["thumb_bytes"],
            **caption,
        )
        return True

    # file_id fallback: the file is delivered, the thumbnail is not applied
    await bot.send_document(
        chat_id=chat_id,
        document=item["file_id"],
        **caption,
    )
    return False


async def _post_to_channel(update, context, item, cfg, payload):
    """Copy the result to the user's channel after re-checking permissions."""
    bot = context.bot
    user_id = update.effective_user.id
    message = update.effective_message
    channel_id = cfg["channel_id"]

    reason = await channel_access.check_channel_access(bot, channel_id, user_id)

    if reason:
        if reason in channel_access.STALE_REASONS:
            try:
                await setting_info.delete_channel(
                    user_id, expected_channel_id=channel_id
                )
            except Exception:
                log.exception("Unable to remove outdated channel")
            text = (
                "your channel was removed from settings because you are no "
                "longer allowed to post there."
            )
        else:
            text = "could not post to your channel. " + channel_access.REASON_TEXT[reason]

        await message.reply_text("⚠️ " + tiny(text))
        return

    try:
        applied = await _send_item(bot, channel_id, item, cfg, payload)
    except TelegramError:
        log.exception("Channel delivery failed")
        await message.reply_text(
            "⚠️ " + tiny(
                "could not post to your channel. "
                "check that i am still an admin there."
            )
        )
        return

    if not applied:
        await message.reply_text(
            "⚠️ " + tiny("the channel copy was also sent without the new thumbnail.")
        )


# ==========================================
# DELIVER MEDIA WITH NEW THUMBNAIL
# ==========================================

async def deliver(update: Update, context: ContextTypes.DEFAULT_TYPE, item: dict):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    cfg = await setting_info.get_settings(user_id)

    if not cfg["thumb_file_id"]:
        set_pending(context, item)
        await update.effective_message.reply_text(
            "📸 " + tiny("now send the photo to use as thumbnail.")
        )
        return

    await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)

    payload = None
    reason = None

    try:
        if item["kind"] == "document":
            if cfg["thumb_bytes"]:
                # one download is shared by the chat and the channel copy
                payload, reason = await _load_document(context.bot, item)
            else:
                reason = REASON_NO_THUMB_DATA

        try:
            applied = await _send_item(context.bot, chat_id, item, cfg, payload)
        except Exception:
            log.exception("Media delivery failed")
            await update.effective_message.reply_text(
                "❌ " + tiny("failed to send your file. please try again.")
            )
            return

        if not applied:
            await update.effective_message.reply_text(
                "⚠️ " + tiny(UNAPPLIED_TEXT.get(reason, UNAPPLIED_TEXT[REASON_DOWNLOAD_FAILED]))
            )

        # Optional copy to the user's channel
        if cfg["channel_id"]:
            await _post_to_channel(update, context, item, cfg, payload)
    finally:
        if payload is not None:
            payload.close()


# ==========================================
# COMMANDS
# ==========================================

async def show_thumb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = await setting_info.get_settings(update.effective_user.id)

    if not cfg["thumb_file_id"]:
        await update.message.reply_text(NO_THUMB_TEXT)
        return

    await update.message.reply_photo(
        photo=cfg["thumb_file_id"],
        caption=tiny("your current thumbnail"),
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cfg = await setting_info.get_settings(user_id)

    clear_pending(context)

    if not cfg["thumb_file_id"]:
        await update.message.reply_text(NO_THUMB_TEXT)
        return

    await setting_info.delete_thumbnail(user_id)
    await update.message.reply_text("🗑 " + tiny("thumbnail cleared."))


# ==========================================
# MESSAGE HANDLERS
# ==========================================

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    try:
        file_id, thumb_bytes = await prepare_thumbnail(update.message.photo)
        await setting_info.set_thumbnail(user_id, file_id, thumb_bytes)
    except ThumbnailError as exc:
        await update.message.reply_text("❌ " + tiny(exc.user_message))
        return
    except Exception:
        log.exception("Unable to save thumbnail")
        await update.message.reply_text(
            "❌ " + tiny("could not save your thumbnail. please try again.")
        )
        return

    pending = pop_pending(context)

    if pending:
        await deliver(update, context, pending)
    else:
        await update.message.reply_text(
            "✅ " + tiny("thumbnail saved. now send a video or file.")
        )


async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if msg.video:
        item = {
            "kind": "video",
            "file_id": msg.video.file_id,
            "caption": msg.caption,
            "caption_entities": msg.caption_entities,
            "duration": msg.video.duration,
            "width": msg.video.width,
            "height": msg.video.height,
        }

    elif msg.document:
        item = {
            "kind": "document",
            "file_id": msg.document.file_id,
            "file_name": msg.document.file_name,
            "file_size": msg.document.file_size,
            "caption": msg.caption,
            "caption_entities": msg.caption_entities,
        }

    else:
        return

    await deliver(update, context, item)


def register_thumbnail_handlers(app: Application):
    private = filters.ChatType.PRIVATE

    app.add_handler(CommandHandler("thumb", show_thumb, filters=private))
    app.add_handler(CommandHandler("clear", clear, filters=private))
    app.add_handler(MessageHandler(private & filters.PHOTO, on_photo))
    app.add_handler(
        MessageHandler(private & (filters.VIDEO | filters.Document.ALL), on_media)
    )
