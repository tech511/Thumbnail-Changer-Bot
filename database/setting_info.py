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


# ---- ban / unban support ----

# Settings that belong together and are saved / restored as one unit
_GROUPS = (
    ("thumb_file_id", "thumb_bytes"),
    ("caption_style",),
    ("channel_id", "channel_title"),
)


def _is_default(key: str, value) -> bool:
    return value is None or value == DEFAULTS[key]


def _group_is_default(snapshot: dict, group) -> bool:
    return all(_is_default(key, snapshot.get(key)) for key in group)


async def export_settings(user_id: int):
    """Raw copy of the stored settings (plus `updated_at`), or None.

    Used to keep a user's settings on the ban record. None means the user
    has no settings document at all.
    """
    doc = await _col().find_one({"user_id": user_id})

    if doc is None:
        return None

    snapshot = {key: doc.get(key, default) for key, default in DEFAULTS.items()}

    if snapshot["thumb_bytes"] is not None:
        snapshot["thumb_bytes"] = bytes(snapshot["thumb_bytes"])

    snapshot["updated_at"] = doc.get("updated_at")
    return snapshot


def merge_snapshots(old: dict | None, current: dict) -> dict:
    """Newer values win, but defaults never erase a saved value."""
    if old is None:
        return dict(current)

    merged = dict(old)

    for group in _GROUPS:
        if not _group_is_default(current, group):
            for key in group:
                merged[key] = current.get(key)

    merged["updated_at"] = current.get("updated_at")
    return merged


async def delete_settings_if_unchanged(user_id: int, updated_at) -> bool:
    """Delete the settings only if nobody changed them since `updated_at`.

    Returns True when the document is gone afterwards (deleted now, or it
    did not exist), False when it was changed in the meantime and so kept.
    """
    result = await _col().delete_one(
        {"user_id": user_id, "updated_at": updated_at}
    )

    if result.deleted_count:
        return True

    return await _col().find_one({"user_id": user_id}, {"_id": 1}) is None


async def restore_settings(user_id: int, snapshot: dict | None):
    """Put settings saved by export_settings() back for an unbanned user.

    Safe to repeat and never overwrites newer settings:
      1. a missing document is created in one atomic upsert (the unique
         user_id index rules out duplicates);
      2. for an existing document, only groups that still hold their
         default values are filled in from the snapshot.
    """
    if not snapshot:
        return

    values = {key: snapshot.get(key) for key in DEFAULTS}

    if values["thumb_bytes"] is not None:
        values["thumb_bytes"] = bytes(values["thumb_bytes"])

    if values["caption_style"] not in CAPTION_STYLES:
        values["caption_style"] = DEFAULTS["caption_style"]

    now = datetime.now(timezone.utc)

    try:
        await _col().update_one(
            {"user_id": user_id},
            {
                "$setOnInsert": {
                    "user_id": user_id,
                    **values,
                    "updated_at": snapshot.get("updated_at") or now,
                }
            },
            upsert=True,
        )
    except DuplicateKeyError:
        pass  # created concurrently: fall through to the fill-in below

    for group in _GROUPS:
        if _group_is_default(values, group):
            continue

        await _col().update_one(
            {
                "user_id": user_id,
                **{key: {"$in": [DEFAULTS[key], None]} for key in group},
            },
            {"$set": {**{key: values[key] for key in group}, "updated_at": now}},
        )
