"""
Message Sender for AgenticGram.
Handles streaming updates, message chunking, and output cleanup.
"""

import logging
import re
import time
import asyncio
from typing import Optional
from telegram import Message
from .markdown import escape_markdown

logger = logging.getLogger(__name__)


class MessageSender:
    """Handles streaming message updates with debouncing and formatting."""
    
    def __init__(self, status_message: Message):
        """
        Initialize message sender.
        
        Args:
            status_message: The initial Telegram message to edit
        """
        self.status_message = status_message
        self.last_output = ""
        self.last_edit_time = 0
        self.update_count = 0
        self.EDIT_COOLDOWN = 0.5  # Seconds
        self.Thinking_chars = set("✢*✶✻✽·●")
        
    async def update_stream(self, output: str) -> None:
        """
        Update message with streamed output.
        
        Args:
            output: Current accumulated output
        """
        if not output:
            return

        try:
            # Clean output body
            # Remove lines that look like they are just spinner characters
            clean_body = re.sub(
                r'^\s*[✢*✶✻✽·●]\s*$', 
                '', 
                output, 
                flags=re.MULTILINE
            )
            
            # Check if we are currently in "Thinking" state
            raw_tail = output.strip().split('\n')[-1].strip() if output.strip() else ""
            is_thinking = len(raw_tail) == 1 and raw_tail in self.Thinking_chars
            
            # Rate limiting
            current_time = time.time()
            if current_time - self.last_edit_time < self.EDIT_COOLDOWN:
                 return

            self.update_count += 1
            self.last_edit_time = current_time
            
            # Format the message
            escaped_body = escape_markdown(clean_body.strip())
            
            formatted = ""
            if is_thinking:
                spinner = raw_tail
                if len(escaped_body) < 10:
                    formatted = f"🤖 **Claude is thinking...** {spinner}"
                else:
                    if len(escaped_body) > 3500:
                        escaped_body = "...[truncated]\n\n" + escaped_body[-3500:]
                    formatted = f"🤖 **Claude is working...**\n\n```\n{escaped_body}\n```\n\n_Thinking {spinner}_"
            else:
                if not escaped_body:
                    formatted = "🤖 **Claude is working...**"
                else:
                    if len(escaped_body) > 3500:
                        escaped_body = "...[truncated]\n\n" + escaped_body[-3500:]
                    formatted = f"🤖 **Claude is working...**\n\n```\n{escaped_body}\n```"
            
            try:
                await self.status_message.edit_text(
                    formatted,
                    parse_mode="Markdown"
                )
            except Exception as e:
                # Ignore "Message is not modified" errors
                if "Message is not modified" not in str(e):
                    logger.debug(f"Message edit failed: {e}")
        
        except Exception as e:
            logger.error(f"Error in stream update: {e}")
            
    async def send_final(self, result: dict) -> None:
        """
        Send final completion message.
        
        Args:
            result: Execution result dictionary
        """
        if result["success"]:
            output = result["output"]
            backend = result.get("backend", "unknown")
            
            final_text = f"✅ **Completed** (via {backend})\n\n```\n{output}\n```"
            
            if len(final_text) > 4000:
                # Send as file
                from io import BytesIO
                output_file = BytesIO(output.encode('utf-8'))
                output_file.name = "claude_output.txt"
                
                # Delete status message to avoid confusion? or keep it?
                # Usually we reply with document.
                # Here we can try to reply to the status message or the original.
                # status_message has reply_document capability? Yes if it's a Message object.
                # But reply_document replies TO the message. We want to send it.
                chat = self.status_message.chat
                await chat.send_document(
                    document=output_file,
                    filename="claude_output.txt",
                    caption=f"✅ **Completed** (via {backend})\n\n_Output too long, sent as file_",
                    parse_mode="Markdown"
                )
                await self.status_message.delete()
            else:
                await self.status_message.edit_text(final_text, parse_mode="Markdown")
        else:
            error = result.get("error", "Unknown error")
            await self.status_message.edit_text(
                f"❌ **Error:** {error}",
                parse_mode="Markdown"
            )
