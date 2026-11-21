"""Registers each new user once and reports them to the log channel."""

import html
import logging

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes, TypeHandler

from config import LOG_CHANNEL
from database import user_info
from utils.ui import tiny

log = logging.getLogger(__name__)


def _new_user_text(user, total) -> str:
    name = html.escape(user.full_name)
    username = f"@{html.escape(user.username)}" if user.username else "—"

    return (
        f"🆕 <b>{tiny('new user')}</b>\n\n"
        f"👤 {tiny('name')} : <a href=\"tg://user?id={user.id}\">{name}</a>\n"
        f"🆔 {tiny('id')} : <code>{user.id}</code>\n"
        f"🔗 {tiny('username')} : {username}\n"
        f"🌐 {tiny('language')} : {html.escape(user.language_code or '—')}\n"
        f"📊 {tiny('total users')} : <code>{total}</code>"
    )


async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if not user or user.is_bot or not chat or chat.type != ChatType.PRIVATE:
        return

    known = context.bot_data.setdefault("known_users", set())

    if user.id in known:
        return  # already checked since startup - skip the database

    try:
        is_new = await user_info.register_user(user)
    except Exception:
        log.exception("Unable to register user %s", user.id)
        return

    known.add(user.id)

    if not is_new or not LOG_CHANNEL:
        return

    try:
        total = await user_info.count_users()
        await context.bot.send_message(
            chat_id=LOG_CHANNEL,
            text=_new_user_text(user, total),
            parse_mode=ParseMode.HTML,
        )
    except (TelegramError, Exception):
        log.exception("Unable to send new-user log")


def register_tracker(app: Application):
    # group -2: runs before everything else and never blocks other handlers
    app.add_handler(TypeHandler(Update, track_user), group=-2)
