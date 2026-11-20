
import logging

from telegram.ext import Application

from config import BOT_TOKEN

from handlers.start import register_start_handlers
from logic.thumbnail import register_thumbnail_handlers


# ==========================================
# LOGGING
# ==========================================

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    level=logging.INFO
)

# Hide Telegram API request URLs containing bot tokens
logging.getLogger("httpx").setLevel(logging.WARNING)

# Keep other application logs
log = logging.getLogger(__name__)


# ==========================================
# MAIN FUNCTION
# ==========================================

def main():

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Register start menu handlers
    register_start_handlers(app)

    # Register thumbnail handlers
    register_thumbnail_handlers(app)

    log.info("Thumbnail Changer Bot started successfully!")

    # Start polling
    app.run_polling()


# ==========================================
# ENTRY POINT
# ==========================================

if __name__ == "__main__":
    main()
