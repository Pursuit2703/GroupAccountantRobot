
from datetime import datetime, timedelta
import json
from bot.config import DRAFT_TTL_SECONDS
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
        expires_at = (datetime.now() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat()
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
    from bot.db.repos import get_group, set_active_wizard_user_id, get_active_draft, create_draft, update_draft, get_users_owed_by_user, get_user_display_name
    from bot.db.connection import get_connection
    from bot.logger import get_logger
    logger = get_logger(__name__)
    
    with get_connection() as conn:
        group = get_group(chat_id)
        if group and group['active_wizard_user_id'] and group['active_wizard_user_id'] != user_id:
            lock_time = datetime.fromisoformat(group['active_wizard_locked_at'])
            if datetime.now() - lock_time > timedelta(seconds=DRAFT_TTL_SECONDS):
                logger.info(f"Overriding stale lock for user {group['active_wizard_user_id']} in chat {chat_id}")
                set_active_wizard_user_id(chat_id, None)
            else:
                other_user = get_user_display_name(group['active_wizard_user_id'])
                bot.answer_callback_query(call.id, f"❗ The menu is currently in use by {other_user}. Please wait.", show_alert=True)
                return

        set_active_wizard_user_id(chat_id, user_id)
        active_draft = get_active_draft(chat_id, user_id)
        draft_id, draft_data, current_step = None, {}, 1
        expires_at = (datetime.now() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat()

        if active_draft and active_draft['type'] == wizard_type:
            draft_id, draft_data, current_step = active_draft['id'], json.loads(active_draft['data_json']), active_draft['step']
        else:
            if active_draft:
                with get_connection() as conn:
                    conn.execute("DELETE FROM drafts WHERE id = ?", (active_draft['id'],))
            draft_id = create_draft(chat_id, user_id, wizard_type, expires_at)

        draft_data['wizard_message_id'] = call.message.message_id
        
        if wizard_type == 'settlement' and current_step == 1 and 'payee' not in draft_data:
            owed_users = get_users_owed_by_user(user_id, chat_id)
            if len(owed_users) == 1:
                draft_data['payee'] = owed_users[0]['user_id']
                current_step = 2

        update_draft(draft_id, draft_data, current_step, expires_at)
        editor_name = get_user_display_name(user_id)

        wizard_text, wizard_keyboard = render_wizard(
            wizard_type=wizard_type,
            draft_data=draft_data,
            current_step=current_step,
            chat_id=chat_id,
            user_id=user_id,
            editor_name=editor_name
        )

        bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')
        bot.answer_callback_query(call.id)

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
        active_draft = get_active_draft(chat_id, user_id)
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
            
            expires_at = (datetime.now() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat()
            update_draft(draft_id, draft_data, current_step, expires_at)
            update_wizard_after_file_processing(bot, chat_id, user_id, draft_data, current_step, wizard_type)
            bot.answer_callback_query(call.id)

def handle_wizard_back(bot, call, chat_id, user_id, wizard_type):
    from bot.db.repos import get_active_draft, update_draft

    with get_connection() as conn:
        active_draft = get_active_draft(chat_id, user_id)
        if active_draft and active_draft['type'] == wizard_type:
            draft_id, draft_data, current_step = active_draft['id'], json.loads(active_draft['data_json']), active_draft['step']
            if current_step > 1:
                current_step -= 1
            expires_at = (datetime.now() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat()
            update_draft(draft_id, draft_data, current_step, expires_at)
            update_wizard_after_file_processing(bot, chat_id, user_id, draft_data, current_step, wizard_type)
            bot.answer_callback_query(call.id)

