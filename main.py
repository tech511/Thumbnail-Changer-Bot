import logging

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


async def post_init(app: Application):
    await setting_info.ensure_indexes()
    await user_info.ensure_indexes()
    await restrictions.ensure_indexes()
    await restrictions.load_cache()   # banned users survive restarts
    log.info("Database ready")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled exception", exc_info=context.error)


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    register_ban_handlers(app)        # ban gate (group -3) + /ban
    register_tracker(app)             # new-user tracking (group -2)
    register_setting_handlers(app)    # /setting panel
    register_start_handlers(app)      # /start, help, about
    register_thumbnail_handlers(app)  # photo / video / document logic
    register_unban_handlers(app)      # /unban (owner)
    register_records_handlers(app)    # /records (owner)
    register_broadcast_handlers(app)  # /broadcast (owner)

    app.add_error_handler(on_error)

    log.info("Thumbnail Changer Bot started successfully!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
