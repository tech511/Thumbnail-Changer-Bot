"""Ban page of the database.

Banned users live in their own collection ("banned_users"). Banning moves
a user off the normal pages (users + user_settings) onto this page, and
unbanning moves them back. The user's settings (thumbnail, caption style,
channel) are kept on the ban record under "settings" so unbanning restores
them. Ban ids are also kept in memory so the bot can
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


MAX_CLEANUP_ATTEMPTS = 3


async def _finish_ban(user_id: int, record: dict):
    """Remove the user from the main pages once their settings are safe.

    The settings are copied onto the ban record first and the original is
    only deleted if it is still exactly what was copied. If it changed in
    the meantime, the newer values are merged into the copy and the delete
    is tried again. Anything that keeps failing is left in place (never
    lost) and is cleaned up by the next /ban of the same user.
    """
    snapshot = record.get("settings")

    for _ in range(MAX_CLEANUP_ATTEMPTS):
        current = await setting_info.export_settings(user_id)

        if current is None:
            break  # nothing (left) on the main page

        merged = setting_info.merge_snapshots(snapshot, current)

        if merged != snapshot:
            await _col().update_one({"_id": user_id}, {"$set": {"settings": merged}})
            snapshot = merged

        if await setting_info.delete_settings_if_unchanged(
            user_id, current.get("updated_at")
        ):
            break

    try:
        await user_info.delete_user(user_id)
    except Exception:
        log.exception("Ban clean-up step failed for %s", user_id)


async def ban_user(user_id: int, reason: str | None, banned_by: int) -> str:
    """Move a user from the normal pages to the ban page.

    Returns ALREADY_BANNED, NOT_FOUND (no record in the database) or BANNED.
    """
    existing = await get_ban(user_id)

    if existing:
        _banned_ids.add(user_id)

        # Finish a ban that an earlier interruption left half done
        try:
            await _finish_ban(user_id, existing)
        except Exception:
            log.exception("Ban clean-up failed for %s", user_id)

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
            "settings": await setting_info.export_settings(user_id),
        }
    )

    # The ban record (with the settings copy) is written first: from this
    # moment the user is banned and their settings are safe, even if the
    # clean-up below were interrupted.
    try:
        await _col().insert_one(record)
    except DuplicateKeyError:
        _banned_ids.add(user_id)
        return ALREADY_BANNED

    _banned_ids.add(user_id)

    try:
        await _finish_ban(user_id, record)
    except Exception:
        log.exception("Ban clean-up failed for %s", user_id)

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
    # both places (still banned), never in neither. Both restores keep
    # anything that already exists, so repeating /unban is safe.
    await user_info.restore_user(user_id, record)
    await setting_info.restore_settings(user_id, record.get("settings"))
    await _col().delete_one({"_id": user_id})
    _banned_ids.discard(user_id)

    return UNBANNED


async def count_banned() -> int:
    return await _col().count_documents({})


async def list_banned(skip: int, limit: int) -> list:
    """One page of banned users, most recent ban first."""
    # "settings" can hold a thumbnail, so it is not loaded for listings
    cursor = (
        _col()
        .find({}, {"settings": 0})
        .sort("banned_at", -1)
        .skip(skip)
        .limit(limit)
    )
    return [doc async for doc in cursor]
