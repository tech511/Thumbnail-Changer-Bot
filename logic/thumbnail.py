import logging

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
from utils.caption import style_caption
from utils.ui import tiny

log = logging.getLogger(__name__)

# Bot API cannot download files bigger than this
MAX_DOWNLOAD = 20 * 1024 * 1024

NO_THUMB_TEXT = tiny("you have no thumbnail set yet")


# ==========================================
# HELPERS
# ==========================================

async def prepare_thumbnail(sizes):
    """Return (file_id of best size, JPEG bytes of the small size)."""
    small = next(
        (s for s in sizes if max(s.width, s.height) <= 320),
        sizes[0],
    )

    tg_file = await small.get_file()
    thumb_bytes = bytes(await tg_file.download_as_bytearray())

    return sizes[-1].file_id, thumb_bytes


def _caption_kwargs(item: dict, style: str) -> dict:
    styled = style_caption(item.get("caption"), style)

    if styled:
        return {"caption": styled, "parse_mode": ParseMode.HTML}

    # style "none": keep the original caption and its formatting
    return {
        "caption": item.get("caption"),
        "caption_entities": item.get("caption_entities"),
    }


async def _send_item(bot, chat_id, item: dict, cfg: dict):
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
        return

    # Telegram usually ignores a new thumbnail when a document is re-sent
    # by file_id, so re-upload the bytes when the file is small enough.
    document = item["file_id"]

    if (item.get("file_size") or 0) <= MAX_DOWNLOAD:
        try:
            tg_file = await bot.get_file(item["file_id"])
            document = bytes(await tg_file.download_as_bytearray())
        except TelegramError:
            log.warning("Document download failed, sending by file_id")

    await bot.send_document(
        chat_id=chat_id,
        document=document,
        filename=item.get("file_name"),
        thumbnail=cfg["thumb_bytes"],
        **caption,
    )


# ==========================================
# DELIVER MEDIA WITH NEW THUMBNAIL
# ==========================================

async def deliver(update: Update, context: ContextTypes.DEFAULT_TYPE, item: dict):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    cfg = await setting_info.get_settings(user_id)

    if not cfg["thumb_file_id"]:
        context.user_data["pending"] = item
        await update.effective_message.reply_text(
            "📸 " + tiny("now send the photo to use as thumbnail.")
        )
        return

    await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)

    try:
        await _send_item(context.bot, chat_id, item, cfg)
    except Exception:
        log.exception("Media delivery failed")
        await update.effective_message.reply_text(
            "❌ " + tiny("failed to send your file. please try again.")
        )
        return

    # Optional copy to the user's channel
    if cfg["channel_id"]:
        try:
            await _send_item(context.bot, cfg["channel_id"], item, cfg)
        except TelegramError:
            log.exception("Channel delivery failed")
            await update.effective_message.reply_text(
                "⚠️ " + tiny(
                    "could not post to your channel. "
                    "check that i am still an admin there."
                )
            )


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

    context.user_data.pop("pending", None)

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
    except Exception:
        log.exception("Unable to save thumbnail")
        await update.message.reply_text(
            "❌ " + tiny("could not save your thumbnail. please try again.")
        )
        return

    pending = context.user_data.pop("pending", None)

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
