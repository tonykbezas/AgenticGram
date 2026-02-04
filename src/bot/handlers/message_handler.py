
import logging
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes
from src.utils import validate_file_type, format_file_size
from src.bot.middleware.auth import AuthMiddleware
from src.telegram.message_sender import MessageSender

logger = logging.getLogger(__name__)


class MessageHandler:
    def __init__(self, auth_middleware: AuthMiddleware, session_manager, orchestrator=None):
        self.auth = auth_middleware
        self.session_manager = session_manager
        self.orchestrator = orchestrator

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

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle text messages as Claude instructions (no /code needed)."""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

        if not await self.auth.check_auth(update, context):
            return

        # Get instruction from message text
        instruction = update.message.text.strip()

        if not instruction:
            return

        # Check if orchestrator is available
        if not self.orchestrator:
            await update.message.reply_text(
                "❌ Bot not fully configured. Use /code command instead."
            )
            return

        # Get or create session
        session = self.session_manager.get_session(user_id)
        if not session:
            session = self.session_manager.create_session(user_id)

        # Check if work directory exists
        work_dir = Path(session.work_dir)
        if not work_dir.exists():
            await update.message.reply_text(
                "⚠️ **No working directory configured**\n\n"
                "Use /browse to select a working directory first.",
                parse_mode="Markdown"
            )
            return

        # Send typing indicator
        await update.message.chat.send_action("typing")

        # Send initial status message
        status_message = await update.message.reply_text(
            "🤖 **Claude is working...**\n\n_Waiting for response..._",
            parse_mode="Markdown"
        )

        logger.info(f"Processing text message from user {user_id}: {instruction[:50]}...")

        # Initialize MessageSender
        sender = MessageSender(status_message)

        # Stream callback
        async def stream_callback(output: str):
            await sender.update_stream(output)

        try:
            result = await self.orchestrator.execute_command(
                instruction=instruction,
                telegram_id=user_id,
                chat_id=chat_id,
                output_callback=stream_callback
            )

            await sender.send_final(result, instruction=instruction)

        except Exception as e:
            logger.error(f"Error executing text command: {e}", exc_info=True)
            try:
                await status_message.edit_text(
                    f"❌ **Error:** {str(e)}",
                    parse_mode="Markdown"
                )
            except:
                await update.message.reply_text(
                    f"❌ **Error:** {str(e)}",
                    parse_mode="Markdown"
                )
