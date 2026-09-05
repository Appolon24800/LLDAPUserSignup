"""Entry point: build the Application and run long polling."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
)

from .auth import UserRateLimiter
from .backend_client import BackendClient
from .config import BotConfig
from .handlers import cmd_gen, cmd_list, cmd_revoke, cmd_start, on_error, on_picker_callback


def build_application(config: BotConfig) -> Application:
    app = Application.builder().token(config.telegram_bot_token).build()
    app.bot_data["admin_ids"] = config.admin_ids
    app.bot_data["rate_limiter"] = UserRateLimiter()
    app.bot_data["backend"] = BackendClient(config.backend_url, config.internal_api_key)

    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("gen", cmd_gen))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("revoke", cmd_revoke))
    app.add_handler(CallbackQueryHandler(on_picker_callback))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = BotConfig.from_env()
    app = build_application(config)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
