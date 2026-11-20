
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    Application,
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

log = logging.getLogger(__name__)


# ==========================================
# START MENU BUTTONS
# ==========================================

def start_keyboard():

    keyboard = [
        [
            InlineKeyboardButton(
                "Help",
                callback_data="help"
            ),
            InlineKeyboardButton(
                "About",
                callback_data="about"
            ),
        ],
        [
            InlineKeyboardButton(
                "Setting",
                callback_data="setting"
            ),
        ],
        [
            InlineKeyboardButton(
                "Update Channel",
                url="https://t.me/AniWorld_Bots_Hub"
            ),
            InlineKeyboardButton(
                "Close",
                callback_data="close"
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# ==========================================
# NAVIGATION BUTTONS
# ==========================================

def navigation_keyboard():

    keyboard = [
        [
            InlineKeyboardButton(
                "Back",
                callback_data="back"
            ),
            InlineKeyboardButton(
                "Close",
                callback_data="close"
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# ==========================================
# DELETE OLD MENU MESSAGES
# ==========================================

async def delete_old_messages(
    chat_id,
    context: ContextTypes.DEFAULT_TYPE
):

    message_ids = context.user_data.get(
        "menu_message_ids", []
    )

    for message_id in message_ids:

        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=message_id
            )

        except Exception:
            log.warning(
                "Unable to delete message: %s",
                message_id
            )

    context.user_data["menu_message_ids"] = []


# ==========================================
# DISPLAY MENU PAGE
# ==========================================

async def show_page(
    chat_id,
    context: ContextTypes.DEFAULT_TYPE,
    text,
    video_url=None,
    keyboard=None
):

    await delete_old_messages(
        chat_id,
        context
    )

    message_ids = []

    # Send video
    if video_url:

        try:

            video_message = await context.bot.send_video(
                chat_id=chat_id,
                video=video_url
            )

            message_ids.append(
                video_message.message_id
            )

        except Exception:
            log.exception(
                "Unable to send menu video"
            )

    # Send text and buttons
    text_message = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard
    )

    message_ids.append(
        text_message.message_id
    )

    context.user_data["menu_message_ids"] = message_ids


# ==========================================
# START COMMAND
# ==========================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    await show_page(
        chat_id=chat_id,
        context=context,
        text=START_TEXT,
        video_url=START_VIDEO_URL,
        keyboard=start_keyboard()
    )


# ==========================================
# MENU CALLBACKS
# ==========================================

async def menu_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    chat_id = query.message.chat_id

    # CLOSE
    if query.data == "close":

        await delete_old_messages(
            chat_id,
            context
        )

        return

    # BACK TO START MENU
    elif query.data == "back":

        await show_page(
            chat_id=chat_id,
            context=context,
            text=START_TEXT,
            video_url=START_VIDEO_URL,
            keyboard=start_keyboard()
        )

        return

    # HELP PAGE
    elif query.data == "help":

        await show_page(
            chat_id=chat_id,
            context=context,
            text=HELP_TEXT,
            video_url=HELP_VIDEO_URL,
            keyboard=navigation_keyboard()
        )

        return

    # ABOUT PAGE
    elif query.data == "about":

        await show_page(
            chat_id=chat_id,
            context=context,
            text=ABOUT_TEXT,
            video_url=ABOUT_VIDEO_URL,
            keyboard=navigation_keyboard()
        )

        return

    # SETTING PAGE
    elif query.data == "setting":

        await show_page(
            chat_id=chat_id,
            context=context,
            text="⚙️ <b>Settings</b>\n\nSetting features coming soon.",
            keyboard=navigation_keyboard()
        )

        return


# ==========================================
# REGISTER HANDLERS
# ==========================================

def register_start_handlers(app: Application):

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CallbackQueryHandler(
            menu_callback,
            pattern="^(help|about|setting|back|close)$"
        )
    )
