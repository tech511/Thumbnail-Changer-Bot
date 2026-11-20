
import logging
from io import BytesIO

from telegram import Update, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

log = logging.getLogger(__name__)


# ==========================================
# SHOW SAVED THUMBNAIL
# ==========================================

async def show_thumb(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    cover = context.user_data.get("cover")

    if not cover:
        await update.message.reply_text(
            "No thumbnail saved. Send me a photo."
        )
        return

    await update.message.reply_photo(
        photo=cover,
        caption="Your current thumbnail"
    )


# ==========================================
# CLEAR SAVED THUMBNAIL
# ==========================================

async def clear(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    for key in ("cover", "thumb_bytes", "pending"):
        context.user_data.pop(key, None)

    await update.message.reply_text(
        "🗑 Thumbnail cleared."
    )


# ==========================================
# DELIVER MEDIA WITH NEW THUMBNAIL
# ==========================================

async def deliver(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    item: dict
):

    chat_id = update.effective_chat.id

    try:

        if item["kind"] == "video":

            await context.bot.send_video(
                chat_id=chat_id,
                video=item["file_id"],
                cover=context.user_data["cover"],
                caption=item.get("caption"),
                duration=item.get("duration"),
                width=item.get("width"),
                height=item.get("height"),
                supports_streaming=True,
            )

        else:

            thumb = context.user_data.get("thumb_bytes")

            thumbnail_file = None

            if thumb:
                thumbnail_file = InputFile(
                    BytesIO(thumb),
                    filename="thumbnail.jpg"
                )

            await context.bot.send_document(
                chat_id=chat_id,
                document=item["file_id"],
                thumbnail=thumbnail_file,
                caption=item.get("caption"),
            )

    except Exception:

        log.exception("Media delivery failed")

        await update.effective_message.reply_text(
            "❌ Failed to send your file. Please try again."
        )


# ==========================================
# PHOTO HANDLER
# ==========================================

async def on_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    sizes = update.message.photo

    # Save Telegram file_id
    context.user_data["cover"] = sizes[-1].file_id

    # Find small image for document thumbnail
    small = next(
        (
            s for s in sizes
            if max(s.width, s.height) <= 320
        ),
        sizes[0]
    )

    # Download only the small thumbnail
    tg_file = await small.get_file()

    thumb_bytes = bytes(
        await tg_file.download_as_bytearray()
    )

    context.user_data["thumb_bytes"] = thumb_bytes

    pending = context.user_data.pop(
        "pending",
        None
    )

    if pending:

        await deliver(
            update,
            context,
            pending
        )

    else:

        await update.message.reply_text(
            "✅ Thumbnail saved. Now send a video or file."
        )


# ==========================================
# VIDEO / DOCUMENT HANDLER
# ==========================================

async def on_media(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    msg = update.message

    if msg.video:

        video = msg.video

        item = {
            "kind": "video",
            "file_id": video.file_id,
            "caption": msg.caption,
            "duration": video.duration,
            "width": video.width,
            "height": video.height,
        }

    elif msg.document:

        document = msg.document

        item = {
            "kind": "document",
            "file_id": document.file_id,
            "caption": msg.caption,
        }

    else:
        return

    if context.user_data.get("cover"):

        await deliver(
            update,
            context,
            item
        )

    else:

        context.user_data["pending"] = item

        await msg.reply_text(
            "📸 Now send the photo to use as thumbnail."
        )


# ==========================================
# REGISTER THUMBNAIL HANDLERS
# ==========================================

def register_thumbnail_handlers(app: Application):

    app.add_handler(
        CommandHandler("thumb", show_thumb)
    )

    app.add_handler(
        CommandHandler("clear", clear)
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            on_photo
        )
    )

    app.add_handler(
        MessageHandler(
            filters.VIDEO | filters.Document.ALL,
            on_media
        )
    )
