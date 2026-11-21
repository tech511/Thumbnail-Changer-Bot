import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

from config import (
    START_TEXT,
    START_VIDEO_URL,
    ABOUT_TEXT,
    ABOUT_VIDEO_URL,
    HELP_TEXT,
    HELP_VIDEO_URL,
    UPDATE_CHANNEL_URL,
)
from utils.ui import tiny, nav_keyboard, show_page, delete_old_messages

log = logging.getLogger(__name__)


def start_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(tiny("help"), callback_data="help"),
            InlineKeyboardButton(tiny("about"), callback_data="about"),
        ],
        [
            InlineKeyboardButton(tiny("setting"), callback_data="setting"),
        ],
        [
            InlineKeyboardButton(tiny("update channel"), url=UPDATE_CHANNEL_URL),
            InlineKeyboardButton("✖️ " + tiny("close"), callback_data="close"),
        ],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_page(
        chat_id=update.effective_chat.id,
        context=context,
        text=START_TEXT,
        video_url=START_VIDEO_URL,
        keyboard=start_keyboard(),
    )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_chat.id

    if query.data == "close":
        await delete_old_messages(chat_id, context)

    elif query.data == "back":
        await show_page(chat_id, context, START_TEXT, START_VIDEO_URL, start_keyboard())

    elif query.data == "help":
        await show_page(chat_id, context, HELP_TEXT, HELP_VIDEO_URL, nav_keyboard())

    elif query.data == "about":
        await show_page(chat_id, context, ABOUT_TEXT, ABOUT_VIDEO_URL, nav_keyboard())


def register_start_handlers(app: Application):
    app.add_handler(
        CommandHandler("start", start, filters=filters.ChatType.PRIVATE)
    )

    # "setting" and "set:*" callbacks are handled in handlers/setting.py
    app.add_handler(
        CallbackQueryHandler(menu_callback, pattern="^(help|about|back|close)$")
    )
