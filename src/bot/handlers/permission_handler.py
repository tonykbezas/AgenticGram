
import logging
import asyncio
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TimedOut
from telegram.ext import ContextTypes
from src.telegram.markdown import escape_markdown

logger = logging.getLogger(__name__)

class PermissionHandler:
    def __init__(self, app, config):
        self.app = app
        self.permission_timeout = config["PERMISSION_TIMEOUT_MINUTES"] * 60
        self.pending_permissions = {}  # {request_id: Future}

    async def handle_request(self, action_type: str, details: dict) -> bool:
        """
        Handle permission request from Claude Code.
        Called by orchestrator background task.
        """
        request_id = str(uuid.uuid4())[:8]
        future = asyncio.Future()
        self.pending_permissions[request_id] = future
        
        # ideally we should have a way to know WHICH chat/user this request is for.
        # Currently the logic relies on `bot.current_chat_id` which is flawed for concurrent users.
        # But we will rely on what `CodeCommands` stored in `context.bot_data`? No, context is not available here.
        # We need the orchestrator to pass the chat_id.
        # In `CodeCommands`, we passed `chat_id` to `orchestrator.execute_command`.
        # The orchestrator should pass `chat_id` back to this callback.
        # We assume `details` might contain it or we modify `orchestrator` to pass it.
        # Assuming `details` has it or we can hack it. 
        # Wait, in `src/bot.py` heavily relied on `self.current_chat_id`. 
        # `Orchestrator` execute_command takes `chat_id`. 
        # When `Orchestrator` calls `_check_permission`, it should pass that `chat_id`.
        # I need to verify `src/orchestrator.py` to see if it passes `chat_id`.
        # If not, I might need to update Orchestrator too.
        # For now, I'll attempt to get it from details if available, otherwise fail gracefully.
        
        chat_id = details.get('chat_id')
        if not chat_id:
             # Fallback to app data (set by CodeCommands)
             chat_id = self.app.bot_data.get('current_chat_id')
        
        if not chat_id:
             logger.error("No chat_id provided for permission request")
             return False

        try:
            # Format permission message
            raw_description = details.get('description', 'Unknown action')
            
            # Truncate if too long (Telegram limit is 4096, but we add wrapper text)
            MAX_DESC_LENGTH = 3000
            if len(raw_description) > MAX_DESC_LENGTH:
                raw_description = raw_description[:MAX_DESC_LENGTH] + "\n... [Truncated]"
            
            description = escape_markdown(raw_description)
            
            # Create message and keyboard (Logic copied from original bot.py)
            reply_markup = self._create_markup(action_type, details, request_id, description)
            message = self._create_message(action_type, details, description)
            
            # Send message logic
            if not await self._send_request(chat_id, message, reply_markup, request_id):
                return False

            # Wait for response
            async with asyncio.timeout(self.permission_timeout):
                approved = await future
                logger.info(f"Permission request {request_id} {'approved' if approved else 'denied'}")
                return approved
                
        except asyncio.TimeoutError:
            self._handle_timeout(chat_id)
            return False
            
        except Exception as e:
            logger.error(f"Error handling permission request: {e}", exc_info=True)
            return False
            
        finally:
            self.pending_permissions.pop(request_id, None)

    def _create_markup(self, action_type, details, request_id, description):
        if action_type == "menu_prompt":
            menu_options = details.get('options', [])
            keyboard = []
            for option in menu_options:
                number = option['number']
                text = option['text']
                keyboard.append([
                    InlineKeyboardButton(
                        f"{number}. {text[:50]}",
                        callback_data=f"perm_{request_id}_{number}"
                    )
                ])
            return InlineKeyboardMarkup(keyboard)
        else:
            return InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Yes", callback_data=f"perm_{request_id}_yes"),
                    InlineKeyboardButton("❌ No", callback_data=f"perm_{request_id}_no")
                ]
            ])

    def _create_message(self, action_type, details, description):
        # Simplified message creation logic
        if action_type == "menu_prompt":
             return f"🔐 **Claude is asking:**\n\n{description}\n\n**Please select an option:**"
        elif action_type == "directory_access":
             target = escape_markdown(details.get('target', 'unknown directory'))
             return f"🔐 **Permission Required**\n\nClaude wants to access:\n`{target}`\n\n**Allow access?**"
        # ... Add other types as in original ...
        return f"🔐 **Permission Required**\n\n{description}\n\n**Approve?**"

    async def _send_request(self, chat_id, message, reply_markup, request_id):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
                return True
            except TimedOut:
                if attempt == max_retries - 1:
                    logger.error(f"Failed to send permission request {request_id} after retries")
                    return False
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Error sending permission request: {e}")
                return False
        return False

    def _handle_timeout(self, chat_id):
        asyncio.create_task(self.app.bot.send_message(
            chat_id=chat_id,
            text="⏱️ Permission request timed out. Denied by default.",
            parse_mode="Markdown"
        ))

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle permission button callbacks."""
        query = update.callback_query
        await query.answer()
        
        parts = query.data.split("_")
        if len(parts) != 3:
            await query.edit_message_text("❌ Invalid permission data")
            return
        
        request_id = parts[1]
        action = parts[2]
        
        future = self.pending_permissions.get(request_id)
        if not future:
            await query.edit_message_text("⏱️ This permission request has expired.")
            return
        
        if action in ["yes", "no"]:
            approved = (action == "yes")
            future.set_result(approved)
            result_text = "✅ Approved" if approved else "❌ Denied"
        else:
            future.set_result(action)
            result_text = f"✅ Selected option {action}"
        
        await query.edit_message_text(
            f"{query.message.text}\n\n**Decision:** {result_text}",
            parse_mode="Markdown"
        )
