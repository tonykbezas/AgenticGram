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


def load_environment() -> dict:
    """
    Load and validate environment variables.
    
    Returns:
        Dictionary containing validated environment variables
        
    Raises:
        ValueError: If required environment variables are missing
    """
    load_dotenv()
    
    required_vars = ["TELEGRAM_BOT_TOKEN", "ALLOWED_TELEGRAM_IDS"]
    env_vars = {}
    
    for var in required_vars:
        value = os.getenv(var)
        if not value:
            raise ValueError(f"Missing required environment variable: {var}")
        env_vars[var] = value
    
    # Optional variables with defaults
    env_vars["OPENROUTER_API_KEY"] = os.getenv("OPENROUTER_API_KEY", "")
    env_vars["CLAUDE_CODE_PATH"] = os.getenv("CLAUDE_CODE_PATH", "")  # Custom path to Claude CLI
    env_vars["WORK_DIR"] = os.getenv("WORK_DIR", "./workspace")
    env_vars["MAX_SESSION_AGE_HOURS"] = int(os.getenv("MAX_SESSION_AGE_HOURS", "24"))
    env_vars["AUTO_CLEANUP_SESSIONS"] = os.getenv("AUTO_CLEANUP_SESSIONS", "true").lower() == "true"
    env_vars["PERMISSION_TIMEOUT_MINUTES"] = int(os.getenv("PERMISSION_TIMEOUT_MINUTES", "5"))
    env_vars["LOG_LEVEL"] = os.getenv("LOG_LEVEL", "INFO")
    env_vars["LOG_FILE"] = os.getenv("LOG_FILE", "")
    
    # Directory navigation settings
    env_vars["BROWSE_START_DIR"] = os.getenv("BROWSE_START_DIR", str(Path.home()))
    env_vars["ALLOWED_BASE_DIRS"] = os.getenv("ALLOWED_BASE_DIRS", f"{Path.home()},/home,/opt,/srv").split(",")
    env_vars["BLOCKED_DIRS"] = os.getenv("BLOCKED_DIRS", "/etc,/sys,/proc,/root,/boot,/dev,/run,/tmp").split(",")
    env_vars["MAX_DIRS_PER_PAGE"] = int(os.getenv("MAX_DIRS_PER_PAGE", "8"))
    
    # Parse allowed Telegram IDs
    env_vars["ALLOWED_TELEGRAM_IDS"] = [
        int(id.strip()) for id in env_vars["ALLOWED_TELEGRAM_IDS"].split(",")
    ]
    
    return env_vars


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
    dir_path = Path(path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path
