
import logging
import os
import threading

from flask import Flask
from telegram import Update
from telegram.ext import Application, ContextTypes

from config import BOT_TOKEN
from database import restrictions, setting_info, user_info
from handlers.ban import register_ban_handlers
from handlers.broadcast import register_broadcast_handlers
from handlers.records import register_records_handlers
from handlers.setting import register_setting_handlers
from handlers.start import register_start_handlers
from handlers.tracker import register_tracker
from handlers.unban import register_unban_handlers
from logic.thumbnail import register_thumbnail_handlers


logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    level=logging.INFO,
)

# Hide Telegram API request URLs containing bot tokens
logging.getLogger("httpx").setLevel(logging.WARNING)

log = logging.getLogger(__name__)


# Flask health-check server
web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "Thumbnail Changer Bot is running!", 200


@web_app.route("/health")
def health():
    return {"status": "ok"}, 200


async def post_init(app: Application):
    await setting_info.ensure_indexes()
    await user_info.ensure_indexes()
    await restrictions.ensure_indexes()
    await restrictions.load_cache()

    log.info("Database ready")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled exception", exc_info=context.error)


def main():
    # Start Flask health server in background thread
    port = int(os.environ.get("PORT", 10000))

    web_thread = threading.Thread(
        target=lambda: web_app.run(
            host="0.0.0.0",
            port=port,
            use_reloader=False
        ),
        daemon=True
    )
    web_thread.start()

    # Initialize Telegram bot
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    register_ban_handlers(app)
    register_tracker(app)
    register_setting_handlers(app)
    register_start_handlers(app)
    register_thumbnail_handlers(app)
    register_unban_handlers(app)
    register_records_handlers(app)
    register_broadcast_handlers(app)

    app.add_error_handler(on_error)

    log.info("Thumbnail Changer Bot started successfully!")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
