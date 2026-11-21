from pymongo import AsyncMongoClient

from config import MONGO_URL, DB_NAME

_client = None


def get_db():
    """Lazy client so it binds to the running event loop."""
    global _client

    if _client is None:
        _client = AsyncMongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)

    return _client[DB_NAME]
