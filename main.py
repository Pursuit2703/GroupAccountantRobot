import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from bot.app import Bot
from bot.config import BOT_TOKEN, FILES_CHANNEL_ID
from bot.logger import get_logger

logger = get_logger(__name__)

def main():
    """
    The main function that creates and runs the bot.
    """
    try:
        bot = Bot()
        bot.run()
    except Exception as e:
        logger.critical(f"An unhandled exception occurred in main: {e}", exc_info=True)

if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN environment variable not set. Exiting.")
    elif not FILES_CHANNEL_ID or FILES_CHANNEL_ID == 0:
        logger.critical("FILES_CHANNEL_ID environment variable not set or is invalid. Exiting.")
    else:
        main()
