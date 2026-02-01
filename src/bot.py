"""
AgenticGram - Main Telegram Bot
Provides remote control interface for AI CLI tools via Telegram.
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from .utils import (
    setup_logging,
    load_environment,
    validate_file_type,
    sanitize_message,
    format_file_size,
    ensure_directory
)
from .session_manager import SessionManager
from .orchestrator import Orchestrator
from .directory_browser import DirectoryBrowser


logger = logging.getLogger(__name__)


class AgenticGramBot:
    """Main bot class for AgenticGram."""
    
    def __init__(self, config: dict):
        """
        Initialize the bot.
        
        Args:
            config: Configuration dictionary from environment
        """
        self.config = config
        self.allowed_users = set(config["ALLOWED_TELEGRAM_IDS"])
        self.permission_timeout = config["PERMISSION_TIMEOUT_MINUTES"] * 60  # Convert to seconds
        
        # Initialize components
        self.session_manager = SessionManager(
            work_dir_base=config["WORK_DIR"]
        )
        self.orchestrator = Orchestrator(
            session_manager=self.session_manager,
            openrouter_api_key=config.get("OPENROUTER_API_KEY"),
            claude_code_path=config.get("CLAUDE_CODE_PATH")
        )
        
        # Set permission callback
        self.orchestrator.set_permission_callback(self._handle_permission_request)
        
        # Track pending permission requests
        self.pending_permissions: Dict[str, asyncio.Future] = {}
        
        # Initialize directory browser
        self.directory_browser = DirectoryBrowser(
            start_dir=config["BROWSE_START_DIR"],
            allowed_base_dirs=config["ALLOWED_BASE_DIRS"],
            blocked_dirs=config["BLOCKED_DIRS"],
            max_dirs_per_page=config["MAX_DIRS_PER_PAGE"]
        )
        
        # Track user navigation state (current_path per user)
        self.user_navigation: Dict[int, str] = {}
        
        # Build application
        self.app = Application.builder().token(config["TELEGRAM_BOT_TOKEN"]).build()
        self._register_handlers()
    
    def _register_handlers(self) -> None:
        """Register command and message handlers."""
        # Command handlers
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        self.app.add_handler(CommandHandler("code", self._cmd_code))
        self.app.add_handler(CommandHandler("session", self._cmd_session))
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(CommandHandler("browse", self._cmd_browse))
        
        # File upload handler
        self.app.add_handler(MessageHandler(filters.Document.ALL, self._handle_file))
        
        # Callback query handler for inline buttons
        self.app.add_handler(CallbackQueryHandler(self._handle_callback))
        
        logger.info("Handlers registered successfully")
    
    def _check_authorization(self, user_id: int) -> bool:
        """
        Check if user is authorized.
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            True if authorized, False otherwise
        """
        return user_id in self.allowed_users
    
    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        user_id = update.effective_user.id
        
        if not self._check_authorization(user_id):
            await update.message.reply_text("❌ Unauthorized. Contact the bot administrator.")
            logger.warning(f"Unauthorized access attempt from user {user_id}")
            return
        
        welcome_message = (
            "🤖 **Welcome to AgenticGram!**\n\n"
            "I'm your AI coding assistant bridge. I can execute commands via Claude Code CLI "
            "or fallback to OpenRouter when needed.\n\n"
            "**Available Commands:**\n"
            "/code <instruction> - Execute an AI coding instruction\n"
            "/browse - Browse and select working directory\n"
            "/session - Manage your session (new/clear/info)\n"
            "/status - Check backend availability\n"
            "/help - Show this help message\n\n"
            "You can also send me code files (.py, .sql, .js) and I'll save them to your workspace!"
        )
        
        await update.message.reply_text(welcome_message, parse_mode="Markdown")
        logger.info(f"User {user_id} started the bot")
    
    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        user_id = update.effective_user.id
        
        if not self._check_authorization(user_id):
            await update.message.reply_text("❌ Unauthorized.")
            return
        
        help_message = (
            "📚 **AgenticGram Help**\n\n"
            "**Commands:**\n"
            "• `/code <instruction>` - Execute coding instruction\n"
            "  Example: `/code Create a Python function to calculate fibonacci`\n\n"
            "• `/browse [path]` - Browse and select working directory\n"
            "  Navigate through directories with inline buttons\n\n"
            "• `/session new` - Start a new session\n"
            "• `/session clear` - Clear current session\n"
            "• `/session info` - Show session information\n\n"
            "• `/status` - Check AI backend availability\n\n"
            "**File Uploads:**\n"
            "Send me code files and I'll save them to your workspace.\n"
            "Supported: .py, .sql, .js, .txt, .json, .md\n\n"
            "**Permission System:**\n"
            "When Claude Code needs to edit files or run commands, "
            "I'll ask for your approval with inline buttons. "
            f"You have {self.config['PERMISSION_TIMEOUT_MINUTES']} minutes to respond."
        )
        
        await update.message.reply_text(help_message, parse_mode="Markdown")
    
    async def _cmd_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /code command."""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        if not self._check_authorization(user_id):
            await update.message.reply_text("❌ Unauthorized.")
            return
        
        # Get instruction from command arguments
        if not context.args:
            await update.message.reply_text(
                "❌ Please provide an instruction.\n"
                "Usage: `/code <your instruction>`",
                parse_mode="Markdown"
            )
            return
        
        instruction = " ".join(context.args)
        
        # Send typing indicator
        await update.message.chat.send_action("typing")
        
        # Execute command
        logger.info(f"Executing code command for user {user_id}: {instruction[:50]}...")
        
        try:
            result = await self.orchestrator.execute_command(
                instruction=instruction,
                telegram_id=user_id,
                chat_id=chat_id
            )
            
            if result["success"]:
                output = result["output"]
                backend = result.get("backend", "unknown")
                
                # Prepare response
                response = f"✅ **Completed** (via {backend})\n\n"
                
                # Chunk and send output
                chunks = sanitize_message(output)
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await update.message.reply_text(
                            response + f"```\n{chunk}\n```",
                            parse_mode="Markdown"
                        )
                    else:
                        await update.message.reply_text(
                            f"```\n{chunk}\n```",
                            parse_mode="Markdown"
                        )
            else:
                error = result.get("error", "Unknown error")
                await update.message.reply_text(
                    f"❌ **Error:** {error}",
                    parse_mode="Markdown"
                )
        
        except Exception as e:
            logger.error(f"Error executing code command: {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ **Unexpected error:** {str(e)}",
                parse_mode="Markdown"
            )
    
    async def _cmd_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /session command."""
        user_id = update.effective_user.id
        
        if not self._check_authorization(user_id):
            await update.message.reply_text("❌ Unauthorized.")
            return
        
        if not context.args:
            await update.message.reply_text(
                "Usage:\n"
                "/session new - Create new session\n"
                "/session clear - Clear current session\n"
                "/session info - Show session info"
            )
            return
        
        action = context.args[0].lower()
        
        if action == "new":
            session = self.session_manager.create_session(user_id)
            await update.message.reply_text(
                f"✅ New session created!\n"
                f"Session ID: `{session.session_id}`\n"
                f"Workspace: `{session.work_dir}`",
                parse_mode="Markdown"
            )
        
        elif action == "clear":
            if self.session_manager.delete_session(user_id):
                await update.message.reply_text("✅ Session cleared!")
            else:
                await update.message.reply_text("ℹ️ No active session to clear.")
        
        elif action == "info":
            session = self.session_manager.get_session(user_id)
            if session:
                await update.message.reply_text(
                    f"📊 **Session Info**\n\n"
                    f"Session ID: `{session.session_id}`\n"
                    f"Created: {session.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"Last used: {session.last_used.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"Messages: {session.message_count}\n"
                    f"Workspace: `{session.work_dir}`",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("ℹ️ No active session. Use `/session new` to create one.")
        
        else:
            await update.message.reply_text("❌ Unknown action. Use: new, clear, or info")
    
    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command."""
        user_id = update.effective_user.id
        
        if not self._check_authorization(user_id):
            await update.message.reply_text("❌ Unauthorized.")
            return
        
        await update.message.chat.send_action("typing")
        
        # Check backend availability
        claude_available = await self.orchestrator.check_claude_availability()
        openrouter_available = await self.orchestrator.check_openrouter_availability()
        
        status_message = "🔍 **Backend Status**\n\n"
        status_message += f"Claude Code CLI: {'✅ Available' if claude_available else '❌ Unavailable'}\n"
        status_message += f"OpenRouter API: {'✅ Available' if openrouter_available else '❌ Unavailable'}\n"
        
        await update.message.reply_text(status_message, parse_mode="Markdown")
    
    async def _cmd_browse(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /browse command to navigate directories."""
        user_id = update.effective_user.id
        
        if not self._check_authorization(user_id):
            await update.message.reply_text("❌ Unauthorized.")
            return
        
        # Determine starting directory
        if context.args:
            start_path = " ".join(context.args)
        else:
            start_path = self.directory_browser.start_dir
        
        # Validate directory
        is_safe, error_msg = self.directory_browser.is_safe_directory(str(start_path))
        if not is_safe:
            await update.message.reply_text(
                f"❌ Cannot access directory: {error_msg}\n\n"
                f"Starting from default: `{self.directory_browser.format_directory_path(str(self.directory_browser.start_dir))}`",
                parse_mode="Markdown"
            )
            start_path = self.directory_browser.start_dir
        
        # Store current path for user
        self.user_navigation[user_id] = str(start_path)
        
        # Get directory info and keyboard
        info = self.directory_browser.get_directory_info(str(start_path))
        keyboard = self.directory_browser.create_navigation_keyboard(str(start_path))
        
        await update.message.reply_text(
            info + "\n\nSelect a folder to navigate or choose an action:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        logger.info(f"User {user_id} started browsing from {start_path}")
    
    async def _handle_directory_callback(self, query) -> None:
        """Handle directory navigation callback queries."""
        user_id = query.from_user.id
        data = query.data
        
        try:
            # Parse callback data
            parts = data.split("_", 2)
            action = parts[1]
            
            if action == "cancel":
                await query.edit_message_text("❌ Directory selection cancelled.")
                self.user_navigation.pop(user_id, None)
                return
            
            # Decode path from callback data
            if len(parts) >= 3:
                if action == "page":
                    # Format: dir_page_<encoded_path>_<page_num>
                    path_and_page = parts[2].rsplit("_", 1)
                    encoded_path = path_and_page[0]
                    page = int(path_and_page[1])
                    current_path = self.directory_browser.decode_path(encoded_path)
                else:
                    encoded_path = parts[2]
                    current_path = self.directory_browser.decode_path(encoded_path)
                    page = 0
            else:
                await query.edit_message_text("❌ Invalid navigation data.")
                return
            
            # Validate directory
            is_safe, error_msg = self.directory_browser.is_safe_directory(current_path)
            if not is_safe:
                await query.edit_message_text(f"❌ Cannot access directory: {error_msg}")
                return
            
            # Handle different actions
            if action == "select":
                # User selected this directory
                session = self.session_manager.set_work_directory(user_id, current_path)
                if session:
                    await query.edit_message_text(
                        f"✅ **Working directory set!**\n\n"
                        f"Selected: `{self.directory_browser.format_directory_path(current_path, 60)}`\n"
                        f"Workspace: `{session.work_dir}`\n\n"
                        f"You can now use `/code` commands in this workspace.",
                        parse_mode="Markdown"
                    )
                    logger.info(f"User {user_id} set work directory to {current_path}")
                else:
                    # Failed to set directory - likely permission issue
                    await query.edit_message_text(
                        f"❌ **Failed to set working directory**\n\n"
                        f"The bot doesn't have write permissions in:\n"
                        f"`{self.directory_browser.format_directory_path(current_path, 60)}`\n\n"
                        f"**Solutions:**\n"
                        f"1. Choose a different directory with write access\n"
                        f"2. Grant permissions:\n"
                        f"   `chmod -R 755 {current_path}`\n"
                        f"   or\n"
                        f"   `sudo chown -R $USER:$USER {current_path}`\n\n"
                        f"Use `/browse` to try again.",
                        parse_mode="Markdown"
                    )
                    logger.error(f"User {user_id} failed to set work directory: {current_path}")
                
                self.user_navigation.pop(user_id, None)
                return
            
            elif action == "open":
                # Navigate into subdirectory
                self.user_navigation[user_id] = current_path
            
            elif action == "up":
                # Navigate to parent directory
                self.user_navigation[user_id] = current_path
            
            elif action == "page":
                # Change page
                pass  # current_path and page already set
            
            # Update message with new directory view
            info = self.directory_browser.get_directory_info(current_path)
            keyboard = self.directory_browser.create_navigation_keyboard(current_path, page)
            
            await query.edit_message_text(
                info + "\n\nSelect a folder to navigate or choose an action:",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Error handling directory callback: {e}", exc_info=True)
            await query.edit_message_text(f"❌ Error: {str(e)}")
    
    async def _handle_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle file uploads."""
        user_id = update.effective_user.id
        
        if not self._check_authorization(user_id):
            await update.message.reply_text("❌ Unauthorized.")
            return
        
        document = update.message.document
        filename = document.file_name
        
        # Validate file type
        if not validate_file_type(filename):
            await update.message.reply_text(
                "❌ Unsupported file type. Allowed: .py, .sql, .js, .txt, .json, .md"
            )
            return
        
        # Get or create session
        session = self.session_manager.get_session(user_id)
        if not session:
            session = self.session_manager.create_session(user_id)
        
        # Download file
        try:
            file = await document.get_file()
            file_path = Path(session.work_dir) / filename
            await file.download_to_drive(str(file_path))
            
            file_size = format_file_size(document.file_size)
            
            await update.message.reply_text(
                f"✅ File saved!\n"
                f"Name: `{filename}`\n"
                f"Size: {file_size}\n"
                f"Location: `{file_path}`",
                parse_mode="Markdown"
            )
            
            logger.info(f"User {user_id} uploaded file: {filename}")
        
        except Exception as e:
            logger.error(f"Error handling file upload: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error saving file: {str(e)}")
    
    async def _handle_permission_request(
        self,
        action_type: str,
        details: dict
    ) -> bool:
        """
        Handle permission request from Claude Code.
        This is called by the orchestrator when Claude needs approval.
        
        Args:
            action_type: Type of action (file_edit, command_exec, etc.)
            details: Details about the action
            
        Returns:
            True if approved, False if denied
        """
        # Generate unique request ID
        request_id = str(uuid.uuid4())
        
        # Create future for async response
        future = asyncio.Future()
        self.pending_permissions[request_id] = future
        
        # This would need to be sent to the appropriate chat
        # For now, we'll implement a simplified version
        # In production, you'd need to track which chat_id is associated with the current command
        
        try:
            # Wait for user response with timeout
            async with asyncio.timeout(self.permission_timeout):
                approved = await future
                return approved
        except asyncio.TimeoutError:
            logger.warning(f"Permission request {request_id} timed out")
            return False
        finally:
            # Clean up
            self.pending_permissions.pop(request_id, None)
    
    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline keyboard button callbacks."""
        query = update.callback_query
        await query.answer()
        
        # Check if it's a directory navigation callback
        if query.data.startswith("dir_"):
            await self._handle_directory_callback(query)
            return
        
        # Parse callback data: "permission_<request_id>_<approve|deny>"
        data_parts = query.data.split("_")
        if len(data_parts) != 3 or data_parts[0] != "permission":
            await query.edit_message_text("❌ Invalid callback data")
            return
        
        request_id = data_parts[1]
        action = data_parts[2]
        
        # Get pending permission future
        future = self.pending_permissions.get(request_id)
        if not future:
            await query.edit_message_text("⏱️ This permission request has expired.")
            return
        
        # Set result
        approved = (action == "approve")
        future.set_result(approved)
        
        # Update message
        result_text = "✅ Approved" if approved else "❌ Denied"
        await query.edit_message_text(
            f"{query.message.text}\n\n**Decision:** {result_text}"
        )
    
    async def run(self) -> None:
        """Run the bot."""
        logger.info("Starting AgenticGram bot...")
        
        # Start cleanup task
        if self.config["AUTO_CLEANUP_SESSIONS"]:
            asyncio.create_task(self._cleanup_task())
        
        # Run bot
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        
        logger.info("Bot is running!")
        
        # Keep running
        try:
            await asyncio.Event().wait()
        finally:
            await self.shutdown()
    
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


async def main():
    """Main entry point."""
    # Load configuration
    try:
        config = load_environment()
    except ValueError as e:
        print(f"Configuration error: {e}")
        return
    
    # Setup logging
    setup_logging(
        log_level=config["LOG_LEVEL"],
        log_file=config["LOG_FILE"] if config["LOG_FILE"] else None
    )
    
    # Create and run bot
    bot = AgenticGramBot(config)
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
