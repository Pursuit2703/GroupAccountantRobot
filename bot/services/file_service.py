
import sqlite3
import telebot
from bot.logger import get_logger
from bot.config import FILES_CHANNEL_ID
from bot.db.connection import get_connection

logger = get_logger(__name__)

def forward_to_files_channel(bot: telebot.TeleBot, message: telebot.types.Message) -> telebot.types.Message | None:
    if not FILES_CHANNEL_ID:
        logger.warning("FILES_CHANNEL_ID is not set in config. Skipping file forwarding.")
        return None

    try:
        # Forward the message to the private files channel
        forwarded_message = bot.forward_message(
            chat_id=FILES_CHANNEL_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )
        logger.info(f"File message {message.message_id} from chat {message.chat.id} forwarded to channel {FILES_CHANNEL_ID} as {forwarded_message.message_id}.")
        return forwarded_message
    except telebot.apihelper.ApiTelegramException as e:
        logger.error(f"Failed to forward file message {message.message_id} to channel {FILES_CHANNEL_ID}: {e}")
        return None

def store_file_ref(file_id: str, origin_channel_message_id: int, uploader_user_id: int, related_type: str, related_id: str, mime: str | None, size: int | None) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO files (file_id, origin_channel_message_id, uploader_user_id, related_type, related_id, mime, size) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (file_id, origin_channel_message_id, uploader_user_id, related_type, related_id, mime, size))
        file_row_id = cursor.lastrowid
        logger.info(f"Stored file reference with ID: {file_row_id} for file_id: {file_id}.")
        return file_row_id
