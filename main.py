import logging

from telegram import Update
from telegram.ext import Application, ContextTypes

from config import BOT_TOKEN
from database import setting_info, user_info
from handlers.setting import register_setting_handlers
from handlers.start import register_start_handlers
from handlers.tracker import register_tracker
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
    log.info("Database ready")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled exception", exc_info=context.error)


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    register_tracker(app)             # new-user tracking (group -2)
    register_setting_handlers(app)    # /setting panel
    register_start_handlers(app)      # /start, help, about
    register_thumbnail_handlers(app)  # photo / video / document logic

    app.add_error_handler(on_error)

    log.info("Thumbnail Changer Bot started successfully!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
