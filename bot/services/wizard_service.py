
from datetime import datetime, timedelta
from bot.utils.time import get_now_in_configured_timezone
import json
from bot.config import DRAFT_TTL_SECONDS, DB_TIMEZONE_OFFSET
from bot.db.repos import update_draft, get_user_display_name
from bot.ui.renderers import render_wizard
import threading
from bot.db.connection import get_connection

def handle_amount_input(bot, message, active_draft):
    try:
        amount = float(message.text)
        if not (0 < amount < 1_000_000_000):
            warning_msg = bot.send_message(message.chat.id, "❗ Amount must be between 0 and 1,000,000,000.")
            threading.Timer(5.0, bot.delete_message, [message.chat.id, warning_msg.message_id]).start()
            return

        draft_id = active_draft['id']
        draft_data = json.loads(active_draft['data_json'])
        current_step = active_draft['step']

        draft_data['amount'] = amount
        current_step += 1
        expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
        update_draft(draft_id, draft_data, current_step, expires_at)
        
        editor_name = get_user_display_name(active_draft['user_id'])
        
        wizard_text, wizard_keyboard = render_wizard(
            wizard_type=active_draft['type'],
            draft_data=draft_data,
            current_step=current_step,
            chat_id=message.chat.id,
            user_id=active_draft['user_id'],
            editor_name=editor_name
        )

        bot.edit_message_text(chat_id=message.chat.id, message_id=draft_data['wizard_message_id'], text=wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')

    except ValueError:
        warning_msg = bot.send_message(message.chat.id, "❗ Invalid amount. Please enter a number.")
        threading.Timer(5.0, bot.delete_message, [message.chat.id, warning_msg.message_id]).start()
    finally:
        bot.delete_message(message.chat.id, message.message_id)

def start_wizard(bot, call, chat_id, user_id, wizard_type):
    from bot.db.repos import get_group, set_active_wizard_user_id, get_active_drafts_by_user, create_draft, update_draft, get_users_owed_by_user, get_user_display_name, delete_file_by_id
    from bot.db.connection import get_connection
    from bot.logger import get_logger
    from bot.config import FILES_CHANNEL_ID
    logger = get_logger(__name__)
    
    try:
        # Clean up any existing wizards for this user in this chat
        existing_drafts = get_active_drafts_by_user(chat_id, user_id, DB_TIMEZONE_OFFSET)
        if existing_drafts:
            logger.info(f"Found {len(existing_drafts)} existing drafts for user {user_id} in chat {chat_id}. Cleaning up.")
            for draft in existing_drafts:
                try:
                    draft_data = json.loads(draft['data_json'])
                    if 'wizard_message_id' in draft_data:
                        bot.delete_message(chat_id, draft_data['wizard_message_id'])
                    
                    # Delete associated files
                    if 'files' in draft_data:
                        for file_info in draft_data['files']:
                            bot.delete_message(FILES_CHANNEL_ID, file_info['origin_channel_message_id'])
                            delete_file_by_id(file_info['file_row_id'])
                    
                    # Delete the draft record
                    with get_connection() as conn:
                        conn.execute("DELETE FROM drafts WHERE id = ?", (draft['id'],))
                except Exception as e:
                    logger.error(f"Error cleaning up old draft {draft['id']}: {e}")

        # Lock the menu for the user
        set_active_wizard_user_id(chat_id, user_id)

        # Create a new draft
        expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
        draft_id = create_draft(chat_id, user_id, wizard_type, expires_at)
        
        draft_data = {'wizard_message_id': call.message.message_id}
        current_step = 1
        
        # Special handling for settlement wizard if user owes only one person
        if wizard_type == 'settlement':
            owed_users = get_users_owed_by_user(user_id, chat_id)
            if len(owed_users) == 1:
                draft_data['payee'] = owed_users[0]['user_id']
                current_step = 2

        update_draft(draft_id, draft_data, current_step, expires_at)
        
        # Render and send the new wizard message
        editor_name = get_user_display_name(user_id)
        wizard_text, wizard_keyboard = render_wizard(
            wizard_type=wizard_type,
            draft_data=draft_data,
            current_step=current_step,
            chat_id=chat_id,
            user_id=user_id,
            editor_name=editor_name
        )

        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=wizard_text,
            reply_markup=wizard_keyboard,
            parse_mode='HTML'
        )
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Error in start_wizard: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "An error occurred while starting the wizard.", show_alert=True)

def update_wizard_after_file_processing(bot, chat_id, user_id, draft_data, current_step, wizard_type):
    editor_name = get_user_display_name(user_id)
    wizard_text, wizard_keyboard = render_wizard(
        wizard_type=wizard_type,
        draft_data=draft_data,
        current_step=current_step,
        chat_id=chat_id,
        user_id=user_id,
        editor_name=editor_name
    )

    try:
        bot.edit_message_text(chat_id=chat_id, message_id=draft_data['wizard_message_id'], text=wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')
        return True
    except Exception as e:
        logger.error(f"Error updating wizard after file processing: {e}")
        return False

def handle_wizard_next(bot, call, chat_id, user_id, wizard_type):
    from bot.db.repos import get_active_draft, update_draft
    
    with get_connection() as conn:
        active_draft = get_active_draft(chat_id, user_id, DB_TIMEZONE_OFFSET)
        if active_draft and active_draft['type'] == wizard_type:
            draft_id, draft_data, current_step = active_draft['id'], json.loads(active_draft['data_json']), active_draft['step']

            if wizard_type == 'expense':
                if current_step == 1 and 'amount' not in draft_data:
                    bot.answer_callback_query(call.id, text="❗ Please enter an amount before proceeding.", show_alert=True)
                    return
                if current_step == 3 and not draft_data.get('description') and not draft_data.get('categories'):
                    bot.answer_callback_query(call.id, text="❗ Please add a description or select a category.", show_alert=True)
                    return
                if current_step == 4 and not draft_data.get('debtors'):
                    bot.answer_callback_query(call.id, text="❗ Please select at least one debtor.", show_alert=True)
                    return
                if current_step < 6:
                    current_step += 1
            elif wizard_type == 'settlement':
                if current_step == 1 and 'payee' not in draft_data:
                    bot.answer_callback_query(call.id, text="❗ Please select a payee before proceeding.", show_alert=True)
                    return
                if current_step == 2 and 'amount' not in draft_data:
                    bot.answer_callback_query(call.id, text="❗ Please enter an amount before proceeding.", show_alert=True)
                    return
                if current_step == 3 and not draft_data.get('files') and not draft_data.get('no_proof'):
                    bot.answer_callback_query(call.id, text="❗ Please upload proof of payment or select 'I am paying with cash'.", show_alert=True)
                    return
                if current_step < 4:
                    current_step += 1
            
            expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
            update_draft(draft_id, draft_data, current_step, expires_at)
            update_wizard_after_file_processing(bot, chat_id, user_id, draft_data, current_step, wizard_type)
            bot.answer_callback_query(call.id)

def handle_wizard_back(bot, call, chat_id, user_id, wizard_type):
    from bot.db.repos import get_active_draft, update_draft

    with get_connection() as conn:
        active_draft = get_active_draft(chat_id, user_id, DB_TIMEZONE_OFFSET)
        if active_draft and active_draft['type'] == wizard_type:
            draft_id, draft_data, current_step = active_draft['id'], json.loads(active_draft['data_json']), active_draft['step']
            if current_step > 1:
                current_step -= 1
            expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
            update_draft(draft_id, draft_data, current_step, expires_at)
            update_wizard_after_file_processing(bot, chat_id, user_id, draft_data, current_step, wizard_type)
            bot.answer_callback_query(call.id)

