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
    """Handy for future owner-only commands such as broadcast."""
    async for doc in _col().find({}, {"_id": 1}):
        yield doc["_id"]
