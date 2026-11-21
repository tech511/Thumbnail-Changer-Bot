"""Per-user settings stored in MongoDB (one document per user id)."""

from datetime import datetime, timezone

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from database.connection import get_db
from utils.caption import CAPTION_STYLES

COLLECTION = "user_settings"

DEFAULTS = {
    "thumb_file_id": None,
    "thumb_bytes": None,
    "caption_style": "none",
    "channel_id": None,
    "channel_title": None,
}


def _col():
    return get_db()[COLLECTION]


async def ensure_indexes():
    await _col().create_index("user_id", unique=True)


def _normalize(doc: dict) -> dict:
    """Merge a stored document over the defaults (always every key)."""
    settings = {key: doc.get(key, default) for key, default in DEFAULTS.items()}

    if settings["thumb_bytes"] is not None:
        settings["thumb_bytes"] = bytes(settings["thumb_bytes"])

    if settings["caption_style"] not in CAPTION_STYLES:
        settings["caption_style"] = "none"

    return settings


async def get_settings(user_id: int) -> dict:
    """Saved settings merged over defaults (always returns every key)."""
    doc = await _col().find_one({"user_id": user_id}) or {}
    return _normalize(doc)


async def _apply(user_id: int, changes: dict) -> dict:
    """Atomically update only the given fields and return the result.

    A single upsert with $set touches nothing but the keys in `changes`,
    so concurrent updates to different settings can never overwrite one
    another (no read-modify-write cycle). $setOnInsert gives a brand-new
    document its default values for every key not being set.
    """
    changes = {key: value for key, value in changes.items() if key in DEFAULTS}
    now = datetime.now(timezone.utc)

    update = {
        "$set": {**changes, "updated_at": now},
        "$setOnInsert": {
            "user_id": user_id,
            **{k: v for k, v in DEFAULTS.items() if k not in changes},
        },
    }

    # Two first-time upserts for the same user can race on the unique
    # index; the loser simply retries and becomes a normal update.
    for attempt in range(2):
        try:
            doc = await _col().find_one_and_update(
                {"user_id": user_id},
                update,
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            break
        except DuplicateKeyError:
            if attempt:
                raise

    return _normalize(doc or {})


async def save_settings(user_id: int, settings: dict):
    """Save the given settings keys without touching any other key."""
    return await _apply(user_id, settings)


async def _update(user_id: int, **changes) -> dict:
    return await _apply(user_id, changes)


# ---- thumbnail ----

async def set_thumbnail(user_id: int, file_id: str, thumb_bytes: bytes):
    return await _update(
        user_id, thumb_file_id=file_id, thumb_bytes=thumb_bytes
    )


async def delete_thumbnail(user_id: int):
    return await _update(user_id, thumb_file_id=None, thumb_bytes=None)


# ---- caption ----

async def set_caption_style(user_id: int, style: str):
    if style not in CAPTION_STYLES:
        raise ValueError(f"Unknown caption style: {style}")

    return await _update(user_id, caption_style=style)


# ---- channel ----

async def set_channel(user_id: int, channel_id: int, title: str | None):
    return await _update(user_id, channel_id=channel_id, channel_title=title)


async def delete_channel(user_id: int, expected_channel_id: int | None = None):
    """Clear the saved channel (id and title together).

    With `expected_channel_id` the channel is only cleared if it is still
    the one the caller checked, so a newer choice is never wiped by a
    stale background check.
    """
    if expected_channel_id is None:
        return await _update(user_id, channel_id=None, channel_title=None)

    await _col().update_one(
        {"user_id": user_id, "channel_id": expected_channel_id},
        {
            "$set": {
                "channel_id": None,
                "channel_title": None,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )
    return await get_settings(user_id)


async def delete_settings(user_id: int):
    await _col().delete_one({"user_id": user_id})

