import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

class AuthMiddleware:
    def __init__(self, allowed_users: list):
        self.allowed_users = set(allowed_users)

    def is_authorized(self, user_id: int) -> bool:
        return user_id in self.allowed_users

    async def check_auth(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """
        Check if user is authorized. Sends a rejection message if not.
        Returns True if authorized, False otherwise.
        """
        user_id = update.effective_user.id
        if not self.is_authorized(user_id):
            if update.message:
                await update.message.reply_text("❌ Unauthorized. Contact the bot administrator.")
            logger.warning(f"Unauthorized access attempt from user {user_id}")
            return False
        return True
