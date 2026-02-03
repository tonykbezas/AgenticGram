
import logging
import time
from telegram import Update
from telegram.ext import ContextTypes
from src.bot.middleware.auth import AuthMiddleware
from src.telegram.message_sender import MessageSender

logger = logging.getLogger(__name__)

class CodeCommands:
    def __init__(self, auth_middleware: AuthMiddleware, orchestrator):
        self.auth = auth_middleware
        self.orchestrator = orchestrator

    async def code(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /code command."""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        if not await self.auth.check_auth(update, context):
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
        
        # Set current chat_id logic
        context.bot_data['current_chat_id'] = chat_id
        
        # Send initial status message
        status_message = await update.message.reply_text(
            "🤖 **Claude is working...**\n\n_Waiting for response..._",
            parse_mode="Markdown"
        )
        
        logger.info(f"Executing code command for user {user_id}: {instruction[:50]}...")
        
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
            
            await sender.send_final(result)
        
        except Exception as e:
            logger.error(f"Error executing code command: {e}", exc_info=True)
            try:
                await status_message.edit_text(
                    f"❌ **Unexpected error:** {str(e)}",
                    parse_mode="Markdown"
                )
            except:
                await update.message.reply_text(
                    f"❌ **Unexpected error:** {str(e)}",
                    parse_mode="Markdown"
                )
