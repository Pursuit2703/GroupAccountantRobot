
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN")
FILES_CHANNEL_ID = int(os.environ.get("FILES_CHANNEL_ID", 0))
DB_PATH = os.environ.get("DB_PATH", "debt_manager.db")
ADMIN_USER_IDS = [int(admin_id) for admin_id in os.environ.get("ADMIN_USER_IDS", "").split(",") if admin_id]
LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG")
SCALE = int(os.environ.get("SCALE", 100000))
DRAFT_TTL_SECONDS = int(os.environ.get("DRAFT_TTL_SECONDS", 3600))
REJECTED_TTL_SECONDS = int(os.environ.get('REJECTED_TTL_SECONDS', 86400))
PENDING_TTL_SECONDS = int(os.environ.get('PENDING_TTL_SECONDS', 172800))
CURRENCY = os.environ.get("CURRENCY", "UZS")
DB_TIMEZONE_OFFSET = os.environ.get('DB_TIMEZONE_OFFSET', '+5 hours')
