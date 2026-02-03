import logging
import re
import time
import asyncio
from typing import Optional, List
from telegram import Message
from .markdown import escape_markdown
from .splitter import split_message, MAX_MESSAGE_LENGTH

logger = logging.getLogger(__name__)


class MessageSender:
    """Handles streaming message updates with debouncing, formatting, and splitting."""
    
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
        self.EDIT_COOLDOWN = 1.0  # Increased debounce for multi-message handling
        self.Thinking_chars = set("✢*✶✻✽·●")
        self.message_chain: List[Message] = [status_message]
        
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
            clean_body = re.sub(
                r'^\s*[✢*✶✻✽·●]\s*$', 
                '', 
                output, 
                flags=re.MULTILINE
            )
            
            # Check thinking state
            raw_tail = output.strip().split('\n')[-1].strip() if output.strip() else ""
            is_thinking = len(raw_tail) == 1 and raw_tail in self.Thinking_chars
            
            # Rate limiting
            current_time = time.time()
            if current_time - self.last_edit_time < self.EDIT_COOLDOWN:
                 return

            self.update_count += 1
            self.last_edit_time = current_time
            
            # Prepare formatted body
            formatted_body = self._format_output(clean_body, is_thinking, raw_tail)
            
            # Split into chunks if needed
            chunks = split_message(formatted_body, MAX_MESSAGE_LENGTH)
            
            # Update messages
            await self._update_message_chain(chunks)
        
        except Exception as e:
            logger.error(f"Error in stream update: {e}")
            
    def _format_output(self, body: str, is_thinking: bool, spinner: str) -> str:
        """Format the output string before splitting."""
        escaped_body = escape_markdown(body.strip())
        
        if is_thinking:
            if len(escaped_body) < 10:
                header = escape_markdown("🤖 Claude is thinking... ")
                return f"*{header}*{spinner}"
            else:
                header = escape_markdown("🤖 Claude is working...\n\n")
                footer = escape_markdown("Thinking ")
                return f"*{header}*```\n{escaped_body}\n```\n\n_{footer}{spinner}_"
        else:
            if not escaped_body:
                header = escape_markdown("🤖 Claude is working...")
                return f"*{header}*"
            else:
                header = escape_markdown("🤖 Claude is working...\n\n")
                return f"*{header}*```\n{escaped_body}\n```"

    async def _update_message_chain(self, chunks: List[str]) -> None:
        """Update the chain of messages with new chunks."""
        chat = self.status_message.chat
        
        # Ensure we have enough message objects
        while len(self.message_chain) < len(chunks):
            # Send new placeholder message
            new_msg = await chat.send_message("...")
            self.message_chain.append(new_msg)
            
        # Update each message
        for i, chunk in enumerate(chunks):
            msg = self.message_chain[i]
            if msg.text != chunk and msg.caption != chunk:  # Simple check to avoid redundant API calls
                try:
                    await msg.edit_text(chunk, parse_mode="MarkdownV2")
                except Exception as e:
                    if "Message is not modified" not in str(e):
                        logger.debug(f"Message {i} edit failed: {e}")
    
    async def send_final(self, result: dict) -> None:
        """Send final completion message."""
        logger.info(f"Sending final result: {result}")
        if result["success"]:
            output = result["output"]
            backend = result.get("backend", "unknown")
            
            # Prepare final text
            escaped_output = escape_markdown(output)
            header = escape_markdown(f"✅ Completed (via {backend})\n\n")
            final_text = f"*{header}*```\n{escaped_output}\n```"
            
            # Split
            chunks = split_message(final_text, MAX_MESSAGE_LENGTH)
            
            if len(chunks) > 5: # If gigantic, send as file
                from io import BytesIO
                output_file = BytesIO(output.encode('utf-8'))
                output_file.name = "claude_output.txt"
                
                caption = escape_markdown(f"✅ Completed (via {backend})\n\nOutput too long, sent as file")
                
                await self.status_message.chat.send_document(
                    document=output_file,
                    filename="claude_output.txt",
                    caption=f"*{caption}*",
                    parse_mode="MarkdownV2"
                )
                # Cleanup chain
                for msg in self.message_chain:
                    try:
                        await msg.delete()
                    except:
                        pass
            else:
                # Update chain with final text
                await self._update_message_chain(chunks)
                
                # Delete any extra messages in chain if we shrank
                if len(self.message_chain) > len(chunks):
                    for msg in self.message_chain[len(chunks):]:
                        try:
                            await msg.delete()
                        except:
                            pass
        else:
            error = result.get("error", "Unknown error")
            escaped_error = escape_markdown(f"❌ Error: {error}")
            await self.status_message.edit_text(
                f"*{escaped_error}*",
                parse_mode="MarkdownV2"
            )
