"""
Utility functions for AgenticGram bot.
Provides helper functions for validation, formatting, and logging.
"""

import os
import logging
from pathlib import Path
from typing import Optional, List
from dotenv import load_dotenv


def setup_logging(log_level: str = "INFO", log_file: Optional[str] = None) -> None:
    """
    Configure logging for the application.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional path to log file
    """
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        handlers=handlers
    )




def validate_file_type(filename: str, allowed_extensions: List[str] = None) -> bool:
    """
    Validate if a file has an allowed extension.
    
    Args:
        filename: Name of the file to validate
        allowed_extensions: List of allowed extensions (default: ['.py', '.sql', '.js'])
        
    Returns:
        True if file type is allowed, False otherwise
    """
    if allowed_extensions is None:
        allowed_extensions = ['.py', '.sql', '.js', '.txt', '.json', '.md']
    
    file_ext = Path(filename).suffix.lower()
    return file_ext in allowed_extensions


def sanitize_message(message: str, max_length: int = 4096) -> List[str]:
    """
    Sanitize and chunk message for Telegram (4096 character limit).
    
    Args:
        message: Message to sanitize
        max_length: Maximum length per chunk (default: 4096 for Telegram)
        
    Returns:
        List of message chunks
    """
    if len(message) <= max_length:
        return [message]
    
    chunks = []
    current_chunk = ""
    
    for line in message.split('\n'):
        if len(current_chunk) + len(line) + 1 <= max_length:
            current_chunk += line + '\n'
        else:
            if current_chunk:
                chunks.append(current_chunk.rstrip())
            current_chunk = line + '\n'
    
    if current_chunk:
        chunks.append(current_chunk.rstrip())
    
    return chunks


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        Formatted string (e.g., "1.5 MB")
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def ensure_directory(path: str) -> Path:
    """
    Ensure a directory exists, create if it doesn't.
    
    Args:
        path: Path to directory
        
    Returns:
        Path object
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


