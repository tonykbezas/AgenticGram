
import logging
import asyncio
from telegram.ext import Application, CommandHandler as TelegramCommandHandler, MessageHandler as TelegramMessageHandler, CallbackQueryHandler, filters, TypeHandler, ApplicationHandlerStop
from telegram import Update, BotCommand
from telegram.request import HTTPXRequest

from src.claude.session_manager import SessionManager
from src.orchestrator import Orchestrator
from src.directory_browser import DirectoryBrowser
from src.bot.middleware.auth import AuthMiddleware
from src.bot.middleware.stale_filter import StaleFilterMiddleware
from src.bot.handlers.basic_commands import BasicCommands
from src.bot.handlers.code_commands import CodeCommands
from src.bot.handlers.browser_commands import BrowserCommands
from src.bot.handlers.message_handler import MessageHandler as MyMessageHandler
from src.bot.handlers.permission_handler import PermissionHandler

logger = logging.getLogger(__name__)

# Bot commands for Telegram menu
BOT_COMMANDS = [
    BotCommand("code", "Execute AI coding instruction"),
    BotCommand("stop", "Stop running agent"),
    BotCommand("new", "Start fresh conversation"),
    BotCommand("model", "Select Claude model"),
    BotCommand("bypass", "Toggle bypass mode"),
    BotCommand("browse", "Browse working directory"),
    BotCommand("session", "Manage session"),
    BotCommand("status", "Check backend status"),
    BotCommand("help", "Show help"),
]

class AgenticGramBot:
    """Main bot class for AgenticGram."""
    
    def __init__(self, config: dict):
        self.config = config
        
        # Initialize components
        self.session_manager = SessionManager(
            work_dir_base=config["WORK_DIR"]
        )
        self.orchestrator = Orchestrator(
            session_manager=self.session_manager,
            openrouter_api_key=config.get("OPENROUTER_API_KEY"),
            claude_code_path=config.get("CLAUDE_CODE_PATH"),
            notification_callback=self.send_notification
        )
        
        self.directory_browser = DirectoryBrowser(
            start_dir=config["BROWSE_START_DIR"],
            allowed_base_dirs=config["ALLOWED_BASE_DIRS"],
            blocked_dirs=config["BLOCKED_DIRS"],
            max_dirs_per_page=config["MAX_DIRS_PER_PAGE"]
        )
        
        # Build application
        request = HTTPXRequest(
            connect_timeout=20.0,
            read_timeout=20.0,
            write_timeout=20.0,
            pool_timeout=20.0,
        )
        self.app = Application.builder().token(config["TELEGRAM_BOT_TOKEN"]).request(request).build()
        
        # Initialize middleware
        self.auth_middleware = AuthMiddleware(config["ALLOWED_TELEGRAM_IDS"])
        self.stale_filter = StaleFilterMiddleware()
        
        # Initialize handlers
        self.basic_commands = BasicCommands(self.auth_middleware, self.session_manager, self.orchestrator)
        self.code_commands = CodeCommands(self.auth_middleware, self.orchestrator)
        self.browser_commands = BrowserCommands(self.auth_middleware, self.directory_browser, self.session_manager)
        self.message_handler = MyMessageHandler(self.auth_middleware, self.session_manager, self.orchestrator)
        
        # Permission handler (requires app)
        self.permission_handler = PermissionHandler(self.app, config)
        self.orchestrator.set_permission_callback(self.permission_handler.handle_request)
        
        self._register_handlers()

    async def send_notification(self, user_id: int, message: str) -> None:
        """
        Send a notification to a user.
        
        Args:
            user_id: Telegram user ID
            message: Message text to send
        """
        try:
            await self.app.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to send notification to {user_id}: {e}")
        
    def _register_handlers(self) -> None:
        """Register command and message handlers."""
        
        # Register Middleware (Group -1)
        # Stale filter
        async def stale_check(update: Update, context):
            if await self.stale_filter.check_stale(update, context):
                raise ApplicationHandlerStop
        self.app.add_handler(TypeHandler(Update, stale_check), group=-1)

        # Command handlers
        self.app.add_handler(TelegramCommandHandler("start", self.basic_commands.start))
        self.app.add_handler(TelegramCommandHandler("help", self.basic_commands.help))
        self.app.add_handler(TelegramCommandHandler("session", self.basic_commands.session))
        self.app.add_handler(TelegramCommandHandler("status", self.basic_commands.status))
        self.app.add_handler(TelegramCommandHandler("bypass", self.basic_commands.bypass))
        self.app.add_handler(TelegramCommandHandler("model", self.basic_commands.model))
        self.app.add_handler(TelegramCommandHandler("new", self.basic_commands.new_conversation))
        self.app.add_handler(TelegramCommandHandler("stop", self.basic_commands.stop))

        self.app.add_handler(TelegramCommandHandler("code", self.code_commands.code))
        
        self.app.add_handler(TelegramCommandHandler("browse", self.browser_commands.browse))
        self.app.add_handler(TelegramCommandHandler("trust", self.browser_commands.trust))
        
        # File upload handler
        self.app.add_handler(TelegramMessageHandler(filters.Document.ALL, self.message_handler.handle_file))

        # Text message handler (process as Claude instruction - no /code needed)
        self.app.add_handler(TelegramMessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.message_handler.handle_text
        ))

        # Callback query handler
        self.app.add_handler(CallbackQueryHandler(self._handle_callback))

        logger.info("Handlers registered successfully")

    async def _handle_callback(self, update, context):
        """Central callback dispatcher."""
        query = update.callback_query
        data = query.data

        if data.startswith("dir_"):
            await self.browser_commands.handle_callback(query)
        elif data.startswith("perm_"):
            await self.permission_handler.handle_callback(update, context)
        elif data.startswith("model_"):
            await self.basic_commands.handle_model_callback(update, context)
        else:
            await query.answer()
            logger.warning(f"Unknown callback data: {data}")

    async def run(self) -> None:
        """Run the bot."""
        logger.info("Starting AgenticGram bot...")

        # Start cleanup task
        if self.config["AUTO_CLEANUP_SESSIONS"]:
            asyncio.create_task(self._cleanup_task())

        # Run bot
        await self.app.initialize()
        await self.app.start()

        # Set bot commands menu
        await self._setup_commands_menu()

        await self.app.updater.start_polling()

        logger.info("Bot is running!")

        # Keep running
        try:
            await asyncio.Event().wait()
        finally:
            await self.shutdown()

    async def _setup_commands_menu(self) -> None:
        """Setup the bot commands menu in Telegram."""
        try:
            await self.app.bot.set_my_commands(BOT_COMMANDS)
            logger.info("Bot commands menu configured")
        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}")

    async def _cleanup_task(self) -> None:
        """Periodic cleanup of old sessions."""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour
                count = self.session_manager.cleanup_old_sessions(
                    self.config["MAX_SESSION_AGE_HOURS"]
                )
                if count > 0:
                    logger.info(f"Cleaned up {count} old sessions")
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}", exc_info=True)

    async def shutdown(self) -> None:
        """Shutdown the bot gracefully."""
        logger.info("Shutting down bot...")
        await self.orchestrator.cleanup()
        await self.app.stop()
        await self.app.shutdown()
        logger.info("Bot shutdown complete")
