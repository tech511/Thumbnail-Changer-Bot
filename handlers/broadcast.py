"""/broadcast (owner only): reply to a post to send it to every user."""

import asyncio
import html
import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import (
    BadRequest,
    Forbidden,
    NetworkError,
    RetryAfter,
    TelegramError,
)
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

STATE_KEY = "broadcast_state"

BATCH_SIZE = 20          # messages sent at the same time
BATCH_PAUSE = 1.0        # seconds between batches (Telegram ~30 msg/s)
REFRESH_SECONDS = 2      # progress message refresh interval
SEND_TIMEOUT = 30
MAX_ATTEMPTS = 3
BAR_WIDTH = 12

USAGE = (
    "📣 " + tiny("reply to the post you want to send with") + " <code>/broadcast</code>"
)


# ==========================================
# PROGRESS MESSAGE
# ==========================================

def _bar(done: int, total: int) -> str:
    filled = BAR_WIDTH if total == 0 else int(BAR_WIDTH * done / total)
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def _percent(done: int, total: int) -> int:
    return 100 if total == 0 else int(done * 100 / total)


def _progress_text(state: dict, final: str | None = None) -> str:
    done = state["sent"] + state["failed"]
    total = state["total"]
    elapsed = int(time.monotonic() - state["started"])

    title = final or tiny("broadcasting...")

    return (
        f"📣 <b>{title}</b>\n\n"
        f"<code>{_bar(done, total)}</code> <code>{_percent(done, total)}%</code>\n\n"
        f"👥 {tiny('total users')} : <code>{total}</code>\n"
        f"✅ {tiny('received')} : <code>{state['sent']}</code>\n"
        f"❌ {tiny('not received / failed')} : <code>{state['failed']}</code>\n"
        f"⏱ {tiny('time')} : <code>{elapsed}s</code>"
    )


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🛑 " + tiny("cancel"), callback_data="bc:cancel")]]
    )


async def _edit(message, text: str, keyboard=None):
    """Edit the progress message; display problems never stop a broadcast."""
    try:
        await message.edit_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )
    except RetryAfter:
        pass
    except BadRequest:
        pass  # "message is not modified" and similar
    except TelegramError:
        log.warning("Unable to update broadcast progress")


# ==========================================
# SENDING
# ==========================================

def _wait_seconds(error: RetryAfter) -> float:
    value = error.retry_after
    return float(value.total_seconds() if hasattr(value, "total_seconds") else value)


async def _copy_to(bot, chat_id, from_chat_id, message_id, markup) -> bool:
    """Copy the post to one user. True = delivered, False = not delivered.

    copy_message sends the post as a fresh message, so there is no
    "forwarded from" label, and the original buttons are passed along.
    """
    for _ in range(MAX_ATTEMPTS):
        try:
            await asyncio.wait_for(
                bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                    reply_markup=markup,
                ),
                timeout=SEND_TIMEOUT,
            )
            return True

        except RetryAfter as exc:
            await asyncio.sleep(_wait_seconds(exc) + 1)

        except (Forbidden, BadRequest):
            return False  # blocked the bot, deactivated, chat not found...

        except (NetworkError, asyncio.TimeoutError):
            await asyncio.sleep(1)

        except TelegramError:
            return False

    return False


async def _run(context, state, user_ids, from_chat_id, message_id, markup):
    bot = context.bot

    for start in range(0, len(user_ids), BATCH_SIZE):
        if state["cancel"].is_set():
            break

        batch = user_ids[start:start + BATCH_SIZE]

        results = await asyncio.gather(
            *(_copy_to(bot, uid, from_chat_id, message_id, markup) for uid in batch),
            return_exceptions=True,
        )

        for result in results:
            if result is True:
                state["sent"] += 1
            else:
                state["failed"] += 1  # False or an unexpected exception

        await asyncio.sleep(BATCH_PAUSE)


async def _broadcast_job(context, state, progress, user_ids, from_chat_id, message_id, markup):
    """Background job: sends everything while refreshing the progress."""
    final = None

    try:
        sender = asyncio.create_task(
            _run(context, state, user_ids, from_chat_id, message_id, markup)
        )

        while not sender.done():
            await asyncio.wait({sender}, timeout=REFRESH_SECONDS)

            if not sender.done():
                await _edit(progress, _progress_text(state), _cancel_keyboard())

        sender.result()  # re-raise an unexpected error, if any

        final = tiny("broadcast cancelled") if state["cancel"].is_set() \
            else tiny("broadcast completed")

    except Exception:
        log.exception("Broadcast crashed")
        final = tiny("broadcast stopped by an error")

    finally:
        context.bot_data.pop(STATE_KEY, None)

    await _edit(progress, _progress_text(state, final))


# ==========================================
# COMMAND
# ==========================================

@owner_only
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    post = message.reply_to_message

    if post is None:
        await message.reply_text(USAGE, parse_mode=ParseMode.HTML)
        return

    if context.bot_data.get(STATE_KEY):
        await message.reply_text(
            "⚠️ " + tiny("a broadcast is already running. wait or cancel it.")
        )
        return

    # Claim the slot before the first await so two commands cannot overlap
    state = {
        "sent": 0,
        "failed": 0,
        "total": 0,
        "started": time.monotonic(),
        "cancel": asyncio.Event(),
    }
    context.bot_data[STATE_KEY] = state

    try:
        # Preview to the owner: proves the post can be copied before
        # anyone else receives it.
        markup = post.reply_markup

        try:
            await context.bot.copy_message(
                chat_id=message.chat_id,
                from_chat_id=post.chat_id,
                message_id=post.message_id,
                reply_markup=markup,
            )
        except TelegramError:
            log.warning("Broadcast preview failed", exc_info=True)
            context.bot_data.pop(STATE_KEY, None)
            await message.reply_text(
                "❌ " + tiny("this kind of message cannot be broadcast.")
            )
            return

        user_ids = [
            uid
            async for uid in user_info.iter_user_ids()
            if uid != update.effective_user.id and not restrictions.is_banned(uid)
        ]
        state["total"] = len(user_ids)

        progress = await message.reply_text(
            _progress_text(state),
            parse_mode=ParseMode.HTML,
            reply_markup=_cancel_keyboard(),
        )
    except Exception:
        context.bot_data.pop(STATE_KEY, None)
        log.exception("Unable to start broadcast")
        await message.reply_text("❌ " + tiny("could not start the broadcast."))
        return

    # Runs in the background so the bot keeps answering everyone else
    context.application.create_task(
        _broadcast_job(
            context, state, progress, user_ids, post.chat_id, post.message_id, markup
        ),
        update=update,
    )


@owner_only
async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.bot_data.get(STATE_KEY)

    if not state:
        await update.callback_query.answer(
            tiny("no broadcast is running."), show_alert=True
        )
        return

    state["cancel"].set()
    await update.callback_query.answer(tiny("cancelling..."))


def register_broadcast_handlers(app: Application):
    if not OWNER_ID:
        return

    app.add_handler(
        CommandHandler("broadcast", broadcast_command, filters=filters.ChatType.PRIVATE)
    )
    app.add_handler(CallbackQueryHandler(broadcast_cancel, pattern=r"^bc:cancel$"))
