"""Ban page of the database.

Banned users live in their own collection ("banned_users"). Banning moves
a user off the normal pages (users + user_settings) onto this page, and
unbanning moves them back. Ban ids are also kept in memory so the bot can
reject a banned user on every update without touching the database; the
cache is rebuilt from the database on each start, so bans survive restarts.
"""

import logging
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from database import setting_info, user_info
from database.connection import get_db

log = logging.getLogger(__name__)

COLLECTION = "banned_users"

# Results of ban_user() / unban_user()
BANNED = "banned"
ALREADY_BANNED = "already_banned"
NOT_FOUND = "not_found"
UNBANNED = "unbanned"
NOT_BANNED = "not_banned"

DEFAULT_REASON = "no reason provided"

_banned_ids: set[int] = set()


def _col():
    return get_db()[COLLECTION]


async def ensure_indexes():
    await _col().create_index("banned_at")


async def load_cache():
    """Load every banned id into memory (call once at startup)."""
    ids = set()

    async for doc in _col().find({}, {"_id": 1}):
        ids.add(doc["_id"])

    _banned_ids.clear()
    _banned_ids.update(ids)
    log.info("Loaded %d banned user(s)", len(ids))


def is_banned(user_id: int) -> bool:
    return user_id in _banned_ids


async def get_ban(user_id: int):
    return await _col().find_one({"_id": user_id})


async def ban_user(user_id: int, reason: str | None, banned_by: int) -> str:
    """Move a user from the normal pages to the ban page.

    Returns ALREADY_BANNED, NOT_FOUND (no record in the database) or BANNED.
    """
    if await get_ban(user_id):
        _banned_ids.add(user_id)
        return ALREADY_BANNED

    profile = await user_info.get_user(user_id)

    if profile is None:
        return NOT_FOUND

    record = {key: profile.get(key) for key in user_info.PROFILE_FIELDS}
    record.update(
        {
            "_id": user_id,
            "reason": reason or DEFAULT_REASON,
            "banned_at": datetime.now(timezone.utc),
            "banned_by": banned_by,
        }
    )

    # The ban record is written first: from this moment the user is
    # banned even if the clean-up below were interrupted.
    try:
        await _col().insert_one(record)
    except DuplicateKeyError:
        _banned_ids.add(user_id)
        return ALREADY_BANNED

    _banned_ids.add(user_id)

    # Remove the user from the main pages (profile + settings)
    for cleanup in (user_info.delete_user, setting_info.delete_settings):
        try:
            await cleanup(user_id)
        except Exception:
            log.exception("Ban clean-up step failed for %s", user_id)

    return BANNED


async def unban_user(user_id: int) -> str:
    """Move a user from the ban page back to the normal page.

    Returns NOT_BANNED (no ban record) or UNBANNED.
    """
    record = await get_ban(user_id)

    if record is None:
        _banned_ids.discard(user_id)
        return NOT_BANNED

    # Restore first, delete second: an interruption can leave the user in
    # both places (still banned), never in neither.
    await user_info.restore_user(user_id, record)
    await _col().delete_one({"_id": user_id})
    _banned_ids.discard(user_id)

    return UNBANNED


async def count_banned() -> int:
    return await _col().count_documents({})


async def list_banned(skip: int, limit: int) -> list:
    """One page of banned users, most recent ban first."""
    cursor = _col().find({}).sort("banned_at", -1).skip(skip).limit(limit)
    return [doc async for doc in cursor]
