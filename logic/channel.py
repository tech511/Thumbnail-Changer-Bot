"""Channel permission checks shared by the settings panel and delivery."""

import logging

from telegram.constants import ChatMemberStatus
from telegram.error import NetworkError, RetryAfter, TelegramError

log = logging.getLogger(__name__)

# Failure reasons returned by check_channel_access()
BOT_NOT_ADMIN = "bot_not_admin"
BOT_NO_POST = "bot_no_post"
USER_NOT_ADMIN = "user_not_admin"
USER_NO_POST = "user_no_post"
UNAVAILABLE = "unavailable"
NETWORK = "network"

# Reasons that mean the user may no longer use this channel at all, so
# the saved channel setting is outdated and should be removed.
STALE_REASONS = (USER_NOT_ADMIN, USER_NO_POST)

# Plain, user-safe texts (callers wrap them with tiny()). They never
# contain internal or technical details.
REASON_TEXT = {
    BOT_NOT_ADMIN: "i need admin rights with post permission there.",
    BOT_NO_POST: "i need admin rights with post permission there.",
    USER_NOT_ADMIN: "only an admin of that channel can set it.",
    USER_NO_POST: "you need permission to post in that channel.",
    UNAVAILABLE: "i cannot check admins there. make me an admin.",
    NETWORK: "telegram did not respond. please try again in a moment.",
}


def _can_post(member) -> bool:
    if member.status == ChatMemberStatus.OWNER:
        return True

    return (
        member.status == ChatMemberStatus.ADMINISTRATOR
        and bool(getattr(member, "can_post_messages", False))
    )


async def check_channel_access(bot, chat_id, user_id):
    """Return None when both the bot and the user may post to the channel,
    otherwise one of the failure reasons above."""
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
        member = await bot.get_chat_member(chat_id, user_id)
    except (NetworkError, RetryAfter):
        return NETWORK
    except TelegramError:
        log.warning("Channel membership lookup failed for %s", chat_id)
        return UNAVAILABLE

    if me.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
        return BOT_NOT_ADMIN

    if not _can_post(me):
        return BOT_NO_POST

    if member.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
        return USER_NOT_ADMIN

    if not _can_post(member):
        return USER_NO_POST

    return None
