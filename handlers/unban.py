"""/unban (owner only)."""

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from config import OWNER_ID
from database import restrictions
from handlers.ban import parse_user_id
from utils.auth import owner_only
from utils.ui import tiny

log = logging.getLogger(__name__)

UNBAN_USAGE = f"⚠️ {tiny('usage')} : <code>/unban {{user_id}}</code>"


@owner_only
async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    args = context.args or []

    user_id = parse_user_id(args[0]) if len(args) == 1 else None

    if user_id is None:
        await message.reply_text(UNBAN_USAGE, parse_mode=ParseMode.HTML)
        return

    try:
        result = await restrictions.unban_user(user_id)
    except Exception:
        log.exception("Unban failed for %s", user_id)
        await message.reply_text("❌ " + tiny("database error. please try again."))
        return

    code = f"<code>{user_id}</code>"

    if result == restrictions.NOT_BANNED:
        text = f"⚠️ {code} {tiny('is not banned.')}"

    else:
        text = (
            f"✅ <b>{tiny('user unbanned')}</b>\n\n"
            f"🆔 {tiny('id')} : {code}"
        )

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ " + tiny("you have been unbanned. you can use the bot again."),
            )
        except TelegramError:
            pass  # the user may have blocked the bot

    await message.reply_text(text, parse_mode=ParseMode.HTML)


def register_unban_handlers(app: Application):
    if OWNER_ID:
        app.add_handler(
            CommandHandler("unban", unban_command, filters=filters.ChatType.PRIVATE)
        )
