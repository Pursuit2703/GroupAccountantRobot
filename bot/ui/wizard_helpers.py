
import telebot
from bot.config import FILES_CHANNEL_ID
from bot.db.repos import get_group_members, get_users_owed_by_user
from bot.utils.currency import format_amount

def generate_expense_step_2_buttons(draft_data):
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
    if 'files' in draft_data and draft_data['files']:
        for i, file_info in enumerate(draft_data['files']):
            file_type = "Image" if file_info['mime'] in ['image/jpeg', 'image/png'] else "File"
            keyboard.add(telebot.types.InlineKeyboardButton(f"🗑️ Delete {file_type} {i+1}", callback_data=f"dm:delete_file:{file_info['file_row_id']}"))
    if not draft_data.get('no_receipt') and not draft_data.get('files'):
         keyboard.row(telebot.types.InlineKeyboardButton("➡️ No Receipt", callback_data="dm:wizard_no_receipt"))
    return keyboard

def generate_expense_step_3_buttons(draft_data):
    categories = {
        "Groceries": "🛒 Groceries",
        "Hygiene": "🧼 Hygiene",
        "Wifi": "🌐 Wifi",
        "Electricity": "💡 Electricity",
        "Gas": "🔥 Gas",
        "Water": "💧 Water",
        "Debt": "💸 Debt",
        "Other": "📦 Other"
    }
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    selected_categories = draft_data.get('categories', [])
    category_buttons = [telebot.types.InlineKeyboardButton(f"{'✅' if key in selected_categories else ''} {value}", callback_data=f"dm:set_category:{key}") for key, value in categories.items()]
    keyboard.add(*category_buttons, row_width=2)
    return keyboard

def generate_expense_step_4_buttons(draft_data, chat_id, user_id):
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    members = get_group_members(chat_id, exclude_user_id=user_id)
    if members:
        selected_debtors = draft_data.get('debtors', [])
        debtor_buttons = [telebot.types.InlineKeyboardButton(f"{'✅' if member['id'] in selected_debtors else ''} {member['display_name']}", callback_data=f"dm:toggle_debtor:{member['id']}") for member in members]
        keyboard.add(*debtor_buttons, row_width=2)
        all_selected = set(m['id'] for m in members) == set(selected_debtors)
        toggle_all_label = "☑️ Deselect All" if all_selected else "✅ Select All"
        keyboard.row(telebot.types.InlineKeyboardButton(toggle_all_label, callback_data="dm:toggle_all_debtors"))
    return keyboard

def generate_expense_step_5_buttons(draft_data):
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    keyboard.row(
        telebot.types.InlineKeyboardButton("✏️ Amount", callback_data="dm:edit_amount"),
        telebot.types.InlineKeyboardButton("✏️ Files", callback_data="dm:edit_files")
    )
    keyboard.row(
        telebot.types.InlineKeyboardButton("✏️ Cat/Desc", callback_data="dm:edit_category_desc"),
        telebot.types.InlineKeyboardButton("✏️ Debtors", callback_data="dm:edit_debtors")
    )
    return keyboard

def generate_settlement_step_1_buttons(draft_data, chat_id, user_id):
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    owed_users = get_users_owed_by_user(user_id, chat_id)
    if owed_users:
        if len(owed_users) == 1 and 'payee' not in draft_data:
            draft_data['payee'] = owed_users[0]['user_id']
        payee_buttons = [telebot.types.InlineKeyboardButton(f"{'✅' if draft_data.get('payee') == user['user_id'] else ''} {user['display_name']}", callback_data=f"dm:toggle_payee:{user['user_id']}") for user in owed_users]
        keyboard.add(*payee_buttons, row_width=2)
    return keyboard

def generate_settlement_step_2_buttons(draft_data):
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(telebot.types.InlineKeyboardButton("💰 Full Amount", callback_data="dm:settle_full_amount"))
    return keyboard

def generate_settlement_step_3_buttons(draft_data):
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
    if 'files' in draft_data and draft_data['files']:
        for i, file_info in enumerate(draft_data['files']):
            file_type = "Image" if file_info['mime'] in ['image/jpeg', 'image/png'] else "File"
            keyboard.add(telebot.types.InlineKeyboardButton(f"🗑️ Delete {file_type} {i+1}", callback_data=f"dm:delete_file:{file_info['file_row_id']}"))
    if not draft_data.get('no_proof') and not draft_data.get('files'):
        keyboard.row(telebot.types.InlineKeyboardButton("➡️ I am paying with cash", callback_data="dm:settle_no_proof"))
    return keyboard

def generate_settlement_step_4_buttons(draft_data, chat_id, user_id):
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=3)
    owed_users = get_users_owed_by_user(user_id, chat_id)
    edit_buttons = []
    if len(owed_users) > 1:
        edit_buttons.append(telebot.types.InlineKeyboardButton("✏️ Payee", callback_data="dm:settle_edit_step:1"))
    
    edit_buttons.append(telebot.types.InlineKeyboardButton("✏️ Amount", callback_data="dm:settle_edit_step:2"))
    edit_buttons.append(telebot.types.InlineKeyboardButton("✏️ Proof", callback_data="dm:settle_edit_step:3"))
    keyboard.row(*edit_buttons)
    return keyboard

def generate_clear_debt_step_1_buttons(draft_data):
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        telebot.types.InlineKeyboardButton("💰 Clear Full Amount", callback_data=f"dm:clear_full_debt"),
        telebot.types.InlineKeyboardButton("❌ Cancel", callback_data=f"dm:clear_debt_cancel")
    )
    return keyboard

def generate_clear_debt_step_2_buttons(draft_data):
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        telebot.types.InlineKeyboardButton("✅ Yes, I'm sure", callback_data=f"dm:confirm_clear_debt:{draft_data['debtor_id']}"),
        telebot.types.InlineKeyboardButton("❌ No, go back", callback_data=f"dm:clear_debt_start:{draft_data['debtor_id']}")
    )
    return keyboard
