"""Access helpers. The bot is public; use @owner_only for admin commands."""

from functools import wraps

from config import OWNER_ID


def is_owner(user_id) -> bool:
    return bool(OWNER_ID) and user_id == OWNER_ID


def owner_only(func):
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        user = update.effective_user

        if not user or not is_owner(user.id):
            return  # stay silent for everyone else

        return await func(update, context, *args, **kwargs)

    return wrapper
