
import asyncio
import json
import logging
import urllib.parse
import urllib.request
import urllib.error

from collections import OrderedDict

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import filters
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import (
    DATABASE_URL,
    DATABASE_NAME,
    BOT_TOKEN,
    SETTING_VIDEO,
    SETTING_TEXT,
)

from handle.setting import collection as thumbnails
from handle.setting import dashboard_buttons


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("thumbnail_bot.processing")

mongo = AsyncIOMotorClient(DATABASE_URL)
db = mongo[DATABASE_NAME]
channels = db["processing_channels"]

queues = {}
workers = {}

# Track recently received messages and messages currently being processed.
seen_messages = OrderedDict()
processing_messages = set()

MAX_SEEN_MESSAGES = 5000


def no_thumbnail_button():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⚙️ Set Thumbnail",
                callback_data="processing_open_settings",
            )
        ]
    ])


async def telegram_api(method, data):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    body = urllib.parse.urlencode(data).encode("utf-8")

    def request():
        try:
            with urllib.request.urlopen(
                url,
                data=body,
                timeout=120,
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Telegram API {method} returned HTTP {exc.code}: {details}"
            ) from exc

        return json.loads(raw)

    result = await asyncio.to_thread(request)

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram API {method} failed: "
            f"{result.get('description', 'Unknown error')}"
        )

    return result["result"]


async def send_video_with_cover(chat_id, video_id, thumbnail_id, caption):
    return await telegram_api(
        "sendVideo",
        {
            "chat_id": chat_id,
            "video": video_id,
            "cover": thumbnail_id,
            "caption": caption or "",
        },
    )


async def set_channel(client, message):
    user_id = message.chat.id
    parts = (message.text or "").split(maxsplit=1)

    if len(parts) != 2:
        await message.reply_text(
            "Send your destination channel.\n\n"
            "Example: `/set_channel @my_channel`"
        )
        return

    try:
        chat = await client.get_chat(parts[1].strip())

        await channels.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "user_id": user_id,
                    "channel_id": chat.id,
                }
            },
            upsert=True,
        )

        await message.reply_text("✅ Destination channel saved.")

    except Exception as exc:
        logger.exception("Failed to save channel for user_id=%s", user_id)
        await message.reply_text(
            f"❌ Could not save the channel.\nReason: `{str(exc)[:700]}`"
        )


async def open_settings(client, query):
    await query.answer()

    chat_id = query.message.chat.id
    user_id = query.message.chat.id

    try:
        await query.message.delete()
    except Exception:
        logger.warning("Could not delete settings message", exc_info=True)

    try:
        record = await thumbnails.find_one({"user_id": user_id})
        has_thumbnail = bool(record and record.get("file_id"))

        status = (
            "✅ Set thumbnail"
            if has_thumbnail
            else "❌ No thumbnail set"
        )

        await client.send_video(
            chat_id=chat_id,
            video=SETTING_VIDEO,
            caption=f"{SETTING_TEXT}\n\n📊 Status: {status}",
            reply_markup=dashboard_buttons(),
        )

    except Exception as exc:
        logger.exception("Failed to open settings for user_id=%s", user_id)
        await client.send_message(
            chat_id,
            f"❌ Could not open settings.\nReason: `{str(exc)[:700]}`",
        )


async def process_video(client, message):
    # Only process files received in a private bot chat.
    if not message.from_user:
        return

    if str(message.chat.type).lower().split(".")[-1] != "private":
        return

    user_id = message.chat.id
    media = message.video

    if not media and message.document:
        if (message.document.mime_type or "").startswith("video/"):
            media = message.document

    if not media:
        return

    key = (message.chat.id, message.id)

    # Protect against duplicate processing inside this process.
    if key in processing_messages:
        logger.warning("Already processing message %s", key)
        return

    processing_messages.add(key)

    try:
        logger.info(
            "Processing user_id=%s message_id=%s",
            user_id,
            message.id,
        )

        try:
            record = await thumbnails.find_one({"user_id": user_id})
        except Exception as exc:
            logger.exception("Thumbnail database lookup failed")
            await message.reply_text(
                f"❌ Database error.\nReason: `{str(exc)[:700]}`"
            )
            return

        thumbnail_id = record.get("file_id") if record else None

        if not thumbnail_id:
            await message.reply_text(
                "❌ You have no thumbnail saved yet.",
                reply_markup=no_thumbnail_button(),
            )
            return

        caption = message.caption or ""

        try:
            await send_video_with_cover(
                message.chat.id,
                media.file_id,
                thumbnail_id,
                caption,
            )
            logger.info(
                "Video sent successfully: user_id=%s message_id=%s",
                user_id,
                message.id,
            )

        except Exception as exc:
            logger.exception("Failed to send video with cover")
            await message.reply_text(
                f"❌ Video sending failed.\nReason: `{str(exc)[:700]}`"
            )
            return

        try:
            destination = await channels.find_one({"user_id": user_id})

            if destination:
                await send_video_with_cover(
                    destination["channel_id"],
                    media.file_id,
                    thumbnail_id,
                    caption,
                )
                logger.info(
                    "Destination delivery successful: user_id=%s",
                    user_id,
                )

        except Exception as exc:
            logger.exception("Destination channel delivery failed")
            await message.reply_text(
                f"⚠️ Video was sent here, but channel delivery failed.\n"
                f"Reason: `{str(exc)[:700]}`"
            )

    finally:
        processing_messages.discard(key)


async def queue_worker(client, user_id):
    queue = queues[user_id]

    try:
        while not queue.empty():
            message = await queue.get()
            try:
                await process_video(client, message)
            except Exception:
                logger.exception(
                    "Unexpected processing error: user_id=%s message_id=%s",
                    user_id,
                    message.id,
                )
                try:
                    await message.reply_text(
                        "❌ Unexpected processing error. Check hosting logs."
                    )
                except Exception:
                    logger.exception("Could not send error notice")
            finally:
                queue.task_done()

    finally:
        if workers.get(user_id) is asyncio.current_task():
            workers.pop(user_id, None)

        if not queue.empty():
            workers[user_id] = asyncio.create_task(
                queue_worker(client, user_id)
            )
        else:
            queues.pop(user_id, None)


async def enqueue(client, message):
    if not message.from_user:
        return

    key = (message.chat.id, message.id)

    if key in seen_messages:
        logger.warning("Duplicate incoming message ignored: %s", key)
        return

    seen_messages[key] = True

    if len(seen_messages) > MAX_SEEN_MESSAGES:
        seen_messages.popitem(last=False)

    user_id = message.chat.id
    queue = queues.setdefault(user_id, asyncio.Queue())
    await queue.put(message)

    task = workers.get(user_id)

    if task is None or task.done():
        workers[user_id] = asyncio.create_task(
            queue_worker(client, user_id)
        )


def register_processing(app):
    app.add_handler(
        MessageHandler(
            set_channel,
            filters.command("set_channel") & filters.private,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            open_settings,
            filters.regex(r"^processing_open_settings$") & filters.private,
        )
    )

    app.add_handler(
        MessageHandler(
            enqueue,
            (filters.video | filters.document) & filters.private,
        )
    )

    logger.info("Processing handlers registered")
