"""
Markdown utilities for Telegram.
"""

def escape_markdown(text: str) -> str:
    """
    Escape Markdown characters for Telegram messages.
    Escapes characters that are special in Markdown V1/V2.
    
    Args:
        text: Text to escape
        
    Returns:
        Escaped text
    """
    if not text:
        return ""
        
    # Characters that need escaping in Telegram Markdown
    # We escape them with a backslash
    escape_chars = '_*`['
    return ''.join(f'\\{c}' if c in escape_chars else c for c in text)
