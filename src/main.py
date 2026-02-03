
import asyncio
import logging
from src.config import load_config
from src.utils import setup_logging
from src.bot.bot import AgenticGramBot

async def main():
    """Main entry point."""
    # Load configuration
    try:
        config = load_config()
    except ValueError as e:
        print(f"Configuration error: {e}")
        return
    
    # Setup logging
    setup_logging(
        log_level=config["LOG_LEVEL"],
        log_file=config["LOG_FILE"] if config["LOG_FILE"] else None
    )
    
    # Create and run bot
    bot = AgenticGramBot(config)
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
