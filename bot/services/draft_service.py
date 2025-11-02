
import sqlite3
from datetime import datetime
from bot.logger import get_logger
from bot.config import DRAFT_TTL_SECONDS
from bot.db.connection import get_connection

logger = get_logger(__name__)

def expire_drafts() -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        # Update drafts that have expired and are not locked
        cursor.execute("UPDATE drafts SET locked = 1, updated_at = datetime('now') WHERE expires_at <= datetime('now') AND locked = 0")
        expired_count = cursor.rowcount
        if expired_count > 0:
            logger.info(f"Expired {expired_count} drafts.")
        return expired_count
