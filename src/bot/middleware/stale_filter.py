"""
Stale Filter Middleware.
Prevents processing of updates that occurred while the bot was offline.
"""

import logging
import time
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

class StaleFilterMiddleware:
    """Filters out updates that are older than the bot's start time."""
    
    def __init__(self, cutoff_seconds: int = 120):
        """
        Initialize the filter.
        
        Args:
            cutoff_seconds: Maximum age of updates to process (relative to now)
                            Note: This is just a fallback. Primary check is vs start time.
        """
        self.start_time = datetime.now(timezone.utc)
        self.cutoff_seconds = cutoff_seconds
        logger.info(f"Stale filter initialized. Ignoring updates older than {self.start_time}")

    async def check_stale(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """
        Check if an update is stale.
        
        Args:
            update: The update to check
            
        Returns:
            True if stale (should be ignored), False otherwise
        """
        message = update.message or update.effective_message
        if not message:
            return False
            
        # Get message date (aware datetime in UTC)
        msg_date = message.date
        
        # If message date is older than start time, it's stale
        if msg_date < self.start_time:
            logger.info(f"Ignored stale update from {msg_date} (Bot started: {self.start_time})")
            return True
            
        return False
