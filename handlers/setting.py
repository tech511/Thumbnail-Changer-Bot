"""Settings panel: /setting, thumbnail / caption / channel pages."""

import html
import logging
import re
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import SETTING_VIDEO_URL
from database import setting_info
from logic.thumbnail import prepare_thumbnail
from utils.caption import CAPTION_STYLES
from utils.ui import tiny, nav_row, show_page, show_photo_page

log = logging.getLogger(__name__)


# ==========================================
# SESSION  (one per user, kept in user_data)
# ==========================================

SESSION_KEY = "setting_session"
SESSION_TTL = 600  # seconds an input prompt stays valid

AWAIT_THUMB = "await_thumb"
AWAIT_CHANNEL = "await_channel"


def start_session(context: ContextTypes.DEFAULT_TYPE) -> dict:
    session = {"state": None, "expires": time.time() + SESSION_TTL}
    context.user_data[SESSION_KEY] = session
    return session


def set_state(context: ContextTypes.DEFAULT_TYPE, state):
    session = context.user_data.get(SESSION_KEY) or start_session(context)
    session["state"] = state
    session["expires"] = time.time() + SESSION_TTL


def awaiting(context: ContextTypes.DEFAULT_TYPE):
    session = context.user_data.get(SESSION_KEY)

    if session and session["state"] and session["expires"] >= time.time():
        return session["state"]

    return None


# ==========================================
# TEXTS
# ==========================================

NO_THUMB = tiny("you have no thumbnail set yet")

STYLE_LABELS = {
    "none": tiny("plain"),
    "bold": tiny("bold"),
    "italic": tiny("italic"),
    "mono": tiny("mono"),
    "underline": tiny("underline"),
    "strike": tiny("strike"),
    "spoiler": tiny("spoiler"),
    "quote": tiny("quote"),
}


def main_text(cfg: dict) -> str:
    thumb = tiny("set") + " ✅" if cfg["thumb_file_id"] else tiny("not set") + " ❌"

    if cfg["channel_id"]:
        label = html.escape(cfg["channel_title"] or str(cfg["channel_id"]))
        channel = f"<code>{label}</code> ✅"
    else:
        channel = tiny("not set") + " ❌"

    return (
        f"⚙️ <b>{tiny('settings panel')}</b>\n\n"
        f"🖼 {tiny('thumbnail')} : {thumb}\n"
        f"✏️ {tiny('caption style')} : {STYLE_LABELS[cfg['caption_style']]}\n"
        f"📢 {tiny('channel')} : {channel}"
    )


def thumb_text(note: str = "") -> str:
    prefix = f"{note}\n\n" if note else ""

    return (
        f"{prefix}🖼 <b>{tiny('edit thumbnail')}</b>\n\n"
        f"{tiny('what each button does :')}\n\n"
        f"• <b>{tiny('set thumbnail')}</b> ➜ {tiny('send a photo and it is saved as your thumbnail')}\n"
        f"• <b>{tiny('del thumbnail')}</b> ➜ {tiny('removes your saved thumbnail')}\n"
        f"• <b>{tiny('show thumbnail')}</b> ➜ {tiny('shows your current thumbnail')}"
    )


def caption_text(cfg: dict) -> str:
    return (
        f"✏️ <b>{tiny('edit caption')}</b>\n\n"
        f"{tiny('pick a style. every file you send gets its caption in that style.')}\n"
        f"{tiny('plain keeps your original caption untouched.')}\n\n"
        f"{tiny('current style')} : {STYLE_LABELS[cfg['caption_style']]}"
    )


def channel_text(cfg: dict, note: str = "") -> str:
    prefix = f"{note}\n\n" if note else ""
    label = html.escape(cfg["channel_title"] or str(cfg["channel_id"]))

    return (
        f"{prefix}📢 <b>{tiny('channel')}</b>\n\n"
        f"{tiny('current channel')} : <code>{label}</code>\n"
        f"{tiny('your processed files are also posted there.')}"
    )


def ask_channel_text(note: str = "") -> str:
    prefix = f"{note}\n\n" if note else ""

    return (
        f"{prefix}📢 <b>{tiny('set channel')}</b>\n\n"
        f"{tiny('send your channel id (like -100xxxxxxxxxx) or @username.')}\n"
        f"{tiny('add me to that channel as admin with post permission first.')}"
    )


# ==========================================
# KEYBOARDS
# ==========================================

def _btn(label: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(tiny(label), callback_data=data)


def main_keyboard():
    return InlineKeyboardMarkup([
        [_btn("edit thumbnail", "set:thumb"), _btn("edit caption", "set:cap")],
        [_btn("set channel", "set:ch")],
        nav_row("back"),
    ])


def thumb_keyboard():
    return InlineKeyboardMarkup([
        [_btn("set thumbnail", "set:thumb:set")],
        [
            _btn("del thumbnail", "set:thumb:del"),
            _btn("show thumbnail", "set:thumb:show"),
        ],
        nav_row("set:main"),
    ])


def caption_keyboard(current: str):
    buttons = [
        InlineKeyboardButton(
            ("✅ " if key == current else "") + label,
            callback_data=f"set:cap:{key}",
        )
        for key, label in STYLE_LABELS.items()
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append(nav_row("set:main"))
    return InlineKeyboardMarkup(rows)


def channel_keyboard():
    # "del channel" only exists on this page, which is only reachable
    # once a channel has been saved.
    return InlineKeyboardMarkup([
        [_btn("del channel", "set:ch:del"), _btn("change channel", "set:ch:change")],
        nav_row("set:main"),
    ])


def ask_channel_keyboard():
    return InlineKeyboardMarkup([nav_row("set:main")])


# ==========================================
# PAGES
# ==========================================

async def show_main(chat_id, user_id, context):
    cfg = await setting_info.get_settings(user_id)
    await show_page(
        chat_id, context, main_text(cfg),
        video_url=SETTING_VIDEO_URL, keyboard=main_keyboard(),
    )


async def show_thumb_menu(chat_id, context, note=""):
    await show_page(chat_id, context, thumb_text(note), keyboard=thumb_keyboard())


async def show_caption_menu(chat_id, user_id, context):
    cfg = await setting_info.get_settings(user_id)
    await show_page(
        chat_id, context, caption_text(cfg),
        keyboard=caption_keyboard(cfg["caption_style"]),
    )


async def show_channel_menu(chat_id, user_id, context, note=""):
    cfg = await setting_info.get_settings(user_id)

    if cfg["channel_id"]:
        await show_page(
            chat_id, context, channel_text(cfg, note), keyboard=channel_keyboard()
        )
    else:
        await ask_channel(chat_id, context, note)


async def ask_channel(chat_id, context, note=""):
    set_state(context, AWAIT_CHANNEL)
    await show_page(
        chat_id, context, ask_channel_text(note), keyboard=ask_channel_keyboard()
    )


# ==========================================
# /setting COMMAND
# ==========================================

async def setting_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_session(context)  # fresh session for this user

    try:
        await show_main(update.effective_chat.id, update.effective_user.id, context)
    except Exception:
        log.exception("Unable to open settings")
        await update.message.reply_text(
            "❌ " + tiny("could not load your settings. please try again.")
        )


# ==========================================
# CALLBACKS
# ==========================================

async def setting_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    try:
        await _route(update, context)
    except Exception:
        log.exception("Setting callback failed: %s", query.data)
        try:
            await query.answer(
                tiny("something went wrong. please try again."), show_alert=True
            )
        except TelegramError:
            pass


async def _route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    chat_id = update.effective_chat.id

    # Any navigation cancels a pending input prompt
    if not context.user_data.get(SESSION_KEY):
        start_session(context)
    set_state(context, None)

    if data in ("setting", "set:main"):
        await query.answer()
        await show_main(chat_id, user_id, context)

    # ---------- thumbnail ----------
    elif data == "set:thumb":
        await query.answer()
        await show_thumb_menu(chat_id, context)

    elif data == "set:thumb:set":
        await query.answer()
        set_state(context, AWAIT_THUMB)
        await show_page(
            chat_id, context,
            f"🖼 <b>{tiny('send me a photo now')}</b>\n\n"
            f"{tiny('it will be saved as your thumbnail.')}",
            keyboard=InlineKeyboardMarkup([nav_row("set:thumb")]),
        )

    elif data == "set:thumb:del":
        cfg = await setting_info.get_settings(user_id)
        if not cfg["thumb_file_id"]:
            await query.answer(NO_THUMB, show_alert=True)
            return
        await setting_info.delete_thumbnail(user_id)
        await query.answer(tiny("thumbnail deleted"))
        await show_thumb_menu(chat_id, context, "🗑 " + tiny("thumbnail deleted."))

    elif data == "set:thumb:show":
        cfg = await setting_info.get_settings(user_id)
        if not cfg["thumb_file_id"]:
            await query.answer(NO_THUMB, show_alert=True)
            return
        await query.answer()
        await show_photo_page(
            chat_id, context,
            photo=cfg["thumb_file_id"],
            caption=tiny("your current thumbnail"),
            keyboard=InlineKeyboardMarkup([nav_row("set:thumb")]),
        )

    # ---------- caption ----------
    elif data == "set:cap":
        await query.answer()
        await show_caption_menu(chat_id, user_id, context)

    elif data.startswith("set:cap:"):
        style = data.split(":", 2)[2]
        if style not in CAPTION_STYLES:
            await query.answer()
            return
        await setting_info.set_caption_style(user_id, style)
        await query.answer(tiny("caption style saved"))
        await show_caption_menu(chat_id, user_id, context)

    # ---------- channel ----------
    elif data == "set:ch":
        await query.answer()
        await show_channel_menu(chat_id, user_id, context)

    elif data == "set:ch:change":
        await query.answer()
        await ask_channel(chat_id, context)

    elif data == "set:ch:del":
        cfg = await setting_info.get_settings(user_id)
        if not cfg["channel_id"]:
            await query.answer(tiny("you have no channel set yet"), show_alert=True)
            return
        await setting_info.delete_channel(user_id)
        await query.answer(tiny("channel deleted"))
        await show_main(chat_id, user_id, context)

    else:
        await query.answer()


# ==========================================
# INPUT HANDLERS
# ==========================================

async def on_photo_in_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Runs before the normal photo handler (group -1)."""
    if awaiting(context) != AWAIT_THUMB:
        return  # not in a session - normal handler saves the photo

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    try:
        file_id, thumb_bytes = await prepare_thumbnail(update.message.photo)
        await setting_info.set_thumbnail(user_id, file_id, thumb_bytes)
    except Exception:
        log.exception("Unable to save thumbnail from session")
        await update.message.reply_text(
            "❌ " + tiny("could not save your thumbnail. please try again.")
        )
        raise ApplicationHandlerStop

    set_state(context, None)
    await show_thumb_menu(chat_id, context, "✅ " + tiny("thumbnail saved."))

    raise ApplicationHandlerStop  # stop the normal photo handler


_CHANNEL_RE = re.compile(r"^(-?\d{5,20}|@[A-Za-z][A-Za-z0-9_]{3,31})$")


async def _validate_channel(context, user_id, raw: str):
    """Return (chat, None) when usable, otherwise (None, error text)."""
    text = raw.strip()
    text = re.sub(r"^https?://t\.me/", "@", text)

    if not _CHANNEL_RE.match(text):
        return None, tiny("that is not a valid channel id or @username.")

    target = int(text) if text.lstrip("-").isdigit() else text

    try:
        chat = await context.bot.get_chat(target)
    except TelegramError:
        return None, tiny("i cannot find that channel. add me as admin first.")

    if chat.type != ChatType.CHANNEL:
        return None, tiny("that is not a channel.")

    try:
        me = await context.bot.get_chat_member(chat.id, context.bot.id)
        member = await context.bot.get_chat_member(chat.id, user_id)
    except TelegramError:
        return None, tiny("i cannot check admins there. make me an admin.")

    bot_can_post = me.status == ChatMemberStatus.OWNER or (
        me.status == ChatMemberStatus.ADMINISTRATOR
        and getattr(me, "can_post_messages", False)
    )
    if not bot_can_post:
        return None, tiny("i need admin rights with post permission there.")

    if member.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
        return None, tiny("only an admin of that channel can set it.")

    return chat, None


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if awaiting(context) != AWAIT_CHANNEL:
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    chat, error = await _validate_channel(context, user_id, update.message.text)

    if error:
        await ask_channel(chat_id, context, "⚠️ " + error)
        return

    try:
        await setting_info.set_channel(user_id, chat.id, chat.title)
    except Exception:
        log.exception("Unable to save channel")
        await update.message.reply_text(
            "❌ " + tiny("could not save your channel. please try again.")
        )
        return

    set_state(context, None)
    await show_channel_menu(chat_id, user_id, context, "✅ " + tiny("channel saved."))


# ==========================================
# REGISTER
# ==========================================

def register_setting_handlers(app: Application):
    private = filters.ChatType.PRIVATE

    app.add_handler(CommandHandler("setting", setting_command, filters=private))

    app.add_handler(
        CallbackQueryHandler(setting_callback, pattern=r"^(setting|set:[a-z:]+)$")
    )

    app.add_handler(
        MessageHandler(private & filters.PHOTO, on_photo_in_session), group=-1
    )

    app.add_handler(
        MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_text)
    )
