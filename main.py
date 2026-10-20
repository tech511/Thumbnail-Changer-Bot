from pyrogram import Client

from config import API_ID, API_HASH, BOT_TOKEN
from handle.start import register_start
from handle.setting import register_settings
from callback import register_callbacks
from handle.prossing import register_processing

app = Client(
    "thumbnail_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

register_start(app)
register_settings(app)
register_callbacks(app)
register_processing(app)

if __name__ == "__main__":
    app.run()
