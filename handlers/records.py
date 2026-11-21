"""/records (owner only): paged list of users and banned users."""

import html
import logging
import math

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

from config import OWNER_ID
from database import restrictions, user_info
from utils.auth import owner_only
from utils.ui import tiny

log = logging.getLogger(__name__)

PAGE_SIZE = 10
MAX_NAME = 24

KIND_USERS = "u"
KIND_BANNED = "b"


def _date(value) -> str:
    return value.strftime("%Y-%m-%d") if value else "—"


def _name(doc: dict) -> str:
    full = " ".join(
        part for part in (doc.get("first_name"), doc.get("last_name")) if part
    )
    return html.escape((full or "—")[:MAX_NAME])


def _entry(number: int, doc: dict, kind: str) -> str:
    username = f"@{html.escape(doc['username'])}" if doc.get("username") else "—"

    line = (
        f"<b>{number}.</b> <a href=\"tg://user?id={doc['_id']}\">{_name(doc)}</a>\n"
        f"    🆔 <code>{doc['_id']}</code> · {username}\n"
    )

    if kind == KIND_BANNED:
        reason = html.escape(str(doc.get("reason") or "—")[:80])
        line += (
            f"    📝 {reason}\n"
            f"    🚫 {tiny('banned')} {_date(doc.get('banned_at'))}\n"
        )
    else:
        line += f"    📅 {tiny('joined')} {_date(doc.get('joined_at'))}\n"

    return line


async def _render(kind: str, page: int):
    """Build (text, keyboard) for one page; the page is clamped to range."""
    if kind == KIND_BANNED:
        total = await restrictions.count_banned()
        title = tiny("banned users")
    else:
        total = await user_info.count_users()
        title = tiny("users")

    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    skip = page * PAGE_SIZE

    if kind == KIND_BANNED:
        docs = await restrictions.list_banned(skip, PAGE_SIZE)
    else:
        docs = await user_info.list_users(skip, PAGE_SIZE)

    header = (
        f"📋 <b>{title}</b> · {tiny('total')} <code>{total}</code>\n"
        f"📄 {tiny('page')} <code>{page + 1}/{pages}</code>\n\n"
    )

    if docs:
        body = "\n".join(
            _entry(skip + index + 1, doc, kind) for index, doc in enumerate(docs)
        )
    else:
        body = tiny("nothing to show here yet.")

    nav = []

    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "⬅️ " + tiny("previous"), callback_data=f"rec:{kind}:{page - 1}"
            )
        )

    nav.append(
        InlineKeyboardButton(f"{page + 1}/{pages}", callback_data=f"rec:{kind}:{page}")
    )

    if page < pages - 1:
        nav.append(
            InlineKeyboardButton(
                tiny("next") + " ➡️", callback_data=f"rec:{kind}:{page + 1}"
            )
        )

    if kind == KIND_BANNED:
        switch = InlineKeyboardButton("👥 " + tiny("users"), callback_data="rec:u:0")
    else:
        switch = InlineKeyboardButton("🚫 " + tiny("banned"), callback_data="rec:b:0")

    keyboard = InlineKeyboardMarkup(
        [
            nav,
            [switch, InlineKeyboardButton("✖️ " + tiny("close"), callback_data="rec:close")],
        ]
    )

    return header + body, keyboard


@owner_only
async def records_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text, keyboard = await _render(KIND_USERS, 0)
    except Exception:
        log.exception("Unable to load records")
        await update.effective_message.reply_text(
            "❌ " + tiny("database error. please try again.")
        )
        return

    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


@owner_only
async def records_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split(":")

    if data[1] == "close":
        try:
            await query.message.delete()
        except TelegramError:
            pass
        return

    kind, page = data[1], int(data[2])

    try:
        text, keyboard = await _render(kind, page)
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            log.warning("Unable to edit records page: %s", exc)
    except Exception:
        log.exception("Unable to refresh records")


def register_records_handlers(app: Application):
    if not OWNER_ID:
        return

    app.add_handler(
        CommandHandler("records", records_command, filters=filters.ChatType.PRIVATE)
    )
    app.add_handler(
        CallbackQueryHandler(records_callback, pattern=r"^rec:(?:[ub]:\d{1,6}|close)$")
    )
