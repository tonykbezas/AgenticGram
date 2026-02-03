"""
Message splitting utilities for Telegram.
Respects code blocks and Markdown formatting.
"""

import re
from typing import List

MAX_MESSAGE_LENGTH = 4096

def split_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> List[str]:
    """
    Smart message splitter that respects code blocks and markdown formatting.
    
    Args:
        text: The text to split
        max_length: Maximum length of each chunk
        
    Returns:
        List of message chunks
    """
    if len(text) <= max_length:
        return [text]

    parts = []
    remaining = text
    in_code_block = False
    code_block_lang = ''

    while len(remaining) > 0:
        if len(remaining) <= max_length:
            # If we're in a code block, close it properly
            if in_code_block:
                remaining += '\n```'
            parts.append(remaining)
            break

        # Find the chunk to split
        chunk = remaining[:max_length]
        split_index = max_length

        # Track code block state in this chunk
        # Find all code block markers
        code_block_matches = list(re.finditer(r'```(\w*)?', chunk))
        
        # Calculate state at end of chunk
        temp_in_code_block = in_code_block
        temp_lang = code_block_lang
        
        for match in code_block_matches:
            if temp_in_code_block:
                # Closing a code block
                temp_in_code_block = False
                temp_lang = ''
            else:
                # Opening a code block
                temp_in_code_block = True
                temp_lang = match.group(1) or ''

        # If we're ending mid-code-block, we need to handle it carefully
        if temp_in_code_block:
            # Try to find a good split point before the last code block start
            # or at a newline within the code block

            # First, try to split at a newline
            newline_split = chunk.rfind('\n')

            # If the newline is too early (less than half), look for the last complete line
            if newline_split > max_length / 2:
                split_index = newline_split + 1
                chunk = remaining[:split_index]

                # Recount code blocks in the adjusted chunk
                # We need to re-evaluate state because we changed the chunk content
                # Reset to initial state for this iteration
                temp_in_code_block = in_code_block
                temp_lang = code_block_lang
                
                adjusted_matches = list(re.finditer(r'```(\w*)?', chunk))
                for match in adjusted_matches:
                    if temp_in_code_block:
                        temp_in_code_block = False
                        temp_lang = ''
                    else:
                        temp_in_code_block = True
                        temp_lang = match.group(1) or ''
        else:
            # Not in a code block - try to split at natural boundaries
            # Priority: paragraph break > newline > space

            paragraph_break = chunk.rfind('\n\n')
            if paragraph_break > max_length / 2:
                split_index = paragraph_break + 2
            else:
                newline_break = chunk.rfind('\n')
                if newline_break > max_length / 2:
                    split_index = newline_break + 1
                else:
                    space_break = chunk.rfind(' ')
                    if space_break > max_length / 2:
                        split_index = space_break + 1
            
            chunk = remaining[:split_index]
            
            # Recount code blocks
            temp_in_code_block = in_code_block
            temp_lang = code_block_lang
            
            adjusted_matches = list(re.finditer(r'```(\w*)?', chunk))
            for match in adjusted_matches:
                if temp_in_code_block:
                    temp_in_code_block = False
                    temp_lang = ''
                else:
                    temp_in_code_block = True
                    temp_lang = match.group(1) or ''

        # If we end in a code block, close it and note to reopen
        if temp_in_code_block:
            chunk = chunk.rstrip() + '\n```'
            # Next chunk starts in code block
            next_in_code_block = True
            next_lang = temp_lang
        else:
            next_in_code_block = temp_in_code_block
            next_lang = temp_lang

        parts.append(chunk)

        # Prepare remaining text
        remaining = remaining[split_index:].lstrip()

        # If we were in a code block, reopen it
        if next_in_code_block and remaining:
            remaining = f'```{next_lang}\n' + remaining
            # Since we manually added the opening tag, the regex in the next iteration
            # will find it and switch the state to True. Therefore, we should start
            # the next iteration with in_code_block=False.
            next_in_code_block = False
            
        # Update state for next iteration
        in_code_block = next_in_code_block
        code_block_lang = next_lang

    # Add part indicators if multiple parts
    if len(parts) > 1:
        final_parts = []
        for index, part in enumerate(parts):
            indicator = f"\n\n_Part {index + 1}/{len(parts)}_"
            # Make sure indicator fits (it should, mostly)
            if len(part) + len(indicator) <= max_length:
                final_parts.append(part + indicator)
            else:
                final_parts.append(part)
        return final_parts

    return parts
