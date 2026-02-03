
import logging
import subprocess
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes
from src.bot.middleware.auth import AuthMiddleware

logger = logging.getLogger(__name__)

class BrowserCommands:
    def __init__(self, auth_middleware: AuthMiddleware, directory_browser, session_manager):
        self.auth = auth_middleware
        self.directory_browser = directory_browser
        self.session_manager = session_manager
        # Track user navigation state (current_path per user)
        self.user_navigation = {}

    async def browse(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /browse command to navigate directories."""
        user_id = update.effective_user.id
        
        if not await self.auth.check_auth(update, context):
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

    async def trust(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /trust command to trust a directory for Claude CLI."""
        user_id = update.effective_user.id
        
        if not await self.auth.check_auth(update, context):
            return
        
        if context.args:
            directory = " ".join(context.args)
        else:
            session = self.session_manager.get_session(user_id)
            if not session:
                await update.message.reply_text(
                    "❌ No directory specified and no active session.\n\n"
                    "Usage: `/trust <directory_path>`\n"
                    "Example: `/trust /home/tony/projects`",
                    parse_mode="Markdown"
                )
                return
            directory = session.work_dir
        
        try:
            resolved_path = Path(directory).resolve()
            
            if not resolved_path.exists():
                await update.message.reply_text(f"❌ Directory does not exist: `{directory}`", parse_mode="Markdown")
                return
            
            if not resolved_path.is_dir():
                await update.message.reply_text(f"❌ Path is not a directory: `{directory}`", parse_mode="Markdown")
                return
            
            # Run claude trust command
            result = subprocess.run(
                ["claude", "trust", str(resolved_path)],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                await update.message.reply_text(
                    f"✅ **Directory Trusted**\n\n"
                    f"Claude will no longer ask for permissions in:\n`{resolved_path}`",
                    parse_mode="Markdown"
                )
                logger.info(f"User {user_id} trusted directory: {resolved_path}")
            else:
                error = result.stderr or result.stdout or "Unknown error"
                await update.message.reply_text(
                    f"❌ **Failed to trust directory**\n\nError: `{error}`",
                    parse_mode="Markdown"
                )
                
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}", parse_mode="Markdown")
            logger.error(f"Error in /trust command: {e}", exc_info=True)

    async def handle_callback(self, query):
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
            
            # ... (Rest of navigation logic) ...
            # To keep lines low, I will implement minimal logic here and assume reusable methods?
            # Or just copy paste. It's complex logic.
            # I'll implement the rest below.
            
            if len(parts) >= 3:
                 if action == "page":
                     path_and_page = parts[2].rsplit("_", 1)
                     path_id = path_and_page[0]
                     page = int(path_and_page[1])
                     current_path = self.directory_browser.get_path(path_id)
                 else:
                     path_id = parts[2]
                     current_path = self.directory_browser.get_path(path_id)
                     page = 0
                 
                 if not current_path:
                      await query.edit_message_text("❌ Navigation session expired. Use /browse to start again.")
                      return
            else:
                 await query.edit_message_text("❌ Invalid navigation data.")
                 return
            
            is_safe, error_msg = self.directory_browser.is_safe_directory(current_path)
            if not is_safe:
                await query.edit_message_text(f"❌ Cannot access directory: {error_msg}")
                return
            
            if action == "select":
                session = self.session_manager.set_work_directory(user_id, current_path)
                if session:
                    await query.edit_message_text(
                        f"✅ **Working directory set!**\nSelected: `{current_path}`",
                        parse_mode="Markdown"
                    )
                else:
                    await query.edit_message_text("❌ Failed to set working directory.")
                self.user_navigation.pop(user_id, None)
                return
            
            elif action == "open":
                self.user_navigation[user_id] = current_path
            elif action == "up":
                self.user_navigation[user_id] = current_path
            
            # Update view
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
