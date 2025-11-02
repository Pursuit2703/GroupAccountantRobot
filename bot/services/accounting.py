from bot.db.repos import get_debts_for_group, get_user_balance_summary
from bot.logger import get_logger

logger = get_logger(__name__)

def get_all_balances(chat_id: int) -> list[dict]:
    logger.info(f"Fetching all balances for chat_id: {chat_id}")
    return get_debts_for_group(chat_id)

def get_my_balance(user_id: int, chat_id: int) -> dict:
    logger.info(f"Fetching balance summary for user {user_id} in chat {chat_id}")
    return get_user_balance_summary(user_id, chat_id)
