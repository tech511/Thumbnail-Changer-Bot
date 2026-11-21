"""Shared UI helpers: tiny-caps text, navigation buttons, page rendering."""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)

MENU_KEY = "menu_message_ids"

_SMALL_CAPS = str.maketrans(
    "abcdefghijklmnopqrstuvwxyz",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ",
)


def tiny(text: str) -> str:
    """Convert plain text to tiny small-caps style.

    Only pass plain text here - never strings that contain HTML tags
    or user-provided data.
    """
    return text.lower().translate(_SMALL_CAPS)


# ==========================================
# NAVIGATION
# ==========================================

def nav_row(back_data: str = "back"):
    return [
        InlineKeyboardButton("⬅️ " + tiny("back"), callback_data=back_data),
        InlineKeyboardButton("✖️ " + tiny("close"), callback_data="close"),
    ]


def nav_keyboard(back_data: str = "back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([nav_row(back_data)])


# ==========================================
# PAGE RENDERING
# ==========================================

async def _delete_ids(chat_id, context: ContextTypes.DEFAULT_TYPE, ids):
    for message_id in ids:
        try:
            await context.bot.delete_message(
                chat_id=chat_id, message_id=message_id
            )
        except TelegramError:
            log.warning("Unable to delete message: %s", message_id)


async def delete_old_messages(chat_id, context: ContextTypes.DEFAULT_TYPE):
    ids = context.user_data.get(MENU_KEY, [])
    context.user_data[MENU_KEY] = []
    await _delete_ids(chat_id, context, ids)


async def show_page(
    chat_id,
    context: ContextTypes.DEFAULT_TYPE,
    text,
    video_url=None,
    keyboard=None,
):
    """Send a new page, then remove the previous one.

    The new page is sent first so a failed send never leaves the
    user with an empty chat.
    """
    old_ids = context.user_data.get(MENU_KEY, [])
    new_ids = []

    if video_url:
        try:
            video = await context.bot.send_video(
                chat_id=chat_id, video=video_url
            )
            new_ids.append(video.message_id)
        except TelegramError:
            log.exception("Unable to send menu video")

    try:
        message = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    except Exception:
        await _delete_ids(chat_id, context, new_ids)
        raise

    new_ids.append(message.message_id)
    context.user_data[MENU_KEY] = new_ids
    await _delete_ids(chat_id, context, old_ids)


async def show_photo_page(
    chat_id,
    context: ContextTypes.DEFAULT_TYPE,
    photo,
    caption,
    keyboard=None,
):
    old_ids = context.user_data.get(MENU_KEY, [])

    message = await context.bot.send_photo(
        chat_id=chat_id,
        photo=photo,
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )

    context.user_data[MENU_KEY] = [message.message_id]
    await _delete_ids(chat_id, context, old_ids)
