"""
Telegraph Publisher for AgenticGram.
Publishes long content to telegra.ph and returns the URL.
"""

import logging
import re
from typing import Optional
from telegraph.aio import Telegraph

logger = logging.getLogger(__name__)

# Global Telegraph instance (lazy initialized)
_telegraph: Optional[Telegraph] = None
_account_created = False


async def get_telegraph() -> Telegraph:
    """Get or create Telegraph instance with account."""
    global _telegraph, _account_created

    if _telegraph is None:
        _telegraph = Telegraph()

    if not _account_created:
        try:
            await _telegraph.create_account(
                short_name="AgenticGram",
                author_name="AgenticGram Bot"
            )
            _account_created = True
            logger.info("Telegraph account created")
        except Exception as e:
            logger.error(f"Failed to create Telegraph account: {e}")
            raise

    return _telegraph


def _text_to_telegraph_content(text: str) -> str:
    """
    Convert plain text to Telegraph HTML content.

    Args:
        text: Plain text content

    Returns:
        HTML formatted content for Telegraph
    """
    # Escape HTML special characters
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")

    # Convert code blocks (```...```) to <pre> tags
    text = re.sub(
        r'```(\w*)\n?(.*?)```',
        lambda m: f'<pre>{m.group(2)}</pre>',
        text,
        flags=re.DOTALL
    )

    # Convert inline code (`...`) to <code> tags
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # Convert **bold** to <b> tags
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)

    # Convert *italic* to <i> tags
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)

    # Convert newlines to <br> for non-code sections
    # Split by <pre> tags to preserve code block formatting
    parts = re.split(r'(<pre>.*?</pre>)', text, flags=re.DOTALL)
    result_parts = []

    for part in parts:
        if part.startswith('<pre>'):
            result_parts.append(part)
        else:
            # Convert double newlines to paragraph breaks
            paragraphs = part.split('\n\n')
            formatted = '</p><p>'.join(p.replace('\n', '<br>') for p in paragraphs)
            result_parts.append(f'<p>{formatted}</p>')

    return ''.join(result_parts)


async def publish_to_telegraph(
    title: str,
    content: str,
    author_name: str = "AgenticGram Bot"
) -> Optional[str]:
    """
    Publish content to Telegraph and return the URL.

    Args:
        title: Page title
        content: Content to publish (plain text or markdown-ish)
        author_name: Author name to display

    Returns:
        Telegraph page URL or None if failed
    """
    try:
        telegraph = await get_telegraph()

        # Convert content to Telegraph HTML format
        html_content = _text_to_telegraph_content(content)

        # Create the page
        response = await telegraph.create_page(
            title=title,
            html_content=html_content,
            author_name=author_name
        )

        url = response.get('url')
        if url:
            logger.info(f"Published to Telegraph: {url}")
            return url
        else:
            logger.error("Telegraph response missing URL")
            return None

    except Exception as e:
        logger.error(f"Failed to publish to Telegraph: {e}", exc_info=True)
        return None


async def publish_code_output(
    output: str,
    instruction: str = "Claude Code Output",
    backend: str = "claude_code"
) -> Optional[str]:
    """
    Publish Claude Code output to Telegraph.

    Args:
        output: The output text from Claude
        instruction: The original instruction (used as title)
        backend: Backend used (for subtitle)

    Returns:
        Telegraph page URL or None if failed
    """
    # Create a descriptive title (truncate if too long)
    title = instruction[:100] + "..." if len(instruction) > 100 else instruction

    # Add header to content
    header = f"Backend: {backend}\n\n---\n\n"
    full_content = header + output

    return await publish_to_telegraph(
        title=title,
        content=full_content,
        author_name="AgenticGram Bot"
    )
