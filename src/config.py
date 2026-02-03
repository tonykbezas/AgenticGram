
import os
from pathlib import Path
from dotenv import load_dotenv

def load_config() -> dict:
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
