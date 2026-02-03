
import logging
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes
from src.utils import validate_file_type, format_file_size
from src.bot.middleware.auth import AuthMiddleware

logger = logging.getLogger(__name__)

class MessageHandler:
    def __init__(self, auth_middleware: AuthMiddleware, session_manager):
        self.auth = auth_middleware
        self.session_manager = session_manager

    async def handle_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle file uploads."""
        user_id = update.effective_user.id
        
        if not await self.auth.check_auth(update, context):
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
