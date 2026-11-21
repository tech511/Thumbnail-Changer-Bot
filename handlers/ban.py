"""/ban (owner only) and the gate that blocks banned users."""

import html
import logging
import re

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CommandHandler,
    ContextTypes,
    TypeHandler,
    filters,
)

from config import OWNER_ID
from database import restrictions
from utils.auth import is_owner, owner_only
from utils.ui import tiny

log = logging.getLogger(__name__)

MAX_REASON_LENGTH = 200
_USER_ID_RE = re.compile(r"^\d{1,15}$")

BAN_USAGE = (
    f"⚠️ {tiny('usage')} : <code>/ban {{user_id}} [reason]</code>"
)


def parse_user_id(raw: str):
    """A positive Telegram user id from text, or None."""
    if not _USER_ID_RE.match(raw or ""):
        return None

    user_id = int(raw)
    return user_id if user_id > 0 else None


@owner_only
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    args = context.args or []

    user_id = parse_user_id(args[0]) if args else None

    if user_id is None:
        await message.reply_text(BAN_USAGE, parse_mode=ParseMode.HTML)
        return

    if is_owner(user_id) or user_id == context.bot.id:
        await message.reply_text("❌ " + tiny("this user cannot be banned."))
        return

    reason = " ".join(args[1:]).strip()[:MAX_REASON_LENGTH] or None

    try:
        result = await restrictions.ban_user(
            user_id, reason, update.effective_user.id
        )
    except Exception:
        log.exception("Ban failed for %s", user_id)
        await message.reply_text("❌ " + tiny("database error. please try again."))
        return

    code = f"<code>{user_id}</code>"

    if result == restrictions.ALREADY_BANNED:
        text = f"⚠️ {code} {tiny('is already banned.')}"

    elif result == restrictions.NOT_FOUND:
        text = f"⚠️ {code} {tiny('has no record in the database.')}"

    else:
        shown = html.escape(reason or restrictions.DEFAULT_REASON)
        text = (
            f"🚫 <b>{tiny('user banned')}</b>\n\n"
            f"🆔 {tiny('id')} : {code}\n"
            f"📝 {tiny('reason')} : {shown}"
        )

        # The user may have blocked the bot, so this is best effort
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🚫 {tiny('you have been banned from using this bot.')}\n"
                     f"📝 {tiny('reason')} : {shown}",
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass

        # Forget the "already registered" shortcut kept by the tracker
        context.bot_data.get("known_users", set()).discard(user_id)

    await message.reply_text(text, parse_mode=ParseMode.HTML)


async def block_banned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Runs before everything else (group -3): banned users get nothing."""
    user = update.effective_user

    if not user or is_owner(user.id) or not restrictions.is_banned(user.id):
        return

    try:
        if update.callback_query:
            await update.callback_query.answer(
                tiny("you are banned from using this bot."), show_alert=True
            )
        elif (
            update.effective_message
            and update.effective_chat
            and update.effective_chat.type == ChatType.PRIVATE
        ):
            await update.effective_message.reply_text(
                "🚫 " + tiny("you are banned from using this bot.")
            )
    except TelegramError:
        pass

    # Also keeps the tracker from re-registering a banned user
    raise ApplicationHandlerStop


def register_ban_handlers(app: Application):
    app.add_handler(TypeHandler(Update, block_banned), group=-3)

    if OWNER_ID:
        app.add_handler(
            CommandHandler("ban", ban_command, filters=filters.ChatType.PRIVATE)
        )
