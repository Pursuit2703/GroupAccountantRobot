
import sqlite3
import telebot
from datetime import datetime, timedelta
import json
from decimal import Decimal
import threading
import time
from bot.db.connection import get_connection
from bot.logger import get_logger
from bot.config import BOT_TOKEN, DRAFT_TTL_SECONDS, FILES_CHANNEL_ID, DB_PATH, ADMIN_USER_IDS, REJECTED_TTL_SECONDS, PENDING_TTL_SECONDS
from bot.services.menu_service import ensure_menu
from bot.db.repos import (
    create_user_if_not_exists,
    create_draft,
    get_active_draft,
    get_draft_owner_by_message_id,
    update_draft,
    add_user_to_group_if_not_exists,
    delete_file_by_id,
    get_group_members,    
    create_expense,
    create_expense_debtors,
    get_expense,
    get_expense_debtors,
    update_debtor_status,
    reject_expense,
    upsert_debt,
    get_user_display_name,
    get_user,
    create_group_if_not_exists,
    get_group,
    get_expense_files,
    update_file_relation,
    delete_expense,
    update_group_last_activity,
    get_groups_with_old_menus,
    create_settlement,
    get_settlement,
    update_settlement_status,
    get_settlement_files,
    delete_settlement,
    get_users_owed_by_user,
    get_owed_amount,
    get_spending_by_category,
    get_spending_by_user_by_period,
    set_settings_editor_id,
    create_or_update_group_menu,
    get_group_history,
    update_expense_message_id,
    update_settlement_message_id,
    get_debt_between_users,
    get_group_settings,
    update_group_settings,
    get_old_stale_drafts,
    get_old_rejected_expenses,
    get_old_rejected_settlements,
    set_active_wizard_user_id,
    set_menu_message_id,
    get_old_pending_expenses,
    get_old_pending_settlements,
)
from bot.services.draft_service import expire_drafts
from bot.services.file_service import store_file_ref
from bot.utils.currency import format_amount
from bot.utils.time import get_now_in_configured_timezone
from bot.services.reporter import generate_csv_report
from bot.services.accounting import get_all_balances, get_my_balance
from bot.services.wizard_service import handle_amount_input, start_wizard, update_wizard_after_file_processing, handle_wizard_next, handle_wizard_back
from bot.ui.renderers import render_main_menu, render_expense_message, render_history_message, render_settlement_message, render_help_message, render_analytics_page, render_spending_by_category, render_who_paid_how_much, render_settings_page, render_reports_menu, render_balances_page, render_clear_debt_confirmation, render_excluded_members_page, render_wizard

logger = get_logger(__name__)

class Bot:
    def __init__(self):
        self.bot = telebot.TeleBot(BOT_TOKEN)
        self.media_group_cache = {}
        self.media_group_timers = {}
        self.user_locks = set()
        self.clear_debt_timers = {}
        self.file_processing_lock = threading.Lock()
        self.menu_creation_time = {}
        self.setup_handlers()

    def setup_database(self):
        with get_connection() as conn:
            logger.info("Database connection established and migrations run.")

    def setup_handlers(self):
        self.bot.register_message_handler(self.handle_menu_command, commands=['menu'])
        self.bot.register_message_handler(self.handle_start_command, commands=['start'])
        self.bot.register_message_handler(self.handle_file_message, content_types=['photo', 'document'])
        self.bot.register_message_handler(self.handle_text_message, func=lambda message: True, content_types=['text'])
        self.bot.register_callback_query_handler(self.handle_callback_query, func=lambda call: call.data.startswith("dm:"))
        self.bot.register_message_handler(self.handle_new_chat_members, content_types=['new_chat_members'])

        # Set bot commands
        self.bot.set_my_commands(
            [
                telebot.types.BotCommand("menu", "📖 Open bot menu"),
            ]
        )

    def handle_new_chat_members(self, message: telebot.types.Message):
        if message.chat.type == 'private':
            return
        for new_member in message.new_chat_members:
            try:
                logger.info(f"New member {new_member.id} joined chat {message.chat.id}")
                user_id = create_user_if_not_exists(new_member.id, new_member.username, new_member.full_name)
                add_user_to_group_if_not_exists(user_id, message.chat.id)
            except Exception as e:
                logger.error(f"Error adding new member to group: {e}")

    def run(self):
        logger.info("Starting Debt Manager Bot...")
        logger.info(f"REJECTED_TTL_SECONDS: {REJECTED_TTL_SECONDS}")
        if not BOT_TOKEN:
            logger.critical("BOT_TOKEN environment variable not set. Exiting.")
            return

        self.setup_database()

        # cleanup_thread = threading.Thread(target=self.cleanup_old_menus, daemon=True)
        # cleanup_thread.start()

        old_records_cleanup_thread = threading.Thread(target=self.cleanup_old_records, daemon=True)
        old_records_cleanup_thread.start()

        menu_creation_time_cleanup_thread = threading.Thread(target=self.cleanup_menu_creation_time, daemon=True)
        menu_creation_time_cleanup_thread.start()

        logger.info("Starting bot polling...")
        self.bot.polling(none_stop=True)

    def cleanup_old_records(self):
        while True:
            try:
                # logger.debug("Running old records cleanup...")

                # Clean up old stale drafts
                stale_drafts = get_old_stale_drafts()
                for draft in stale_drafts:
                    try:
                        draft_data = json.loads(draft['data_json'])
                        if 'wizard_message_id' in draft_data:
                            try:
                                self.bot.delete_message(draft['chat_id'], draft_data['wizard_message_id'])
                            except Exception as e:
                                if "message to delete not found" in str(e).lower():
                                    logger.warning(f"Wizard message for stale draft {draft['id']} was already deleted.")
                                else:
                                    raise
                        
                        self._delete_draft_and_files(draft['id'], draft_data)
                        logger.info(f"Deleted stale draft {draft['id']} in chat {draft['chat_id']}")
                    except Exception as e:
                        logger.error(f"Error processing stale draft {draft['id']} for deletion: {e}")

                # Clean up old rejected expenses
                rejected_expenses = get_old_rejected_expenses(REJECTED_TTL_SECONDS)
                for expense in rejected_expenses:
                    try:
                        if expense['message_id']:
                            try:
                                self.bot.delete_message(expense['chat_id'], expense['message_id'])
                            except Exception as e:
                                if "message to delete not found" in str(e).lower():
                                    logger.warning(f"Message for rejected expense {expense['id']} was already deleted.")
                                else:
                                    raise
                        delete_expense(expense['id'])
                        logger.info(f"Deleted rejected expense {expense['id']} in chat {expense['chat_id']}")
                    except Exception as e:
                        logger.error(f"Error processing rejected expense {expense['id']} for deletion: {e}")

                # Clean up old rejected settlements
                rejected_settlements = get_old_rejected_settlements(REJECTED_TTL_SECONDS)
                for settlement in rejected_settlements:
                    try:
                        if settlement['message_id']:
                            try:
                                self.bot.delete_message(settlement['chat_id'], settlement['message_id'])
                            except Exception as e:
                                if "message to delete not found" in str(e).lower():
                                    logger.warning(f"Message for rejected settlement {settlement['id']} was already deleted.")
                                else:
                                    raise
                        delete_settlement(settlement['id'])
                        logger.info(f"Deleted rejected settlement {settlement['id']} in chat {settlement['chat_id']}")
                    except Exception as e:
                        logger.error(f"Error processing rejected settlement {settlement['id']} for deletion: {e}")

                # Clean up old pending expenses
                pending_expenses = get_old_pending_expenses(PENDING_TTL_SECONDS)
                for expense in pending_expenses:
                    try:
                        if expense['message_id']:
                            try:
                                self.bot.delete_message(expense['chat_id'], expense['message_id'])
                            except Exception as e:
                                if "message to delete not found" in str(e).lower():
                                    logger.warning(f"Message for pending expense {expense['id']} was already deleted.")
                                else:
                                    raise
                        delete_expense(expense['id'])
                        logger.info(f"Deleted pending expense {expense['id']} in chat {expense['chat_id']}")
                    except Exception as e:
                        logger.error(f"Error processing pending expense {expense['id']} for deletion: {e}")

                # Clean up old pending settlements
                pending_settlements = get_old_pending_settlements(PENDING_TTL_SECONDS)
                for settlement in pending_settlements:
                    try:
                        if settlement['message_id']:
                            try:
                                self.bot.delete_message(settlement['chat_id'], settlement['message_id'])
                            except Exception as e:
                                if "message to delete not found" in str(e).lower():
                                    logger.warning(f"Message for pending settlement {settlement['id']} was already deleted.")
                                else:
                                    raise
                        delete_settlement(settlement['id'])
                        logger.info(f"Deleted pending settlement {settlement['id']} in chat {settlement['chat_id']}")
                    except Exception as e:
                        logger.error(f"Error processing pending settlement {settlement['id']} for deletion: {e}")

            except Exception as e:
                logger.error(f"Error in cleanup_old_records: {e}")
            
            time.sleep(60) # Sleep for 1 minute

    def cleanup_menu_creation_time(self):
        while True:
            try:
                now = datetime.now()
                # Create a copy of the dictionary to avoid issues with modifying it while iterating
                for chat_id, creation_time in list(self.menu_creation_time.items()):
                    if (now - creation_time) > timedelta(hours=1):
                        del self.menu_creation_time[chat_id]
            except Exception as e:
                logger.error(f"Error in cleanup_menu_creation_time: {e}")
            
            time.sleep(3600) # Sleep for 1 hour

    def delete_message(self, chat_id, message_id):
        try:
            self.bot.delete_message(chat_id, message_id)
        except Exception as e:
            logger.error(f"Error deleting message {message_id} in chat {chat_id}: {e}")

    def _delete_draft_and_files(self, draft_id: int, draft_data: dict):
        if 'files' in draft_data:
            for file_info in draft_data['files']:
                try:
                    self.bot.delete_message(FILES_CHANNEL_ID, file_info['origin_channel_message_id'])
                except Exception as e:
                    logger.error(f"Error deleting file from channel: {e}")
                delete_file_by_id(file_info['file_row_id'])
        with get_connection() as conn:
            conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))

    def handle_menu_command(self, message: telebot.types.Message):
        if message.chat.type == 'private':
            return
        
        chat_id = message.chat.id
        now = datetime.now()
        last_creation_time = self.menu_creation_time.get(chat_id)

        if last_creation_time and (now - last_creation_time) < timedelta(seconds=5):
            logger.info(f"Menu command for chat {chat_id} was issued too quickly. Ignoring.")
            self.bot.delete_message(chat_id, message.message_id)
            return
        
        self.menu_creation_time[chat_id] = now

        try:
            create_group_if_not_exists(chat_id)
            user_id = create_user_if_not_exists(message.from_user.id, message.from_user.username, message.from_user.first_name)
            add_user_to_group_if_not_exists(user_id, chat_id)

            # Immediately delete the user's /menu command
            self.bot.delete_message(chat_id, message.message_id)

            settings = get_group_settings(chat_id)
            excluded_members = settings.get('excluded_members', [])
            if user_id in excluded_members:
                return

            group = get_group(chat_id)
            existing_menu_id = group.get('menu_message_id') if group else None

            # If an existing menu message ID is found, delete it.
            if existing_menu_id:
                try:
                    self.bot.delete_message(chat_id, existing_menu_id)
                    logger.info(f"Deleted old menu message {existing_menu_id} in chat {chat_id}.")
                except telebot.apihelper.ApiTelegramException as e:
                    if "message to delete not found" in str(e).lower():
                        logger.info(f"Old menu message {existing_menu_id} not found in chat {chat_id}. It might have been deleted manually.")
                    else:
                        logger.error(f"Error deleting old menu message {existing_menu_id}: {e}")
                # Always clear the stored menu ID after attempting to delete.
                set_menu_message_id(chat_id, None)

            chat_info = self.bot.get_chat(chat_id)
            group_name = chat_info.title if chat_info.title else "Your Group Name"
            menu_text, menu_keyboard = render_main_menu(group_name=group_name)
            
            # Send a new menu message.
            sent_message = self.bot.send_message(
                chat_id=chat_id,
                text=menu_text,
                reply_markup=menu_keyboard,
                parse_mode='HTML'
            )
            # Store the new menu's ID.
            create_or_update_group_menu(chat_id, sent_message.message_id)

        except Exception as e:
            logger.error(f"Error in handle_menu_command: {e}")

    def handle_start_command(self, message: telebot.types.Message):
        if message.chat.type == 'private':
            self.bot.send_message(message.chat.id, "I only work in groups.")
            return
        self.handle_menu_command(message)

    def handle_file_message(self, message: telebot.types.Message):
        if message.chat.type == 'private':
            return
        update_group_last_activity(message.chat.id)
        if message.media_group_id:
            if message.media_group_id not in self.media_group_cache:
                self.media_group_cache[message.media_group_id] = []
            self.media_group_cache[message.media_group_id].append(message)

            if message.media_group_id in self.media_group_timers:
                self.media_group_timers[message.media_group_id].cancel()
            
            timer = threading.Timer(1.0, self.process_media_group, [message.media_group_id])
            self.media_group_timers[message.media_group_id] = timer
            timer.start()
        else:
            self.process_single_file(message)

    def process_media_group(self, media_group_id):
        with self.file_processing_lock:
            messages = self.media_group_cache.pop(media_group_id, [])
            if not messages:
                return
            
            first_message = messages[0]
            chat_id = first_message.chat.id
            user_id = create_user_if_not_exists(first_message.from_user.id, first_message.from_user.username, first_message.from_user.full_name)
            add_user_to_group_if_not_exists(user_id, chat_id)

            active_draft = get_active_draft(chat_id, user_id)

            if not active_draft or active_draft['type'] not in ['expense', 'settlement']:
                return

            draft_data = json.loads(active_draft['data_json'])
            draft_id = active_draft['id']
            current_step = active_draft['step']

            if 'files' not in draft_data:
                draft_data['files'] = []

            processed_files_info = []
            for message in messages:
                # Process each file but don't delete the source messages yet.
                file_info = self.process_file(message, user_id, draft_id, draft_data, delete_source_message=False)
                if file_info:
                    processed_files_info.append(file_info)

            if not processed_files_info:
                # No files were successfully processed
                return

            expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
            update_draft(draft_id, draft_data, current_step, expires_at)
            
            if update_wizard_after_file_processing(self.bot, chat_id, user_id, draft_data, current_step, active_draft['type']):
                # Success! Now delete all source messages from the media group.
                for msg in messages:
                    self.bot.delete_message(chat_id, msg.message_id)

    def process_single_file(self, message: telebot.types.Message):
        with self.file_processing_lock:
            chat_id = message.chat.id
            user_id = create_user_if_not_exists(message.from_user.id, message.from_user.username, message.from_user.full_name)
            add_user_to_group_if_not_exists(user_id, chat_id)

            active_draft = get_active_draft(chat_id, user_id)

            if not active_draft or active_draft['type'] not in ['expense', 'settlement']:
                return

            draft_data = json.loads(active_draft['data_json'])
            draft_id = active_draft['id']
            current_step = active_draft['step']

            if 'files' not in draft_data:
                draft_data['files'] = []

            # Process the file but don't delete the source message yet.
            processed_file_info = self.process_file(message, user_id, draft_id, draft_data, delete_source_message=False)
            if not processed_file_info:
                # process_file failed (e.g. wrong mime type) and handled its own messaging/deletion.
                return

            expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
            update_draft(draft_id, draft_data, current_step, expires_at)

            if update_wizard_after_file_processing(self.bot, chat_id, user_id, draft_data, current_step, active_draft['type']):
                # Success! Now delete the source message.
                self.bot.delete_message(message.chat.id, message.message_id)

    def process_file(self, message: telebot.types.Message, user_id: int, draft_id: int, draft_data: dict, delete_source_message: bool = True):
        if message.caption:
            draft_data['description'] = message.caption

        mime_type = "image/jpeg" if message.photo else message.document.mime_type
        if mime_type not in ["image/jpeg", "image/png", "application/pdf"]:
            warning_msg = self.bot.send_message(message.chat.id, "❗ Invalid file type. Only photos, PNGs, and PDFs are accepted.")
            # Always delete the source message for an invalid file type, as it can't be processed.
            self.bot.delete_message(message.chat.id, message.message_id)
            threading.Timer(5.0, self.delete_message, [message.chat.id, warning_msg.message_id]).start()
            return None # Indicate failure

        forwarded_message = self.bot.forward_message(FILES_CHANNEL_ID, message.chat.id, message.message_id)
        if forwarded_message:
            file_id, file_size = (message.photo[-1].file_id, message.photo[-1].file_size) if message.photo else (message.document.file_id, message.document.file_size)
            if file_id:
                file_row_id = store_file_ref(file_id, forwarded_message.message_id, user_id, "draft", str(draft_id), mime_type, file_size)
                if delete_source_message:
                    self.bot.delete_message(message.chat.id, message.message_id)
                
                file_info = {
                    'file_id': file_id,
                    'mime': mime_type,
                    'file_size': file_size,
                    'origin_channel_message_id': forwarded_message.message_id,
                    'file_row_id': file_row_id
                }
                draft_data['files'].append(file_info)
                return file_info # Return the processed file info for potential rollback
        return None # Indicate failure

    def handle_text_message(self, message: telebot.types.Message):
        if message.chat.type == 'private':
            return
        try:
            chat_id = message.chat.id
            create_group_if_not_exists(chat_id)
            with get_connection() as conn:
                logger.info(f"Received text message from user {message.from_user.id} in chat {chat_id}: {message.text}")
                update_group_last_activity(chat_id)
                user_id = create_user_if_not_exists(message.from_user.id, message.from_user.username, message.from_user.full_name)
                add_user_to_group_if_not_exists(user_id, chat_id)
                
                settings = get_group_settings(chat_id)
                excluded_members = settings.get('excluded_members', [])
                if user_id in excluded_members:
                    if message.text == '/menu':
                        self.bot.delete_message(chat_id, message.message_id)
                    return

                active_draft = get_active_draft(chat_id, user_id)

                if not active_draft:
                    return

                draft_data = json.loads(active_draft['data_json'])
                wizard_message_id = draft_data.get('wizard_message_id')

                if not wizard_message_id:
                    return

                # Check if the wizard message is still alive
                try:
                    # We need the keyboard to check if the message is alive without changing it
                    editor_name = get_user_display_name(user_id)
                    if active_draft['type'] in ['expense', 'settlement', 'clear_debt']:
                        _, keyboard = render_wizard(
                            wizard_type=active_draft['type'],
                            draft_data=draft_data,
                            current_step=active_draft['step'],
                            chat_id=chat_id,
                            user_id=user_id,
                            editor_name=editor_name
                        )
                    else:
                        keyboard = None

                    if keyboard:
                        self.bot.edit_message_reply_markup(chat_id=chat_id, message_id=wizard_message_id, reply_markup=keyboard)
                except telebot.apihelper.ApiTelegramException as e:
                    if hasattr(e, 'error_code') and e.error_code == 400:
                        if "message to edit not found" in e.description:
                            logger.debug(f"Wizard message {wizard_message_id} not found. Ignoring text message.")
                            self._delete_draft_and_files(active_draft['id'], draft_data)
                            return
                        elif "message is not modified" in e.description:
                            # This is okay, it means the message is alive.
                            pass
                        else:
                            raise
                    else:
                        raise

                if active_draft['type'] == 'expense':
                    current_step = active_draft['step']
                    draft_id = active_draft['id']

                    if current_step == 1:
                        handle_amount_input(self.bot, message, active_draft)
                    elif current_step == 3:
                        description_text = message.text
                        if len(description_text) > 255:
                            self.bot.delete_message(message.chat.id, message.message_id)
                            warning_msg = self.bot.send_message(message.chat.id, "❗ Description is too long. Please keep it under 255 characters.")
                            threading.Timer(5.0, self.delete_message, [message.chat.id, warning_msg.message_id]).start()
                            return
                        draft_data['description'] = description_text
                        expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
                        update_draft(draft_id, draft_data, current_step, expires_at)
                        self.bot.delete_message(message.chat.id, message.message_id)
                        editor_name = get_user_display_name(user_id)
                        wizard_text, wizard_keyboard = render_wizard(
                            wizard_type='expense',
                            draft_data=draft_data,
                            current_step=current_step,
                            chat_id=message.chat.id,
                            user_id=user_id,
                            editor_name=editor_name
                        )
                        self.bot.edit_message_text(chat_id=message.chat.id, message_id=draft_data['wizard_message_id'], text=wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')
                elif active_draft['type'] == 'settlement':
                    current_step = active_draft['step']
                    draft_id = active_draft['id']

                    if current_step == 2:
                        handle_amount_input(self.bot, message, active_draft)
                elif active_draft['type'] == 'clear_debt':
                    try:
                        amount = Decimal(message.text)
                        if amount >= 1_000_000_000:
                            self.bot.delete_message(message.chat.id, message.message_id)
                            warning_msg = self.bot.send_message(message.chat.id, "❗ Amount must be less than 1,000,000,000.")
                            threading.Timer(5.0, self.delete_message, [message.chat.id, warning_msg.message_id]).start()
                            return
                        total_debt = draft_data['total_debt_u5'] / 100000
                        if not (0.00001 <= amount <= total_debt):
                            self.bot.delete_message(message.chat.id, message.message_id)
                            warning_msg = self.bot.send_message(message.chat.id, f"❗ Amount must be between 0.00001 and {total_debt}.")
                            threading.Timer(5.0, self.delete_message, [message.chat.id, warning_msg.message_id]).start()
                            return
                        
                        draft_data['amount_to_clear'] = float(amount)
                        draft_data['amount_to_clear_u5'] = int(amount * 100000)
                        expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
                        update_draft(active_draft['id'], draft_data, 2, expires_at)
                        self.bot.delete_message(message.chat.id, message.message_id)
                        
                        text, keyboard = render_wizard(
                            wizard_type='clear_debt',
                            draft_data=draft_data,
                            current_step=2,
                            chat_id=message.chat.id,
                            user_id=user_id
                        )
                        try:
                            self.bot.edit_message_text(chat_id=message.chat.id, message_id=draft_data['wizard_message_id'], text=text, reply_markup=keyboard, parse_mode='HTML')
                        except telebot.apihelper.ApiTelegramException as e:
                            if e.result.status_code == 400 and "message to edit not found" in e.result.text:
                                logger.warning(f"Wizard message {draft_data['wizard_message_id']} not found for clear_debt. Cleaning up draft.")
                                with get_connection() as conn:
                                    conn.execute("DELETE FROM drafts WHERE id = ?", (active_draft['id'],))
                                set_active_wizard_user_id(chat_id, None)
                            else:
                                raise

                    except ValueError:
                        self.bot.delete_message(message.chat.id, message.message_id)
                        warning_msg = self.bot.send_message(message.chat.id, "❗ Invalid amount. Please enter a number.")
                        threading.Timer(5.0, self.delete_message, [message.chat.id, warning_msg.message_id]).start()

        except Exception as e:
            logger.error(f"Error in handle_text_message: {e}")

    def handle_callback_query(self, call: telebot.types.CallbackQuery):
        user_id = call.from_user.id
        update_group_last_activity(call.message.chat.id)
        if user_id in self.user_locks:
            self.bot.answer_callback_query(call.id, text="⏳ Please wait, processing previous request.", show_alert=False)
            return

        try:
            self.user_locks.add(user_id)
            logger.info(f"Received callback query from user {call.from_user.id} in chat {call.message.chat.id}: {call.data}")
            action_payload = call.data[3:]
            parts = action_payload.split(":", 1)
            action = parts[0] if parts else ""
            payload = parts[1] if len(parts) > 1 else ""
            self.callback_router(call, action, payload)
        except Exception as e:
            logger.error(f"Error in handle_callback_query: {e}")
        finally:
            if user_id in self.user_locks:
                self.user_locks.remove(user_id)

    def callback_router(self, call: telebot.types.CallbackQuery, action: str, payload: str):
        if call.message.chat.type == 'private':
            self.bot.answer_callback_query(call.id, text="I only work in group chats.", show_alert=True)
            return
        chat_id = call.message.chat.id
        user_id = create_user_if_not_exists(call.from_user.id, call.from_user.username, call.from_user.full_name)
        add_user_to_group_if_not_exists(user_id, chat_id)

        # Check if the message being interacted with is an active wizard message for someone else.
        wizard_owner_id = get_draft_owner_by_message_id(chat_id, call.message.message_id)
        if wizard_owner_id and wizard_owner_id != user_id:
            owner_name = get_user_display_name(wizard_owner_id)
            self.bot.answer_callback_query(call.id, f"This is an active wizard for {owner_name}.", show_alert=True)
            return

        # Check if the message being interacted with is an active settings message for someone else.
        SETTINGS_ACTIONS = [
            "toggle_auto_confirm_expense", "toggle_auto_confirm_settlement",
            "manage_excluded_members", "toggle_excluded_member"
        ]
        if action in SETTINGS_ACTIONS:
            group = get_group(chat_id)
            if group and group.get('settings_editor_id') and group.get('settings_editor_id') != user_id:
                owner_name = get_user_display_name(group['settings_editor_id'])
                self.bot.answer_callback_query(call.id, f"The settings are currently in use by {owner_name}.", show_alert=True)
                return

        # For wizard-specific actions, ensure the user has an active draft.
        WIZARD_ACTIONS = [
            "wizard_next", "wizard_back", "wizard_cancel", "wizard_confirm", 
            "wizard_no_receipt", "set_category", "toggle_debtor", "toggle_all_debtors",
            "edit_amount", "edit_files", "edit_category_desc", "edit_debtors", "delete_file",
            "settle_wizard_next", "settle_wizard_back", "settle_wizard_cancel", "settle_confirm",
            "toggle_payee", "settle_edit_step", "settle_full_amount", "settle_no_proof",
            "clear_full_debt", "clear_debt_cancel", "confirm_clear_debt"
        ]
        if action in WIZARD_ACTIONS:
            active_draft = get_active_draft(chat_id, user_id)
            if not active_draft:
                self.bot.answer_callback_query(call.id, "❗ This wizard has expired or been cancelled.", show_alert=True)
                try:
                    self.bot.delete_message(chat_id, call.message.message_id)
                except Exception:
                    pass
                return

        settings = get_group_settings(chat_id)
        excluded_members = settings.get('excluded_members', [])
        if user_id in excluded_members:
            self.bot.answer_callback_query(call.id)
            return

        if action == "add_expense":
            self.handle_add_expense_start(call, chat_id, user_id)
        elif action == "pay_debt":
            self.handle_pay_debt_start(call, chat_id, user_id)
        elif action == "wizard_next":
            active_draft = get_active_draft(chat_id, user_id)
            if active_draft:
                handle_wizard_next(self.bot, call, chat_id, user_id, active_draft['type'])
        elif action == "wizard_back":
            active_draft = get_active_draft(chat_id, user_id)
            if active_draft:
                handle_wizard_back(self.bot, call, chat_id, user_id, active_draft['type'])
        elif action in ["wizard_cancel", "delete_expense"]:
            self.handle_delete_expense(call, chat_id, user_id, payload)
        elif action == "wizard_confirm":
            self.handle_wizard_confirm(call, chat_id, user_id)
        elif action == "confirm_debt":
            self.handle_confirm_debt(call, chat_id, user_id, payload)
        elif action == "reject_debt":
            self.handle_reject_debt(call, chat_id, user_id, payload)
        elif action == "wizard_no_receipt":
            self.handle_wizard_no_receipt(call, chat_id, user_id)
        elif action == "set_category":
            self.handle_set_category(call, chat_id, user_id, payload)
        elif action == "toggle_debtor":
            self.handle_toggle_debtor(call, chat_id, user_id, int(payload))
        elif action == "toggle_all_debtors":
            self.handle_toggle_all_debtors(call, chat_id, user_id)
        elif action == "edit_amount":
            self.handle_edit_step(call, chat_id, user_id, 1)
        elif action == "edit_files":
            self.handle_edit_step(call, chat_id, user_id, 2)
        elif action == "edit_category_desc":
            self.handle_edit_step(call, chat_id, user_id, 3)
        elif action == "edit_debtors":
            self.handle_edit_step(call, chat_id, user_id, 4)
        elif action == "delete_file":
            self.handle_delete_file(call, chat_id, user_id, int(payload))
        elif action == "delete_expense":
            self.handle_delete_expense(call, chat_id, user_id, payload)
        elif action == "edit_expense":
            self.handle_edit_expense(call, chat_id, user_id, payload)
        elif action == "balances":
            self.handle_balances(call, chat_id, user_id)
        elif action == "reports":
            self.handle_reports(call, chat_id, user_id)
        elif action == "noop":
            self.bot.answer_callback_query(call.id)
        elif action == "clear_debt_start":
            self.handle_clear_debt_start(call, chat_id, user_id, payload)
        elif action == "clear_full_debt":
            self.handle_clear_full_debt(call, chat_id, user_id)
        elif action == "clear_debt_cancel":
            self.handle_clear_debt_cancel(call, chat_id, user_id)
        elif action == "confirm_clear_debt":
            self.handle_confirm_clear_debt(call, chat_id, user_id, payload)
        elif action == "main_menu":
            self.handle_main_menu(call, chat_id, user_id)
        elif action == "close_menu":
            self.handle_close_menu(call, chat_id, user_id)
        elif action == "history":
            offset = int(payload) if payload else 0
            self.handle_history(call, chat_id, user_id, offset)
        elif action == "settle_wizard_next":
            active_draft = get_active_draft(chat_id, user_id)
            if active_draft:
                handle_wizard_next(self.bot, call, chat_id, user_id, active_draft['type'])
        elif action == "settle_wizard_back":
            active_draft = get_active_draft(chat_id, user_id)
            if active_draft:
                handle_wizard_back(self.bot, call, chat_id, user_id, active_draft['type'])
        elif action == "settle_wizard_cancel":
            self.handle_settle_wizard_cancel(call, chat_id, user_id)
        elif action == "settle_confirm":
            self.handle_settle_confirm(call, chat_id, user_id)
        elif action == "confirm_settlement":
            self.handle_confirm_settlement(call, chat_id, user_id, payload)
        elif action == "reject_settlement":
            self.handle_reject_settlement(call, chat_id, user_id, payload)
        elif action == "toggle_payee":
            self.handle_toggle_payee(call, chat_id, user_id, int(payload))
        elif action == "settle_edit_step":
            step = int(payload)
            self.handle_settle_edit_step(call, chat_id, user_id, step)
        elif action == "settle_full_amount":
            self.handle_settle_full_amount(call, chat_id, user_id)
        elif action == "settle_no_proof":
            self.handle_settle_no_proof(call, chat_id, user_id)
        elif action == "delete_settlement":
            self.handle_delete_settlement(call, chat_id, user_id, payload)
        elif action == "edit_settlement":
            self.handle_edit_settlement(call, chat_id, user_id, payload)
        elif action == "help":
            self.handle_help(call, chat_id, user_id)
        elif action == "analytics":
            self.handle_analytics(call, chat_id, user_id)
        elif action == "analytics_by_category":
            self.handle_analytics_by_category(call, chat_id, user_id)
        elif action == "analytics_paid_week":
            self.handle_analytics_paid_week(call, chat_id, user_id)
        elif action == "analytics_paid_month":
            self.handle_analytics_paid_month(call, chat_id, user_id)
        elif action == "settings":
            self.handle_settings(call, chat_id, user_id)
        elif action == "manage_excluded_members":
            self.handle_manage_excluded_members(call, chat_id, user_id)
        elif action == "toggle_excluded_member":
            self.handle_toggle_excluded_member(call, chat_id, user_id, payload)
        elif action == "export_data":
            self.handle_export_data(call, chat_id, user_id)
        elif action == "toggle_auto_confirm_expense":
            self.handle_toggle_auto_confirm_expense(call, chat_id, user_id)
        elif action == "toggle_auto_confirm_settlement":
            self.handle_toggle_auto_confirm_settlement(call, chat_id, user_id)
        else:
            self.bot.answer_callback_query(call.id, text=f"❗ Unknown or expired action: {action}", show_alert=True)

    def handle_toggle_auto_confirm_settlement(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        try:
            settings = get_group_settings(chat_id)
            auto_confirm_users = settings.get('auto_confirm_settlement_users', [])
            
            if user_id in auto_confirm_users:
                auto_confirm_users.remove(user_id)
            else:
                auto_confirm_users.append(user_id)
                
            settings['auto_confirm_settlement_users'] = auto_confirm_users
            update_group_settings(chat_id, settings)
            
            # Refresh the page
            self.handle_settings(call, chat_id, user_id)
            
        except Exception as e:
            logger.error(f"Error in handle_toggle_auto_confirm_settlement: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while updating your auto-confirm setting.", show_alert=True)

    def handle_toggle_auto_confirm_expense(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        try:
            settings = get_group_settings(chat_id)
            auto_confirm_users = settings.get('auto_confirm_expense_users', [])
            
            if user_id in auto_confirm_users:
                auto_confirm_users.remove(user_id)
            else:
                auto_confirm_users.append(user_id)
                
            settings['auto_confirm_expense_users'] = auto_confirm_users
            update_group_settings(chat_id, settings)
            
            # Refresh the page
            self.handle_settings(call, chat_id, user_id)
            
        except Exception as e:
            logger.error(f"Error in handle_toggle_auto_confirm_expense: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while updating your auto-confirm setting.", show_alert=True)

    def handle_analytics(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        try:
            group_info = self.bot.get_chat(chat_id)
            group_name = group_info.title if group_info.title else "Your Group Name"
            
            text, keyboard = render_analytics_page(group_name)
            
            self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            self.bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"Error in handle_analytics: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while fetching analytics.", show_alert=True)

    def handle_analytics_by_category(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        try:
            group_info = self.bot.get_chat(chat_id)
            group_name = group_info.title if group_info.title else "Your Group Name"
            
            spending_data = get_spending_by_category(chat_id)
            text, keyboard = render_spending_by_category(group_name, spending_data)
            
            self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            self.bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"Error in handle_analytics_by_category: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while fetching analytics.", show_alert=True)

    def handle_analytics_paid_week(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        try:
            group_info = self.bot.get_chat(chat_id)
            group_name = group_info.title if group_info.title else "Your Group Name"
            
            payment_data = get_spending_by_user_by_period(chat_id, 7)
            text, keyboard = render_who_paid_how_much(group_name, payment_data, "Last 7 Days")
            
            self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            self.bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"Error in handle_analytics_paid_week: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while fetching analytics.", show_alert=True)

    def handle_analytics_paid_month(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        try:
            group_info = self.bot.get_chat(chat_id)
            group_name = group_info.title if group_info.title else "Your Group Name"
            
            payment_data = get_spending_by_user_by_period(chat_id, 30)
            text, keyboard = render_who_paid_how_much(group_name, payment_data, "Last 30 Days")
            
            self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            self.bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"Error in handle_analytics_paid_month: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while fetching analytics.", show_alert=True)

    def handle_settings(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        try:
            group = get_group(chat_id)
            if group and group.get('settings_editor_id') and group.get('settings_editor_id') != user_id:
                lock_time = datetime.fromisoformat(group['settings_locked_at'])
                if datetime.now() - lock_time > timedelta(seconds=DRAFT_TTL_SECONDS):
                    logger.info(f"Overriding stale lock for user {group['settings_editor_id']} in chat {chat_id}")
                    set_settings_editor_id(chat_id, None)
                else:
                    other_user = get_user_display_name(group['settings_editor_id'])
                    self.bot.answer_callback_query(call.id, f"❗ The settings are currently in use by {other_user}. Please wait.", show_alert=True)
                    return

            set_settings_editor_id(chat_id, user_id)
            
            group_info = self.bot.get_chat(chat_id)
            group_name = group_info.title if group_info.title else "Your Group Name"
            
            editor_name = get_user_display_name(user_id)
            
            settings = get_group_settings(chat_id)
            
            text, keyboard = render_settings_page(group_name, settings, editor_name, user_id, call.from_user.id, ADMIN_USER_IDS)
            
            self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            self.bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"Error in handle_settings: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while opening settings.", show_alert=True)

    def handle_manage_excluded_members(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        if call.from_user.id not in ADMIN_USER_IDS:
            self.bot.answer_callback_query(call.id, text="❗ You are not authorized to manage excluded members.", show_alert=True)
            return

        try:
            group_info = self.bot.get_chat(chat_id)
            group_name = group_info.title if group_info.title else "Your Group Name"
            
            settings = get_group_settings(chat_id)
            excluded_members = settings.get('excluded_members', [])
            members = get_group_members(chat_id, exclude_user_id=user_id, exclude_from_settings=False)
            
            text, keyboard = render_excluded_members_page(group_name, members, excluded_members)
            
            self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            self.bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"Error in handle_manage_excluded_members: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while opening the excluded members page.", show_alert=True)

    def handle_toggle_excluded_member(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, payload: str):
        if call.from_user.id not in ADMIN_USER_IDS:
            self.bot.answer_callback_query(call.id, text="❗ You are not authorized to manage excluded members.", show_alert=True)
            return

        try:
            member_id = int(payload)
            
            settings = get_group_settings(chat_id)
            excluded_members = settings.get('excluded_members', [])
            
            if member_id in excluded_members:
                excluded_members.remove(member_id)
            else:
                excluded_members.append(member_id)
                
            settings['excluded_members'] = excluded_members
            update_group_settings(chat_id, settings)
            
            # Refresh the page
            self.handle_manage_excluded_members(call, chat_id, user_id)
            
        except Exception as e:
            logger.error(f"Error in handle_toggle_excluded_member: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while updating the excluded members list.", show_alert=True)

    def handle_add_expense_start(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        set_menu_message_id(chat_id, None)
        start_wizard(self.bot, call, chat_id, user_id, 'expense')

    def handle_pay_debt_start(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        set_menu_message_id(chat_id, None)

        owed_users = get_users_owed_by_user(user_id, chat_id)
        if not owed_users:
            self.bot.answer_callback_query(call.id, text="You don't owe anyone in this group.", show_alert=True)
            return

        start_wizard(self.bot, call, chat_id, user_id, 'settlement')

    def handle_delete_expense(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, payload: str):
        if payload:
            try:
                expense_id = int(payload)
            except ValueError:
                self.bot.answer_callback_query(call.id, text="❗ Invalid callback data.", show_alert=True)
                return

            with get_connection() as conn:
                expense = get_expense(expense_id)
                if not expense:
                    self.bot.answer_callback_query(call.id, text="❗ This expense does not exist.", show_alert=True)
                    return

                if expense['payer_id'] != user_id:
                    self.bot.answer_callback_query(call.id, text="❗ You are not authorized to delete this expense.", show_alert=True)
                    return

                files = get_expense_files(expense_id)
                for file_info in files:
                    try:
                        self.bot.delete_message(FILES_CHANNEL_ID, file_info['origin_channel_message_id'])
                    except Exception as e:
                        logger.error(f"Error deleting file from channel: {e}")
                    delete_file_by_id(file_info['file_row_id'])

                delete_expense(expense_id)
                self.bot.delete_message(chat_id, call.message.message_id)
                self.bot.answer_callback_query(call.id, text="✅ Expense deleted!")
        else:
            active_draft = get_active_draft(chat_id, user_id)
            if active_draft:
                draft_data = json.loads(active_draft['data_json'])
                self._delete_draft_and_files(active_draft['id'], draft_data)
                set_active_wizard_user_id(chat_id, None)
                self.bot.delete_message(chat_id, draft_data['wizard_message_id'])
                self.bot.answer_callback_query(call.id, text="Draft cancelled.")

    def handle_wizard_no_receipt(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        with get_connection() as conn:
            active_draft = get_active_draft(chat_id, user_id)
            if active_draft and active_draft['type'] == 'expense' and active_draft['step'] == 2:
                draft_id, draft_data, current_step = active_draft['id'], json.loads(active_draft['data_json']), active_draft['step']
                draft_data['no_receipt'] = True
                current_step += 1
                expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
                update_draft(draft_id, draft_data, current_step, expires_at)
                editor_name = get_user_display_name(user_id)
                wizard_text, wizard_keyboard = render_wizard(
                    wizard_type='expense',
                    draft_data=draft_data,
                    current_step=current_step,
                    chat_id=chat_id,
                    user_id=user_id,
                    editor_name=editor_name
                )
                self.bot.edit_message_text(chat_id=chat_id, message_id=draft_data['wizard_message_id'], text=wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')
                self.bot.answer_callback_query(call.id)

    def handle_set_category(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, category: str):
        with get_connection() as conn:
            active_draft = get_active_draft(chat_id, user_id)
            if active_draft and active_draft['type'] == 'expense' and active_draft['step'] == 3:
                draft_id, draft_data, current_step = active_draft['id'], json.loads(active_draft['data_json']), active_draft['step']
                
                if 'categories' not in draft_data:
                    draft_data['categories'] = []

                # Exclusive "Debt" category logic
                if category == 'Debt':
                    if any(c != 'Debt' for c in draft_data['categories']):
                        self.bot.answer_callback_query(call.id, text="❗ 'Debt' must be selected alone. Please deselect other categories first.", show_alert=True)
                        return
                elif 'Debt' in draft_data['categories']:
                    self.bot.answer_callback_query(call.id, text="❗ Please deselect 'Debt' before choosing other categories.", show_alert=True)
                    return

                if category in draft_data['categories']:
                    draft_data['categories'].remove(category)
                else:
                    draft_data['categories'].append(category)

                expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
                update_draft(draft_id, draft_data, current_step, expires_at)
                editor_name = get_user_display_name(user_id)
                wizard_text, wizard_keyboard = render_wizard(
                    wizard_type='expense',
                    draft_data=draft_data,
                    current_step=current_step,
                    chat_id=chat_id,
                    user_id=user_id,
                    editor_name=editor_name
                )
                self.bot.edit_message_text(chat_id=chat_id, message_id=draft_data['wizard_message_id'], text=wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')
                self.bot.answer_callback_query(call.id)

    def handle_toggle_debtor(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, debtor_id: int):
        with get_connection() as conn:
            active_draft = get_active_draft(chat_id, user_id)
            if active_draft and active_draft['type'] == 'expense' and active_draft['step'] == 4:
                draft_id, draft_data, current_step = active_draft['id'], json.loads(active_draft['data_json']), active_draft['step']
                
                if 'debtors' not in draft_data:
                    draft_data['debtors'] = []

                if debtor_id in draft_data['debtors']:
                    draft_data['debtors'].remove(debtor_id)
                else:
                    draft_data['debtors'].append(debtor_id)

                expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
                update_draft(draft_id, draft_data, current_step, expires_at)
                editor_name = get_user_display_name(user_id)
                wizard_text, wizard_keyboard = render_wizard(
                    wizard_type='expense',
                    draft_data=draft_data,
                    current_step=current_step,
                    chat_id=chat_id,
                    user_id=user_id,
                    editor_name=editor_name
                )
                self.bot.edit_message_text(chat_id=chat_id, message_id=draft_data['wizard_message_id'], text=wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')
                self.bot.answer_callback_query(call.id)

    def handle_toggle_all_debtors(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        with get_connection() as conn:
            active_draft = get_active_draft(chat_id, user_id)
            if active_draft and active_draft['type'] == 'expense' and active_draft['step'] == 4:
                draft_id, draft_data, current_step = active_draft['id'], json.loads(active_draft['data_json']), active_draft['step']
                
                members = get_group_members(chat_id, exclude_user_id=user_id)
                member_ids = [member['id'] for member in members]
                
                if 'debtors' in draft_data and set(member_ids) == set(draft_data['debtors']):
                    draft_data['debtors'] = []
                else:
                    draft_data['debtors'] = member_ids

                expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
                update_draft(draft_id, draft_data, current_step, expires_at)
                editor_name = get_user_display_name(user_id)
                wizard_text, wizard_keyboard = render_wizard(
                    wizard_type='expense',
                    draft_data=draft_data,
                    current_step=current_step,
                    chat_id=chat_id,
                    user_id=user_id,
                    editor_name=editor_name
                )
                self.bot.edit_message_text(chat_id=chat_id, message_id=draft_data['wizard_message_id'], text=wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')
                self.bot.answer_callback_query(call.id)

    def handle_edit_step(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, step: int):
        with get_connection() as conn:
            active_draft = get_active_draft(chat_id, user_id)
            if active_draft and active_draft['type'] == 'expense':
                draft_id, draft_data = active_draft['id'], json.loads(active_draft['data_json'])
                
                expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
                update_draft(draft_id, draft_data, step, expires_at)
                editor_name = get_user_display_name(user_id)
                wizard_text, wizard_keyboard = render_wizard(
                    wizard_type='expense',
                    draft_data=draft_data,
                    current_step=step,
                    chat_id=chat_id,
                    user_id=user_id,
                    editor_name=editor_name
                )
                self.bot.edit_message_text(chat_id=chat_id, message_id=draft_data['wizard_message_id'], text=wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')
                self.bot.answer_callback_query(call.id)

    def handle_delete_file(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, file_row_id: int):
        with get_connection() as conn:
            active_draft = get_active_draft(chat_id, user_id)
            if active_draft and active_draft['type'] in ['expense', 'settlement']:
                draft_id, draft_data, current_step = active_draft['id'], json.loads(active_draft['data_json']), active_draft['step']
                
                file_to_delete = next((f for f in draft_data.get('files', []) if f['file_row_id'] == file_row_id), None)

                if 'files' in draft_data:
                    draft_data['files'] = [f for f in draft_data['files'] if f['file_row_id'] != file_row_id]
                
                delete_file_by_id(file_row_id)

                if file_to_delete:
                    try:
                        self.bot.delete_message(FILES_CHANNEL_ID, file_to_delete['origin_channel_message_id'])
                    except Exception as e:
                        logger.error(f"Error deleting file from channel: {e}")

                expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
                update_draft(draft_id, draft_data, current_step, expires_at)

                editor_name = get_user_display_name(user_id)
                wizard_text, wizard_keyboard = render_wizard(
                    wizard_type=active_draft['type'],
                    draft_data=draft_data,
                    current_step=current_step,
                    chat_id=chat_id,
                    user_id=user_id,
                    editor_name=editor_name
                )
                
                self.bot.edit_message_text(chat_id=chat_id, message_id=draft_data['wizard_message_id'], text=wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')
                self.bot.answer_callback_query(call.id, text=f"File deleted.")

    def handle_wizard_confirm(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        with get_connection() as conn:
            active_draft = get_active_draft(chat_id, user_id)
            if not active_draft:
                self.bot.answer_callback_query(call.id, text="❗ Your draft has expired.", show_alert=True)
                return

            draft_data = json.loads(active_draft['data_json'])
            
            # Validation
            if 'amount' not in draft_data or 'debtors' not in draft_data or not draft_data['debtors']:
                self.bot.answer_callback_query(call.id, text="❗ Please fill in all the required fields.", show_alert=True)
                return
            if not draft_data.get('description') and not draft_data.get('categories'):
                self.bot.answer_callback_query(call.id, text="❗ Please provide a description or select at least one category.", show_alert=True)
                return

            payer_id = active_draft['user_id']
            amount_u5 = draft_data['amount_u5']
            description = draft_data.get('description')
            category = ', '.join(draft_data.get('categories', []))
            debtors = draft_data['debtors']
            files = draft_data.get('files', [])
            
            categories = draft_data.get('categories', [])
            
            # Determine participants based on category
            if categories == ['Debt']:
                # For a debt, only the selected debtors are participants
                participants = debtors
                if not participants:
                    self.bot.answer_callback_query(call.id, text="❗ For a debt, you must select at least one debtor.", show_alert=True)
                    return
            else:
                # For a regular expense, the payer is also a participant
                participants = debtors + [payer_id]

            if not participants:
                self.bot.answer_callback_query(call.id, text="❗ Cannot calculate split with no participants.", show_alert=True)
                return

            if categories == ['Debt'] and len(participants) == 1:
                # This is a direct debt, not a split, so use the full amount.
                share_u5 = amount_u5
            else:
                # For regular splits, use the existing truncation logic for fairness.
                # Use the precise amount_u5 for splitting to avoid float precision issues.
                total_amount_decimal = Decimal(amount_u5) / Decimal(100000)
                share_decimal = total_amount_decimal / len(participants)
                truncated_share_decimal = Decimal(int(share_decimal * 1000)) / 1000
                share_u5 = int(truncated_share_decimal * 100000)

            try:
                expense_id = create_expense(chat_id, payer_id, amount_u5, description, category)
                create_expense_debtors(expense_id, debtors, share_u5)

                settings = get_group_settings(chat_id)
                auto_confirm_users = settings.get('auto_confirm_expense_users', [])

                for debtor_id in debtors:
                    if debtor_id in auto_confirm_users:
                        update_debtor_status(expense_id, debtor_id, 'confirmed')

                # NEW: Check if all debtors were auto-confirmed and create debts if so
                expense_debtors_after_auto_confirm = get_expense_debtors(expense_id)
                all_confirmed = all(d['status'] == 'confirmed' for d in expense_debtors_after_auto_confirm)

                if all_confirmed:
                    for debtor in expense_debtors_after_auto_confirm:
                        upsert_debt(debtor['debtor_id'], payer_id, debtor['share_u5'])

                for file_info in files:
                    update_file_relation(file_info['file_row_id'], "expense", expense_id)
                
                # Clean up draft
                with get_connection() as conn:
                    conn.execute("DELETE FROM drafts WHERE id = ?", (active_draft['id'],))

                
                # Delete the wizard message
                self.bot.delete_message(chat_id, draft_data['wizard_message_id'])
                
                # Send expense message
                expense = get_expense(expense_id)
                expense_debtors = get_expense_debtors(expense_id)
                payer_name = get_user_display_name(payer_id)
                text, keyboard = render_expense_message(expense, payer_name, expense_debtors, share_u5, files)
                
                sent_message = self.bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode='HTML')
                update_expense_message_id(expense_id, sent_message.message_id)
                
                self.bot.answer_callback_query(call.id, text="✅ Expense published!")

            except Exception as e:
                logger.error(f"Error creating expense: {e}")
                self.bot.answer_callback_query(call.id, text="❗ An error occurred while creating the expense.", show_alert=True)

    def handle_confirm_debt(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, payload: str):
        try:
            expense_id = int(payload)
            debtor_id_to_confirm = user_id  # The user clicking is the one confirming
        except ValueError:
            self.bot.answer_callback_query(call.id, text="❗ Invalid callback data.", show_alert=True)
            return

        with get_connection() as conn:
            expense = get_expense(expense_id)
            if not expense:
                self.bot.answer_callback_query(call.id, text="❗ This expense does not exist.", show_alert=True)
                return

            payer_id = expense['payer_id']
            payer_name = get_user_display_name(payer_id)
            
            # Find the specific debtor to update
            expense_debtors = get_expense_debtors(expense_id)
            debtor_to_update = next((d for d in expense_debtors if d['debtor_id'] == debtor_id_to_confirm), None)

            if not debtor_to_update or debtor_to_update['status'] != 'pending':
                self.bot.answer_callback_query(call.id, text="❗ This debt is not pending or does not exist for you.", show_alert=True)
                return

            share_u5 = debtor_to_update['share_u5']

            # Check if expense is already disputed
            is_disputed = any(d['status'] == 'rejected' for d in expense_debtors)
            if is_disputed:
                self.bot.answer_callback_query(call.id, text="❗ This expense has been disputed and cannot be confirmed.", show_alert=True)
                return

            try:
                update_debtor_status(expense_id, debtor_id_to_confirm, 'confirmed')
                
                # Check if all debtors have confirmed
                expense_debtors = get_expense_debtors(expense_id) # refresh
                all_confirmed = all(d['status'] == 'confirmed' for d in expense_debtors)

                if all_confirmed:
                    # Create debts for all debtors
                    for debtor in expense_debtors:
                        upsert_debt(debtor['debtor_id'], payer_id, debtor['share_u5'])
                
                # Update the expense message
                files = get_expense_files(expense_id)
                text, keyboard = render_expense_message(expense, payer_name, expense_debtors, share_u5, files)

                self.bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=text, reply_markup=keyboard, parse_mode='HTML')
                
                self.bot.answer_callback_query(call.id, text="✅ Debt confirmed!")

            except Exception as e:
                logger.error(f"Error confirming debt: {e}")
                self.bot.answer_callback_query(call.id, text="❗ An error occurred while confirming the debt.", show_alert=True)

    def handle_reject_debt(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, payload: str):
        try:
            expense_id = int(payload)
            debtor_id_to_reject = user_id  # The user clicking is the one rejecting
        except ValueError:
            self.bot.answer_callback_query(call.id, text="❗ Invalid callback data.", show_alert=True)
            return

        with get_connection() as conn:
            expense = get_expense(expense_id)
            if not expense:
                self.bot.answer_callback_query(call.id, text="❗ This expense does not exist.", show_alert=True)
                return

            # Find the specific debtor to update
            expense_debtors = get_expense_debtors(expense_id)
            debtor_to_update = next((d for d in expense_debtors if d['debtor_id'] == debtor_id_to_reject), None)

            if not debtor_to_update or debtor_to_update['status'] != 'pending':
                self.bot.answer_callback_query(call.id, text="❗ This debt is not pending or does not exist for you.", show_alert=True)
                return

            # Check if expense is already disputed
            is_disputed = any(d['status'] == 'rejected' for d in expense_debtors)
            if is_disputed:
                self.bot.answer_callback_query(call.id, text="❗ This expense has already been disputed.", show_alert=True)
                return

            try:
                logger.info(f"User {debtor_id_to_reject} is rejecting expense {expense_id}. Updating status to 'rejected'.")
                update_debtor_status(expense_id, debtor_id_to_reject, 'rejected')
                reject_expense(expense_id)
                
                # Notify the payer with an @-mention in the group chat
                payer_id_internal = expense['payer_id']
                payer_user = get_user(payer_id_internal)
                payer_tg_id = payer_user['tg_id']
                payer_name = payer_user['display_name']
                rejector_name = get_user_display_name(debtor_id_to_reject)
                expense_description = expense.get('category') or expense.get('description') or  'the expense'
                
                payer_mention = f'<a href="tg://user?id={payer_tg_id}">{payer_name}</a>'
                mention_message_text = f"{payer_mention}, {rejector_name} has rejected their share of the expense for \"{expense_description}\". Please resolve this and then edit and resubmit the expense."
                sent_mention_message = self.bot.send_message(chat_id, mention_message_text, parse_mode='HTML')
                
                # Delete the mention message after 30 seconds
                threading.Timer(30.0, self.delete_message, [chat_id, sent_mention_message.message_id]).start()

                # Update the expense message
                expense_debtors = get_expense_debtors(expense_id)
                payer_name = get_user_display_name(payer_id_internal)
                share_u5 = debtor_to_update['share_u5']
                files = get_expense_files(expense_id)
                text, keyboard = render_expense_message(expense, payer_name, expense_debtors, share_u5, files)
                
                self.bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=text, reply_markup=keyboard, parse_mode='HTML')
                
                self.bot.answer_callback_query(call.id, text="❌ Debt rejected!")

            except Exception as e:
                logger.error(f"Error rejecting debt: {e}")
                self.bot.answer_callback_query(call.id, text="❗ An error occurred while rejecting the debt.", show_alert=True)



    def handle_edit_expense(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, payload: str):
        try:
            expense_id = int(payload)
        except ValueError:
            self.bot.answer_callback_query(call.id, text="❗ Invalid callback data.", show_alert=True)
            return

        expense = get_expense(expense_id)
        if not expense:
            self.bot.answer_callback_query(call.id, text="❗ This expense does not exist.", show_alert=True)
            return

        if expense['payer_id'] != user_id:
            self.bot.answer_callback_query(call.id, text="❗ You are not authorized to edit this expense.", show_alert=True)
            return

        self.bot.answer_callback_query(call.id)

        # Create a new draft from the expense
        draft_data = {
            'amount': expense['amount_u5'] / 100000,
            'amount_u5': expense['amount_u5'],
            'description': expense['description'],
            'categories': expense['category'].split(', ') if expense['category'] else [],
            'debtors': [d['debtor_id'] for d in get_expense_debtors(expense_id)],
            'files': get_expense_files(expense_id)
        }
        expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
        draft_id = create_draft(chat_id, user_id, "expense", expires_at)
        update_draft(draft_id, draft_data, 5, expires_at) # Go to step 5

        # Delete the old expense
        delete_expense(expense_id)

        # Delete the old expense message
        try:
            self.bot.delete_message(chat_id, call.message.message_id)
        except Exception as e:
            logger.warning(f"Could not delete old expense message {call.message.message_id}: {e}")

        # Start the wizard
        editor_name = get_user_display_name(user_id)
        wizard_text, wizard_keyboard = render_wizard(
            wizard_type='expense',
            draft_data=draft_data,
            current_step=5,
            chat_id=chat_id,
            user_id=user_id,
            editor_name=editor_name
        )
        new_message = self.bot.send_message(chat_id, wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')
        draft_data['wizard_message_id'] = new_message.message_id
        update_draft(draft_id, draft_data, 5, expires_at)

    def handle_balances(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        message_id = call.message.message_id
        if message_id in self.clear_debt_timers:
            self.clear_debt_timers.pop(message_id).cancel()
            
        self.bot.answer_callback_query(call.id)
        try:
            group_info = self.bot.get_chat(chat_id)
            group_name = group_info.title if group_info.title else "Your Group Name"
            
            balance_summary = get_my_balance(user_id, chat_id)
            all_balances = get_all_balances(chat_id)
            
            text, keyboard = render_balances_page(user_id, group_name, balance_summary, all_balances)
            
            self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error in handle_balances: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while opening balances.", show_alert=True)

    def handle_reports(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        try:
            group_info = self.bot.get_chat(chat_id)
            group_name = group_info.title if group_info.title else "Your Group Name"
            
            text, keyboard = render_reports_menu(group_name)
            
            self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            self.bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"Error in handle_reports: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while opening reports.", show_alert=True)

    def handle_clear_full_debt(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        active_draft = get_active_draft(chat_id, user_id)
        if not active_draft or active_draft['type'] != 'clear_debt':
            self.bot.answer_callback_query(call.id, text="❗ This action has expired.", show_alert=True)
            return
        
        draft_data = json.loads(active_draft['data_json'])
        draft_data['amount_to_clear'] = draft_data['total_debt_u5'] / 100000
        draft_data['amount_to_clear_u5'] = draft_data['total_debt_u5']
        
        expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
        update_draft(active_draft['id'], draft_data, 2, expires_at)
        
        text, keyboard = render_wizard(
            wizard_type='clear_debt',
            draft_data=draft_data,
            current_step=2,
            chat_id=chat_id,
            user_id=user_id
        )
        self.bot.edit_message_text(chat_id=chat_id, message_id=draft_data['wizard_message_id'], text=text, reply_markup=keyboard, parse_mode='HTML')
        self.bot.answer_callback_query(call.id)

    def handle_clear_debt_cancel(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        active_draft = get_active_draft(chat_id, user_id)
        if active_draft and active_draft['type'] == 'clear_debt':
            with get_connection() as conn:
                conn.execute("DELETE FROM drafts WHERE id = ?", (active_draft['id'],))
        
        self.handle_balances(call, chat_id, user_id)

    def handle_clear_debt_start(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, payload: str):
        set_menu_message_id(chat_id, None)
        try:
            group = get_group(chat_id)
            if group and group['active_wizard_user_id'] and group['active_wizard_user_id'] != user_id:
                lock_time = datetime.fromisoformat(group['active_wizard_locked_at'])
                if datetime.now() - lock_time > timedelta(seconds=DRAFT_TTL_SECONDS):
                    logger.info(f"Overriding stale lock for user {group['active_wizard_user_id']} in chat {chat_id}")
                    set_active_wizard_user_id(chat_id, None)
                else:
                    other_user = get_user_display_name(group['active_wizard_user_id'])
                    self.bot.answer_callback_query(call.id, f"❗ The menu is currently in use by {other_user}. Please wait.", show_alert=True)
                    return

            set_active_wizard_user_id(chat_id, user_id)
            debtor_id = int(payload)
            
            debt_amount_u5 = get_debt_between_users(debtor_id, user_id)
            if not debt_amount_u5 or debt_amount_u5 <= 0:
                self.bot.answer_callback_query(call.id, text="❗ No debt to clear.", show_alert=True)
                return

            expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
            draft_id = create_draft(chat_id, user_id, "clear_debt", expires_at)
            
            draft_data = {
                'debtor_id': debtor_id,
                'total_debt_u5': debt_amount_u5,
                'wizard_message_id': call.message.message_id
            }
            update_draft(draft_id, draft_data, 1, expires_at)

            text, keyboard = render_wizard(
                wizard_type='clear_debt',
                draft_data=draft_data,
                current_step=1,
                chat_id=chat_id,
                user_id=user_id
            )
            
            self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            self.bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"Error in handle_clear_debt_start: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred.", show_alert=True)

    def handle_confirm_clear_debt(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, payload: str):
        active_draft = get_active_draft(chat_id, user_id)
        if not active_draft or active_draft['type'] != 'clear_debt':
            self.bot.answer_callback_query(call.id, text="❗ This action has expired.", show_alert=True)
            return

        try:
            draft_data = json.loads(active_draft['data_json'])
            debtor_id = draft_data['debtor_id']
            payee_id = user_id
            amount_to_clear = draft_data['amount_to_clear']
            amount_to_clear_u5 = draft_data['amount_to_clear_u5']

            # To clear the debt, we credit the payee from the debtor
            upsert_debt(payee_id, debtor_id, amount_to_clear_u5)

            self.bot.answer_callback_query(call.id, text="✅ Debt cleared!")
            
            debtor_name = get_user_display_name(debtor_id)
            payee_name = get_user_display_name(payee_id)
            amount_str = format_amount(amount_to_clear)
            
            message_text = f"✅ {payee_name} has cleared a debt of {amount_str} from {debtor_name}."
            self.bot.send_message(chat_id, message_text)

            # Clean up
            with get_connection() as conn:
                conn.execute("DELETE FROM drafts WHERE id = ?", (active_draft['id'],))

            # Refresh the balances page
            self.handle_balances(call, chat_id, user_id)

        except Exception as e:
            logger.error(f"Error in handle_confirm_clear_debt: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while clearing the debt.", show_alert=True)

    def handle_main_menu(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        try:
            # If this message was an active wizard, delete the corresponding draft.
            owner_id = get_draft_owner_by_message_id(chat_id, call.message.message_id)
            if owner_id:
                logger.info(f"User {user_id} is resetting a wizard owned by {owner_id} back to the main menu. Deleting draft.")
                active_draft = get_active_draft(chat_id, owner_id)
                if active_draft:
                    draft_data = json.loads(active_draft['data_json'])
                    self._delete_draft_and_files(active_draft['id'], draft_data)

            set_settings_editor_id(chat_id, None)
            group_info = self.bot.get_chat(chat_id)
            group_name = group_info.title if group_info.title else "Your Group Name"
            
            menu_text, menu_keyboard = render_main_menu(group_name=group_name)
            
            self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=menu_text,
                reply_markup=menu_keyboard,
                parse_mode='HTML'
            )
            create_or_update_group_menu(chat_id, call.message.message_id)
            self.bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"Error in handle_main_menu: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while returning to the main menu.", show_alert=True)

    def handle_close_menu(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        try:
            # If this message was an active wizard, delete the corresponding draft.
            owner_id = get_draft_owner_by_message_id(chat_id, call.message.message_id)
            if owner_id:
                logger.info(f"User {user_id} is closing a wizard owned by {owner_id}. Deleting draft.")
                active_draft = get_active_draft(chat_id, owner_id, DB_TIMEZONE_OFFSET)
                if active_draft:
                    draft_data = json.loads(active_draft['data_json'])
                    self._delete_draft_and_files(active_draft['id'], draft_data)

            set_settings_editor_id(chat_id, None)
            self.bot.delete_message(chat_id, call.message.message_id)
            self.bot.answer_callback_query(call.id, text="Menu closed.")
        except Exception as e:
            logger.error(f"Error in handle_close_menu: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while closing the menu.", show_alert=True)
            
    def handle_history(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, offset: int = 0):
        try:
            group_info = self.bot.get_chat(chat_id)
            group_name = group_info.title if group_info.title else "Your Group Name"

            limit = 10
            history_events = get_group_history(chat_id, limit=limit, offset=offset)
            text, keyboard = render_history_message(history_events, group_name, limit, offset)

            self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            self.bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"Error in handle_history: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while fetching the history.", show_alert=True)

    def handle_settle_wizard_cancel(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        active_draft = get_active_draft(chat_id, user_id)
        if active_draft and active_draft['type'] == 'settlement':
            draft_data = json.loads(active_draft['data_json'])
            self._delete_draft_and_files(active_draft['id'], draft_data)
            self.bot.delete_message(chat_id, draft_data['wizard_message_id'])
            self.bot.answer_callback_query(call.id, text="Settlement draft cancelled.")

    def handle_toggle_payee(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, payee_id: int):
        with get_connection() as conn:
            active_draft = get_active_draft(chat_id, user_id)
            logger.debug(f"handle_toggle_payee: active_draft={active_draft}")
            if active_draft and active_draft['type'] == 'settlement' and active_draft['step'] == 1:
                draft_id, draft_data, current_step = active_draft['id'], json.loads(active_draft['data_json']), active_draft['step']
                
                draft_data['payee'] = payee_id
                current_step += 1 # Auto-advance to next step

                expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
                update_draft(draft_id, draft_data, current_step, expires_at)
                editor_name = get_user_display_name(user_id)
                wizard_text, wizard_keyboard = render_wizard(
                    wizard_type='settlement',
                    draft_data=draft_data,
                    current_step=current_step,
                    chat_id=chat_id,
                    user_id=user_id,
                    editor_name=editor_name
                )
                self.bot.edit_message_text(chat_id=chat_id, message_id=draft_data['wizard_message_id'], text=wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')
                self.bot.answer_callback_query(call.id)
            else:
                self.bot.answer_callback_query(call.id)

    def handle_settle_edit_step(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, step: int):
        with get_connection() as conn:
            active_draft = get_active_draft(chat_id, user_id)
            if active_draft and active_draft['type'] == 'settlement':
                draft_id, draft_data = active_draft['id'], json.loads(active_draft['data_json'])
                
                expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
                update_draft(draft_id, draft_data, step, expires_at)
                editor_name = get_user_display_name(user_id)
                wizard_text, wizard_keyboard = render_wizard(
                    wizard_type='settlement',
                    draft_data=draft_data,
                    current_step=step,
                    chat_id=chat_id,
                    user_id=user_id,
                    editor_name=editor_name
                )
                self.bot.edit_message_text(chat_id=chat_id, message_id=draft_data['wizard_message_id'], text=wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')
                self.bot.answer_callback_query(call.id)

    def handle_settle_full_amount(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        with get_connection() as conn:
            active_draft = get_active_draft(chat_id, user_id)
            if active_draft and active_draft['type'] == 'settlement' and active_draft['step'] == 2:
                draft_id, draft_data, current_step = active_draft['id'], json.loads(active_draft['data_json']), active_draft['step']
                
                if 'payee' in draft_data:
                    owed_amount = get_owed_amount(user_id, draft_data['payee'])
                    if owed_amount > 0:
                        owed_amount_decimal = Decimal(owed_amount) / Decimal(100000)
                        draft_data['amount'] = float(owed_amount_decimal)
                        draft_data['amount_u5'] = owed_amount
                        current_step += 1
                        expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
                        update_draft(draft_id, draft_data, current_step, expires_at)
                        editor_name = get_user_display_name(user_id)
                        wizard_text, wizard_keyboard = render_wizard(
                            wizard_type='settlement',
                            draft_data=draft_data,
                            current_step=current_step,
                            chat_id=chat_id,
                            user_id=user_id,
                            editor_name=editor_name
                        )
                        self.bot.edit_message_text(chat_id=chat_id, message_id=draft_data['wizard_message_id'], text=wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')
                        self.bot.answer_callback_query(call.id)
                    else:
                        self.bot.answer_callback_query(call.id, text="❗ You don't owe any money to this person.", show_alert=True)
                else:
                    self.bot.answer_callback_query(call.id, text="❗ Please select a payee first.", show_alert=True)

    def handle_settle_no_proof(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        with get_connection() as conn:
            active_draft = get_active_draft(chat_id, user_id)
            if active_draft and active_draft['type'] == 'settlement' and active_draft['step'] == 3:
                draft_id, draft_data, current_step = active_draft['id'], json.loads(active_draft['data_json']), active_draft['step']
                
                draft_data['no_proof'] = True
                current_step += 1
                expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
                update_draft(draft_id, draft_data, current_step, expires_at)
                editor_name = get_user_display_name(user_id)
                wizard_text, wizard_keyboard = render_wizard(
                    wizard_type='settlement',
                    draft_data=draft_data,
                    current_step=current_step,
                    chat_id=chat_id,
                    user_id=user_id,
                    editor_name=editor_name
                )
                try:
                    self.bot.edit_message_text(chat_id=chat_id, message_id=draft_data['wizard_message_id'], text=wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')
                except telebot.apihelper.ApiTelegramException as e:
                    if "message is not modified" in str(e):
                        logger.warning("Message not modified, trying to send a new one.")
                        self.bot.delete_message(chat_id, draft_data['wizard_message_id'])
                        new_message = self.bot.send_message(chat_id, wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')
                        draft_data['wizard_message_id'] = new_message.message_id
                        update_draft(draft_id, draft_data, current_step, expires_at)
                    else:
                        raise
                self.bot.answer_callback_query(call.id)

    def handle_settle_confirm(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        with get_connection() as conn:
            active_draft = get_active_draft(chat_id, user_id)
            if not active_draft or active_draft['type'] != 'settlement':
                self.bot.answer_callback_query(call.id, text="❗ Your draft has expired or is invalid.", show_alert=True)
                return

            draft_data = json.loads(active_draft['data_json'])
            
            if 'payee' not in draft_data or 'amount' not in draft_data or (not draft_data.get('files') and not draft_data.get('no_proof')):
                self.bot.answer_callback_query(call.id, text="❗ Please fill in all the required fields.", show_alert=True)
                return

            from_user_id = active_draft['user_id']
            to_user_id = draft_data['payee']
            amount_u5 = draft_data['amount_u5']
            files = draft_data.get('files', [])

            try:
                current_debt = get_owed_amount(from_user_id, to_user_id)
                settlement_id = create_settlement(chat_id, from_user_id, to_user_id, amount_u5)

                settings = get_group_settings(chat_id)
                auto_confirm_users = settings.get('auto_confirm_settlement_users', [])

                if to_user_id in auto_confirm_users:
                    update_settlement_status(settlement_id, 'confirmed')
                    upsert_debt(to_user_id, from_user_id, amount_u5)
                    
                    # Show updated balance
                    new_balance = get_debt_between_users(from_user_id, to_user_id)
                    if new_balance == 0:
                        balance_message = f"✅ {get_user_display_name(from_user_id)} and {get_user_display_name(to_user_id)} are now settled up."
                    elif new_balance > 0:
                        balance_message = f"💰 Balance: {get_user_display_name(from_user_id)} owes {get_user_display_name(to_user_id)} {format_amount(new_balance / 100000)}."
                    else: # new_balance < 0
                        balance_message = f"💰 Balance: {get_user_display_name(to_user_id)} owes {get_user_display_name(from_user_id)} {format_amount(abs(new_balance) / 100000)}."
                    
                    threading.Timer(1.0, self.bot.send_message, [chat_id, balance_message]).start()

                for file_info in files:
                    update_file_relation(file_info['file_row_id'], "settlement", settlement_id)
                
                with get_connection() as conn:
                    conn.execute("DELETE FROM drafts WHERE id = ?", (active_draft['id'],))

                
                self.bot.delete_message(chat_id, draft_data['wizard_message_id'])
                
                settlement = get_settlement(settlement_id)
                from_user_name = get_user_display_name(from_user_id)
                to_user_name = get_user_display_name(to_user_id)

                new_balance = current_debt - amount_u5
                is_overpayment = new_balance < 0

                text, keyboard = render_settlement_message(settlement, from_user_name, to_user_name, files, new_balance, is_overpayment)
                
                sent_message = self.bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode='HTML')
                update_settlement_message_id(settlement_id, sent_message.message_id)
                
                self.bot.answer_callback_query(call.id, text="✅ Settlement published!")

            except Exception as e:
                logger.error(f"Error creating settlement: {e}")
                self.bot.answer_callback_query(call.id, text="❗ An error occurred while creating the settlement.", show_alert=True)

    def handle_confirm_settlement(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, payload: str):
        try:
            settlement_id = int(payload)
        except ValueError:
            self.bot.answer_callback_query(call.id, text="❗ Invalid callback data.", show_alert=True)
            return

        with get_connection() as conn:
            settlement = get_settlement(settlement_id)
            if not settlement:
                self.bot.answer_callback_query(call.id, text="❗ This settlement does not exist.", show_alert=True)
                return

            if settlement['to_user_id'] != user_id:
                self.bot.answer_callback_query(call.id, text="❗ You are not authorized to confirm this settlement.", show_alert=True)
                return

            if settlement['status'] != 'pending':
                self.bot.answer_callback_query(call.id, text="❗ This settlement is not pending.", show_alert=True)
                return

            try:
                update_settlement_status(settlement_id, 'confirmed')
                upsert_debt(settlement['to_user_id'], settlement['from_user_id'], settlement['amount_u5'])
                
                settlement = get_settlement(settlement_id)
                from_user_name = get_user_display_name(settlement['from_user_id'])
                to_user_name = get_user_display_name(settlement['to_user_id'])
                files = get_settlement_files(settlement_id)
                text, keyboard = render_settlement_message(settlement, from_user_name, to_user_name, files)

                self.bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=text, reply_markup=keyboard, parse_mode='HTML')
                
                self.bot.answer_callback_query(call.id, text="✅ Settlement confirmed!")

                # Show updated balance
                new_balance = get_debt_between_users(settlement['from_user_id'], settlement['to_user_id'])
                if new_balance == 0:
                    balance_message = f"✅ {from_user_name} and {to_user_name} are now settled up."
                elif new_balance > 0:
                    balance_message = f"💰 Balance: {get_user_display_name(settlement['from_user_id'])} owes {get_user_display_name(settlement['to_user_id'])} {format_amount(new_balance / 100000)}."
                else: # new_balance < 0
                    balance_message = f"💰 Balance: {get_user_display_name(settlement['to_user_id'])} owes {get_user_display_name(settlement['from_user_id'])} {format_amount(abs(new_balance) / 100000)}."
                
                threading.Timer(1.0, self.bot.send_message, [chat_id, balance_message]).start()

            except Exception as e:
                logger.error(f"Error confirming settlement: {e}")
                self.bot.answer_callback_query(call.id, text="❗ An error occurred while confirming the settlement.", show_alert=True)

    def handle_reject_settlement(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, payload: str):
        try:
            settlement_id = int(payload)
        except ValueError:
            self.bot.answer_callback_query(call.id, text="❗ Invalid callback data.", show_alert=True)
            return

        with get_connection() as conn:
            settlement = get_settlement(settlement_id)
            if not settlement:
                self.bot.answer_callback_query(call.id, text="❗ This settlement does not exist.", show_alert=True)
                return

            if settlement['to_user_id'] != user_id:
                self.bot.answer_callback_query(call.id, text="❗ You are not authorized to reject this settlement.", show_alert=True)
                return

            if settlement['status'] != 'pending':
                self.bot.answer_callback_query(call.id, text="❗ This settlement is not pending.", show_alert=True)
                return

            try:
                update_settlement_status(settlement_id, 'rejected')
                
                settlement = get_settlement(settlement_id)
                from_user_name = get_user_display_name(settlement['from_user_id'])
                to_user_name = get_user_display_name(settlement['to_user_id'])
                files = get_settlement_files(settlement_id)
                text, keyboard = render_settlement_message(settlement, from_user_name, to_user_name, files)

                self.bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=text, reply_markup=keyboard, parse_mode='HTML')
                
                self.bot.answer_callback_query(call.id, text="❌ Settlement rejected!")

            except Exception as e:
                logger.error(f"Error rejecting settlement: {e}")
                self.bot.answer_callback_query(call.id, text="❗ An error occurred while rejecting the settlement.", show_alert=True)

    def handle_delete_settlement(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, payload: str):
        try:
            settlement_id = int(payload)
        except ValueError:
            self.bot.answer_callback_query(call.id, text="❗ Invalid callback data.", show_alert=True)
            return

        with get_connection() as conn:
            settlement = get_settlement(settlement_id)
            if not settlement:
                self.bot.answer_callback_query(call.id, text="❗ This settlement does not exist.", show_alert=True)
                return

            if settlement['from_user_id'] != user_id:
                self.bot.answer_callback_query(call.id, text="❗ You are not authorized to delete this settlement.", show_alert=True)
                return

            files = get_settlement_files(settlement_id)
            for file_info in files:
                try:
                    self.bot.delete_message(FILES_CHANNEL_ID, file_info['origin_channel_message_id'])
                except Exception as e:
                    logger.error(f"Error deleting file from channel: {e}")
                delete_file_by_id(file_info['file_row_id'])

            delete_settlement(settlement_id)
            self.bot.delete_message(chat_id, call.message.message_id)
            self.bot.answer_callback_query(call.id, text="✅ Settlement deleted!")

    def handle_edit_settlement(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int, payload: str):
        try:
            settlement_id = int(payload)
        except ValueError:
            self.bot.answer_callback_query(call.id, text="❗ Invalid callback data.", show_alert=True)
            return

        settlement = get_settlement(settlement_id)
        if not settlement:
            self.bot.answer_callback_query(call.id, text="❗ This settlement does not exist.", show_alert=True)
            return

        if settlement['from_user_id'] != user_id:
            self.bot.answer_callback_query(call.id, text="❗ You are not authorized to edit this settlement.", show_alert=True)
            return

        # Create a new draft from the settlement
        draft_data = {
            'payee': settlement['to_user_id'],
            'amount': settlement['amount_u5'] / 100000,
            'amount_u5': settlement['amount_u5'],
            'files': get_settlement_files(settlement_id),
            'no_proof': not get_settlement_files(settlement_id)
        }
        expires_at = (get_now_in_configured_timezone() + timedelta(seconds=DRAFT_TTL_SECONDS)).isoformat(' ')
        draft_id = create_draft(chat_id, user_id, "settlement", expires_at)
        update_draft(draft_id, draft_data, 4, expires_at) # Go to step 4

        # Delete the old settlement
        delete_settlement(settlement_id)

        # Delete the old settlement message
        self.bot.delete_message(chat_id, call.message.message_id)

        # Start the wizard
        wizard_text, wizard_keyboard = render_wizard(
            wizard_type='settlement',
            draft_data=draft_data,
            current_step=4,
            chat_id=chat_id,
            user_id=user_id
        )
        new_message = self.bot.send_message(chat_id, wizard_text, reply_markup=wizard_keyboard, parse_mode='HTML')
        draft_data['wizard_message_id'] = new_message.message_id
        update_draft(draft_id, draft_data, 4, expires_at)

    def handle_help(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        try:
            text, keyboard = render_help_message()
            self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            self.bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"Error in handle_help: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while fetching help.", show_alert=True)

    def handle_export_data(self, call: telebot.types.CallbackQuery, chat_id: int, user_id: int):
        try:
            self.bot.answer_callback_query(call.id, text="Generating your report, please wait...")
            
            csv_file = generate_csv_report(chat_id)
            
            self.bot.send_document(
                chat_id=chat_id,
                document=telebot.types.InputFile(csv_file, "debt_manager_export.csv"),
                caption="Here is your data export."
            )

            # Send the database file
            try:
                with open(DB_PATH, 'rb') as db_file:
                    self.bot.send_document(
                        chat_id=chat_id,
                        document=telebot.types.InputFile(db_file, "debt_manager.db"),
                        caption="Here is your database file."
                    )
            except FileNotFoundError:
                self.bot.send_message(chat_id, "❗ Database file not found. Please ensure the bot is configured correctly.")
        except Exception as e:
            logger.error(f"Error in handle_export_data: {e}")
            self.bot.answer_callback_query(call.id, text="❗ An error occurred while generating the report.", show_alert=True)

def main():
    try:
        bot_instance = Bot()
        bot_instance.run()
    except Exception as e:
        logger.critical(f"An unhandled exception occurred in main: {e}")

if __name__ == "__main__":
    main()
