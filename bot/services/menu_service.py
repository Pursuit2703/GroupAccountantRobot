
import sqlite3
import telebot
from bot.db.repos import get_group, create_or_update_group_menu
from bot.logger import get_logger
from bot.ui.renderers import render_main_menu
from bot.db.connection import get_connection # Import get_connection


logger = get_logger(__name__)

def ensure_menu(bot: telebot.TeleBot, chat_id: int) -> int:
    with get_connection() as conn:
        group = get_group(chat_id)
        menu_message_id = None

        # Get the current menu content
        # Fetch chat title dynamically
        chat_info = bot.get_chat(chat_id)
        group_name = chat_info.title if chat_info.title else "Your Group Name"

        menu_text, menu_keyboard = render_main_menu(group_name=group_name) # Use actual group name

        if group and group.get("menu_message_id"):
            menu_message_id = group["menu_message_id"]
            try:
                # Attempt to edit the existing menu message to see if it's still valid
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=menu_message_id,
                    text=menu_text,
                    reply_markup=menu_keyboard
                )
                logger.info(f"Existing menu message {menu_message_id} in chat {chat_id} is valid.")
                return menu_message_id
            except telebot.apihelper.ApiTelegramException as e:
                if "message to edit not found" in str(e).lower() or "message can't be edited" in str(e).lower():
                    logger.warning(f"Menu message {menu_message_id} in chat {chat_id} not found or uneditable. Creating new menu.")
                    menu_message_id = None # Invalidate old message_id
                elif "message is not modified" in str(e).lower():
                    logger.info(f"Menu message {menu_message_id} in chat {chat_id} is already up to date.")
                    return menu_message_id # Treat as success
                else:
                    logger.error(f"Error editing menu message {menu_message_id} in chat {chat_id}: {e}")
                    raise # Re-raise unexpected errors

        if not menu_message_id:
            # Create a new menu message
            sent_message = bot.send_message(
                chat_id=chat_id,
                text=menu_text,
                reply_markup=menu_keyboard
            )
            menu_message_id = sent_message.message_id
            create_or_update_group_menu(chat_id, menu_message_id)
            logger.info(f"New menu message {menu_message_id} created in chat {chat_id}.")

            # TODO: Implement cleanup_old_menus here

        return menu_message_id

def rotate_menu(bot: telebot.TeleBot, chat_id: int) -> int:
    # This function will be called when the menu needs to be refreshed or moved
    # For now, it will just create a new menu and update the DB
    logger.info(f"Rotating menu in chat {chat_id}.")
    new_menu_message_id = ensure_menu(bot, chat_id)
    return new_menu_message_id