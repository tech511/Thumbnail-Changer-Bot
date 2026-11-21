"""Per-user settings stored in MongoDB (one document per user id)."""

from datetime import datetime, timezone

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


async def get_settings(user_id: int) -> dict:
    """Saved settings merged over defaults (always returns every key)."""
    doc = await _col().find_one({"user_id": user_id}) or {}
    settings = {key: doc.get(key, default) for key, default in DEFAULTS.items()}

    if settings["thumb_bytes"] is not None:
        settings["thumb_bytes"] = bytes(settings["thumb_bytes"])

    if settings["caption_style"] not in CAPTION_STYLES:
        settings["caption_style"] = "none"

    return settings


async def save_settings(user_id: int, settings: dict):
    """Replace the old setting document with the new one.

    replace_one(upsert) does "remove old, insert new" in one atomic
    step, so a crash can never leave the user without a document.
    """
    doc = {key: settings.get(key, default) for key, default in DEFAULTS.items()}
    doc["user_id"] = user_id
    doc["updated_at"] = datetime.now(timezone.utc)

    await _col().replace_one({"user_id": user_id}, doc, upsert=True)


async def _update(user_id: int, **changes) -> dict:
    settings = await get_settings(user_id)
    settings.update(changes)
    await save_settings(user_id, settings)
    return settings


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


async def delete_channel(user_id: int):
    return await _update(user_id, channel_id=None, channel_title=None)


async def delete_settings(user_id: int):
    await _col().delete_one({"user_id": user_id})

