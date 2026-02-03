
import asyncio
import logging

# Configure logging if run directly
if __name__ == "__main__":
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )

from src.main import main

if __name__ == "__main__":
    asyncio.run(main())
