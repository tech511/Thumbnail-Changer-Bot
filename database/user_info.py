"""Users collection - every user is stored once, on first contact."""

from datetime import datetime, timezone

from database.connection import get_db

COLLECTION = "users"


def _col():
    return get_db()[COLLECTION]


async def ensure_indexes():
    await _col().create_index("joined_at")


async def register_user(user) -> bool:
    """Save the user if unseen. Returns True only for a brand-new user.

    $setOnInsert + upsert is atomic, so two simultaneous updates from
    the same new user can never both count as "new".
    """
    result = await _col().update_one(
        {"_id": user.id},
        {
            "$setOnInsert": {
                "first_name": user.first_name,
                "last_name": user.last_name,
                "username": user.username,
                "language_code": user.language_code,
                "joined_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )

    return result.upserted_id is not None


async def count_users() -> int:
    return await _col().count_documents({})


async def iter_user_ids():
    """Every normal (not banned) user id - used by /broadcast."""
    async for doc in _col().find({}, {"_id": 1}):
        yield doc["_id"]


# Profile fields that are copied to / from the ban page
PROFILE_FIELDS = (
    "first_name",
    "last_name",
    "username",
    "language_code",
    "joined_at",
)


async def get_user(user_id: int):
    """The stored user document, or None when the user is unknown."""
    return await _col().find_one({"_id": user_id})


async def delete_user(user_id: int):
    await _col().delete_one({"_id": user_id})


async def restore_user(user_id: int, profile: dict):
    """Put a previously banned user back on the normal page.

    $setOnInsert keeps this safe to repeat and never overwrites a record
    that already exists.
    """
    fields = {key: profile.get(key) for key in PROFILE_FIELDS}

    await _col().update_one(
        {"_id": user_id},
        {"$setOnInsert": fields},
        upsert=True,
    )


async def list_users(skip: int, limit: int) -> list:
    """One page of users, newest first."""
    cursor = _col().find({}).sort("joined_at", -1).skip(skip).limit(limit)
    return [doc async for doc in cursor]
