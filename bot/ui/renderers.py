
import telebot
from bot.config import CURRENCY, FILES_CHANNEL_ID
from bot.db.repos import get_group_members, get_users_owed_by_user, get_owed_amount, get_user, get_debt_between_users, get_user_display_name, get_owed_amount
from bot.utils.currency import format_amount
from datetime import datetime
from bot.logger import get_logger
from bot.ui.wizard_config import WIZARD_CONFIGS
from bot.ui.wizard_helpers import (
    generate_expense_step_2_buttons,
    generate_expense_step_3_buttons,
    generate_expense_step_4_buttons,
    generate_expense_step_5_buttons,
    generate_settlement_step_1_buttons,
    generate_settlement_step_2_buttons,
    generate_settlement_step_3_buttons,
    generate_settlement_step_4_buttons,
    generate_clear_debt_step_1_buttons,
    generate_clear_debt_step_2_buttons,
)


logger = get_logger(__name__)

def render_main_menu(group_name: str, active_drafts_count: int = 0) -> tuple[str, telebot.types.InlineKeyboardMarkup]:
    text = f"🧾 Debt Manager — Group: {group_name}\n"
    if active_drafts_count > 0:
        text += f"Active drafts: {active_drafts_count}\n"

    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        telebot.types.InlineKeyboardButton("➕ Add Expense", callback_data="dm:add_expense"),
        telebot.types.InlineKeyboardButton("💸 Pay Debt", callback_data="dm:pay_debt")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("📂 Reports", callback_data="dm:reports"),
        telebot.types.InlineKeyboardButton("📊 Balances", callback_data="dm:balances")
    )
    keyboard.add(
        telebot.types.InlineKeyboardButton("❓ Help", callback_data="dm:help"),
        telebot.types.InlineKeyboardButton("⚙️ Settings", callback_data="dm:settings")
    )
    keyboard.add(telebot.types.InlineKeyboardButton("❌ Close", callback_data="dm:close_menu"))
    return text, keyboard

def render_reports_menu(group_name: str) -> tuple[str, telebot.types.InlineKeyboardMarkup]:
    text = f"📈 <b>Reports for {group_name}</b>\n\n"
    text += "Select a report to view:"

    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        telebot.types.InlineKeyboardButton("📜 History", callback_data="dm:history"),
        telebot.types.InlineKeyboardButton("📈 Analytics", callback_data="dm:analytics")
    )
    keyboard.row(
        telebot.types.InlineKeyboardButton("📊 Export Data", callback_data="dm:export_data")
    )
    keyboard.row(
        telebot.types.InlineKeyboardButton("◀ Back", callback_data="dm:main_menu")
    )
    return text, keyboard

def render_balances_page(user_id: int, group_name: str, balance_summary: dict, all_balances: list[dict]) -> tuple[str, telebot.types.InlineKeyboardMarkup]:
    user_name = get_user_display_name(user_id)
    text = f"📊 <b>Balances for {group_name}</b>\n\n"
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
    text += f"👤 <b>Your Balance Summary ({user_name})</b>\n"

    total_owed = balance_summary.get('total_owed', 0) / 100000
    total_owed_to_user = balance_summary.get('total_owed_to_user', 0) / 100000

    if total_owed_to_user > total_owed and total_owed_to_user - total_owed >= 0.01:
        net_balance = total_owed_to_user - total_owed
        text += f"🎉 You are owed a net total of: {format_amount(net_balance)}\n"
    elif total_owed > total_owed_to_user and total_owed - total_owed_to_user >= 0.01:
        net_balance = total_owed - total_owed_to_user
        text += f"💸 You owe a net total of: {format_amount(net_balance)}\n"
    else:
        text += "✅ You are all settled up!\n"

    if balance_summary['detailed_debts']:
        text += "\n<b>Your Debts:</b>\n"
        debts_owed_to_user = []
        for debt in balance_summary['detailed_debts']:
            from_user = debt['from_user_display_name']
            to_user = debt['to_user_display_name']
            amount = format_amount(debt['amount_u5'] / 100000)

            if debt['from_user_id'] == user_id:
                text += f"• You owe {to_user}: {amount}\n"
            else:
                text += f"• {from_user} owes you: {amount}\n"
                debts_owed_to_user.append(debt)
        
        if debts_owed_to_user:
            text += "\n"
            for debt in debts_owed_to_user:
                from_user = debt['from_user_display_name']
                keyboard.add(telebot.types.InlineKeyboardButton(f"🚮 Clear {from_user}'s Debt", callback_data=f"dm:clear_debt_start:{debt['from_user_id']}"))

    other_balances = [
        debt for debt in all_balances 
        if debt['from_user_id'] != user_id and debt['to_user_id'] != user_id
    ]

    if other_balances:
        text += "\n<b>Other Balances:</b>\n"
        for debt in other_balances:
            from_user = debt['from_user_display_name']
            to_user = debt['to_user_display_name']
            amount = format_amount(debt['amount_u5'] / 100000)
            text += f"• {from_user} owes {to_user}: {amount}\n"

    if not balance_summary['detailed_debts'] and not other_balances:
        text += "\nEveryone is settled up! 🎉"

    keyboard.add(telebot.types.InlineKeyboardButton("◀ Back", callback_data="dm:main_menu"))
    return text, keyboard


def render_analytics_page(group_name: str) -> tuple[str, telebot.types.InlineKeyboardMarkup]:
    text = f"📈 <b>Analytics for {group_name}</b>\n\n"
    text += "Select an analytics report to view:"

    keyboard = telebot.types.InlineKeyboardMarkup()
    keyboard.row(
        telebot.types.InlineKeyboardButton("📊 By Category", callback_data="dm:analytics_by_category")
    )
    keyboard.row(
        telebot.types.InlineKeyboardButton("🗓️ Week", callback_data="dm:analytics_paid_week"),
        telebot.types.InlineKeyboardButton("🗓️ Month", callback_data="dm:analytics_paid_month")
    )
    keyboard.row(
        telebot.types.InlineKeyboardButton("◀ Back", callback_data="dm:reports")
    )
    return text, keyboard

def render_spending_by_category(group_name: str, spending_data: list[dict]) -> tuple[str, telebot.types.InlineKeyboardMarkup]:
    text = f"📊 <b>Spending by Category for {group_name}</b>\n\n"

    categories_emojis = {
        "Groceries": "🛒",
        "Hygiene": "🧼",
        "Wifi": "🌐",
        "Electricity": "💡",
        "Gas": "🔥",
        "Water": "💧",
        "Debt": "💸",
        "Other": "📦"
    }

    if not spending_data:
        text += "No spending data available."
    else:
        for item in spending_data:
            category = item['category'] if item['category'] else "Uncategorized"
            emoji = categories_emojis.get(category, "-")
            amount = format_amount(item['total_amount'] / 100000)
            text += f"{emoji} {category}: {amount}\n"

    keyboard = telebot.types.InlineKeyboardMarkup()
    keyboard.add(telebot.types.InlineKeyboardButton("◀ Back", callback_data="dm:analytics"))
    return text, keyboard

def render_who_paid_how_much(group_name: str, payment_data: list[dict], period: str) -> tuple[str, telebot.types.InlineKeyboardMarkup]:
    text = f"🗓️ <b>Who Paid How Much ({period}) for {group_name}</b>\n\n"

    if not payment_data:
        text += "No payment data available for this period."
    else:
        for item in payment_data:
            display_name = item['display_name']
            amount = format_amount(item['total_amount'] / 100000)
            text += f"👤 {display_name}: {amount}\n"

    keyboard = telebot.types.InlineKeyboardMarkup()
    keyboard.add(telebot.types.InlineKeyboardButton("◀ Back", callback_data="dm:analytics"))
    return text, keyboard

def render_settings_page(group_name: str, settings: dict, editor_name: str | None, internal_user_id: int, telegram_user_id: int, admin_ids: list[int]) -> tuple[str, telebot.types.InlineKeyboardMarkup]:
    text = f"⚙️ <b>Settings for {group_name}</b>\n\n"

    if editor_name:
        text += f"<i>Currently being edited by {editor_name}.</i>\n\n"

    keyboard = telebot.types.InlineKeyboardMarkup()

    auto_confirm_expense_enabled = internal_user_id in settings.get('auto_confirm_expense_users', [])
    auto_confirm_expense_text = f"{'✅' if auto_confirm_expense_enabled else '❌'} Auto-Confirm Expenses: {'Enabled' if auto_confirm_expense_enabled else 'Disabled'}"
    keyboard.add(telebot.types.InlineKeyboardButton(auto_confirm_expense_text, callback_data="dm:toggle_auto_confirm_expense"))

    auto_confirm_settlement_enabled = internal_user_id in settings.get('auto_confirm_settlement_users', [])
    auto_confirm_settlement_text = f"{'✅' if auto_confirm_settlement_enabled else '❌'} Auto-Confirm Settlements: {'Enabled' if auto_confirm_settlement_enabled else 'Disabled'}"
    keyboard.add(telebot.types.InlineKeyboardButton(auto_confirm_settlement_text, callback_data="dm:toggle_auto_confirm_settlement"))

    if telegram_user_id in admin_ids:
        keyboard.add(telebot.types.InlineKeyboardButton("🚫 Manage Excluded Members", callback_data="dm:manage_excluded_members"))

    keyboard.add(telebot.types.InlineKeyboardButton("◀ Back", callback_data="dm:main_menu"))
    return text, keyboard

def render_excluded_members_page(group_name: str, members: list[dict], excluded_members: list[int]) -> tuple[str, telebot.types.InlineKeyboardMarkup]:
    text = f"🚫 <b>Manage Excluded Members for {group_name}</b>\n\n"
    text += "Select members to exclude from expense splits."

    keyboard = telebot.types.InlineKeyboardMarkup()
    
    buttons = []
    for member in members:
        is_excluded = member['id'] in excluded_members
        button_text = f"{'❌' if is_excluded else '✅'} {member['display_name']}"
        buttons.append(telebot.types.InlineKeyboardButton(button_text, callback_data=f"dm:toggle_excluded_member:{member['id']}"))

    # Add buttons in rows of 2
    for i in range(0, len(buttons), 2):
        keyboard.row(*buttons[i:i+2])

    keyboard.add(telebot.types.InlineKeyboardButton("◀ Back", callback_data="dm:settings"))
    return text, keyboard




def render_clear_debt_confirmation(debtor_name: str, amount_str: str, debtor_id: int) -> tuple[str, telebot.types.InlineKeyboardMarkup]:
    text = f"Are you sure you want to clear the debt of {amount_str} from {debtor_name}?"
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        telebot.types.InlineKeyboardButton("✅ Yes, Clear Debt", callback_data=f"dm:confirm_clear_debt:{debtor_id}"),
        telebot.types.InlineKeyboardButton("❌ No, Cancel", callback_data="dm:balances")
    )
    return text, keyboard


def render_wizard(wizard_type: str, draft_data: dict, current_step: int, chat_id: int = None, user_id: int = None, editor_name: str = None) -> tuple[str, telebot.types.InlineKeyboardMarkup]:
    config = WIZARD_CONFIGS[wizard_type]
    title = config['title']
    if editor_name and wizard_type != 'clear_debt':
        title += f" by {editor_name}"
    if current_step == config.get('review_step'):
        title += " (Review)"
    
    text = f"{title}\n\n"

    # Display summary for all steps except the first
    if current_step > 1:
        summary_items = []
        if 'amount' in draft_data:
            summary_items.append(f"<b>Amount:</b> {format_amount(draft_data['amount'])}")
        if draft_data.get('description'):
            summary_items.append(f"<b>Description:</b> {draft_data['description']}")
        if draft_data.get('categories'):
            summary_items.append(f"<b>Category:</b> {', '.join(draft_data['categories'])}")
        if 'debtors' in draft_data and draft_data['debtors']:
            debtor_names = [get_user_display_name(debtor_id) for debtor_id in draft_data['debtors']]
            summary_items.append(f"<b>Debtors:</b> {', '.join(debtor_names)}")
        if 'payee' in draft_data:
            payee_name = get_user_display_name(draft_data['payee'])
            summary_items.append(f"<b>To:</b> {payee_name}")
        
        if summary_items:
            text += "\n".join(summary_items) + "\n"

        if 'files' in draft_data and draft_data['files']:
            file_links = []
            for i, file_info in enumerate(draft_data['files']):
                file_link = f"https://t.me/c/{str(FILES_CHANNEL_ID)[4:]}/{file_info['origin_channel_message_id']}"
                file_type = "Image" if file_info['mime'] in ['image/jpeg', 'image/png'] else "File"
                file_links.append(f'  - <a href="{file_link}">{file_type} {i+1}</a>')
            text += f"\n📎 <b>Files:</b>\n" + "\n".join(file_links)
        elif draft_data.get('no_proof'):
            text += "\n📎 <b>Proof:</b> Paying with cash\n"
        
        text += "\n\n"

    # Dynamic text based on step
    step_config = config['steps'][current_step]
    instruction = step_config['instruction']
    if wizard_type == 'settlement' and current_step == 2:
        payee_name = get_user_display_name(draft_data['payee'])
        total_debt = get_owed_amount(user_id, draft_data['payee']) / 100000
        total_debt_str = format_amount(total_debt)
        instruction = instruction.format(payee_name=payee_name, total_debt_str=total_debt_str)
    elif wizard_type == 'expense' and current_step == 1 and 'amount' in draft_data:
        instruction += f"\n\nCurrent amount: {format_amount(draft_data['amount'])}"
    elif wizard_type == 'clear_debt':
        if current_step == 1:
            total_debt_str = format_amount(draft_data['total_debt_u5'] / 100000)
            instruction = instruction.format(total_debt_str=total_debt_str)
        elif current_step == 2:
            debtor_name = get_user_display_name(draft_data['debtor_id'])
            amount_to_clear = draft_data['amount_to_clear']
            total_debt = draft_data['total_debt_u5'] / 100000
            if amount_to_clear == total_debt:
                amount_text = f"the full debt of <b>{format_amount(total_debt)}</b>"
            else:
                amount_text = f"<b>{format_amount(amount_to_clear)}</b> of <b>{format_amount(total_debt)}</b> debt"
            instruction = instruction.format(amount_text=amount_text, debtor_name=debtor_name)
    text += instruction

    # Step-specific buttons
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    if step_config['buttons']:
        button_func_name = step_config['buttons']
        button_func = globals()[button_func_name]
        # Pass chat_id and user_id only if the function needs them
        import inspect
        sig = inspect.signature(button_func)
        params = {}
        if 'draft_data' in sig.parameters:
            params['draft_data'] = draft_data
        if 'chat_id' in sig.parameters:
            params['chat_id'] = chat_id
        if 'user_id' in sig.parameters:
            params['user_id'] = user_id
        
        keyboard = button_func(**params)


    # Navigation row
    if wizard_type != 'clear_debt':
        navigation_row = []
        if current_step == 1:
            navigation_row.append(telebot.types.InlineKeyboardButton("◀ Back", callback_data="dm:main_menu"))
        elif current_step > 1:
            navigation_row.append(telebot.types.InlineKeyboardButton("◀ Back", callback_data="dm:wizard_back"))

        navigation_row.append(telebot.types.InlineKeyboardButton("❌ Cancel", callback_data="dm:wizard_cancel"))

        if current_step < config['total_steps']:
             navigation_row.append(telebot.types.InlineKeyboardButton("Next ▶", callback_data="dm:wizard_next"))
        else:
            if wizard_type == 'settlement':
                callback_data = "dm:settle_confirm"
            else:
                callback_data = "dm:wizard_confirm"
            navigation_row.append(telebot.types.InlineKeyboardButton("✅ Request Confirmation", callback_data=callback_data))

        if navigation_row:
            keyboard.row(*navigation_row)

    return text, keyboard





def render_expense_message(expense: dict, payer_name: str, debtors: list[dict], share_u5: int, files: list[dict] = None) -> tuple[str, telebot.types.InlineKeyboardMarkup]:

    logger.debug(f"Rendering expense message with files: {files}")

    amount_str = format_amount(expense['amount_u5'] / 100000)
    share_str = format_amount(share_u5 / 100000)

    description = expense.get('description')
    category = expense.get('category')

    # Determine if the expense is disputed
    is_disputed = any(d['status'] == 'rejected' for d in debtors)
    all_confirmed = all(d['status'] == 'confirmed' for d in debtors)

    title_prefix = "New Expense"
    if all_confirmed:
        title_prefix = "Expense"
    text = f"🧾 <b>{title_prefix}: {amount_str} from {payer_name}</b>\n"
    if is_disputed:
        text += "<b>Disputed 🔴</b>\n\n"
    else:
        text += "\n"

    if description and category:
        text += f'"{description}" (<i>{category}</i>)\n\n'
    elif description:
        text += f'"{description}"\n\n'
    elif category:
        text += f"<i>{category}</i>\n\n"

    debtor_mentions = []
    for debtor in debtors:
        status_emoji = "⚪️"  # Pending
        if debtor['status'] == 'confirmed':
            status_emoji = "✅"
        elif debtor['status'] == 'rejected':
            status_emoji = "❌"
        mention = f'<a href="tg://user?id={debtor["tg_id"]}">{debtor["display_name"]}</a>'
        debtor_mentions.append(f"{status_emoji} {mention}")

    if len(debtors) == 1:
        text += f"👤 {debtor_mentions[0]} owes {share_str}:\n"
    else:
        text += f"👥 Each of the {len(debtors)} debtors owes {share_str}:\n" + "\n".join(debtor_mentions) + "\n"

    if files:
        file_links = []
        for i, file_info in enumerate(files):
            file_link = f"https://t.me/c/{str(FILES_CHANNEL_ID)[4:]}/{file_info['origin_channel_message_id']}"
            file_type = "Image" if file_info['mime'] in ['image/jpeg', 'image/png'] else "File"
            file_links.append(f'<a href="{file_link}">{file_type} {i+1}</a>')
        text += f"\n📎 Files: {', '.join(file_links)}\n"

    # Calculate remainder based on formatted share
    if expense.get('category') == 'Debt':
        participants_count = len(debtors)
    else:
        participants_count = len(debtors) + 1

    total_formatted_share = (share_u5 / 100000) * participants_count
    
    expense_float = expense['amount_u5'] / 100000
    formatted_expense = float(f"{expense_float:.3f}")

    remainder = formatted_expense - total_formatted_share

    if remainder > 0.0001:
        remainder_str = f"{remainder:.3f}".rstrip('0').rstrip('.')
        text += f"\nℹ️ <b>Rounding Adjustment:</b>\nTo ensure a fair split, the remaining <b>{remainder_str} {CURRENCY}</b> of the expense has been assigned to the payer."

    created_at = datetime.fromisoformat(expense['created_at']).strftime('%b %d, %Y, %H:%M')
    text += f"\n🗓️ {created_at}"

    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    has_pending_debtors = any(d['status'] == 'pending' for d in debtors)
    all_confirmed = all(d['status'] == 'confirmed' for d in debtors)

    # Only show Confirm/Reject buttons if there are pending debtors AND the expense is not disputed
    if has_pending_debtors and not is_disputed:
        keyboard.add(
            telebot.types.InlineKeyboardButton("✅ Confirm", callback_data=f"dm:confirm_debt:{expense['id']}"),
            telebot.types.InlineKeyboardButton("❌ Reject", callback_data=f"dm:reject_debt:{expense['id']}")
        )

    # Always show Edit/Delete buttons if not all confirmed (or if disputed, to allow resolution)
    if not all_confirmed or is_disputed:
        keyboard.add(
            telebot.types.InlineKeyboardButton("✏️ Edit & Resubmit", callback_data=f"dm:edit_expense:{expense['id']}"),
            telebot.types.InlineKeyboardButton("🗑️ Delete Expense", callback_data=f"dm:delete_expense:{expense['id']}")
        )

    return text, keyboard


def render_history_message(history_events: list[dict], group_name: str, limit: int, offset: int) -> tuple[str, telebot.types.InlineKeyboardMarkup]:
    text = f"📜 <b>Recent History for {group_name}</b>\n\n"
    last_date = None

    if not history_events:
        text += "No recent activity to display."
    else:
        for event in history_events:
            event_dt = datetime.fromisoformat(event['created_at'])
            event_date = event_dt.strftime('%b %d')
            event_time = event_dt.strftime('%H:%M')
            
            if event_date != last_date:
                text += f"<b>{event_date}</b>\n"
                last_date = event_date

            amount = format_amount(event['amount_u5'] / 100000)
            if event['type'] == 'expense':
                payer_name = event['payer_name']
                description = event.get('description') or event.get('category') or 'expense'
                text += f"  • {event_time}: {payer_name} paid {amount} for \"{description}\"\n"
            elif event['type'] == 'settlement':
                from_user_name = event['from_user_name']
                to_user_name = event['to_user_name']
                text += f"  • {event_time}: {from_user_name} paid {to_user_name} {amount}\n"

    keyboard = telebot.types.InlineKeyboardMarkup()
    pagination_row = []
    if offset > 0:
        pagination_row.append(telebot.types.InlineKeyboardButton("◀ Previous", callback_data=f"dm:history:{offset - limit}"))
    if len(history_events) == limit:
        pagination_row.append(telebot.types.InlineKeyboardButton("Next ▶", callback_data=f"dm:history:{offset + limit}"))
    
    if pagination_row:
        keyboard.row(*pagination_row)
        
    keyboard.add(telebot.types.InlineKeyboardButton("◀ Back", callback_data="dm:reports"))

    return text, keyboard

def render_help_message() -> tuple[str, telebot.types.InlineKeyboardMarkup]:
    text = """<b>❓ Help</b>

    Here are the main features of the bot:

    <b>➕ Add Expense</b>
    Use this to add a new expense to the group. The bot will guide you through the process of entering the amount, description, and selecting who was involved.
    - If you select the 'Debt' category, the payer will automatically be excluded from the split.
    - Expenses require all debtors to confirm. If any debtor rejects, the expense becomes 'Disputed' and is locked for editing by the payer.

    <b>💸 Settle Debt</b>
    Use this to record a payment to another member of the group to settle a debt.
    - If you only owe money to one person, the bot will automatically select them and skip directly to the amount input step.
    - You can choose 'I am paying with cash' if you don't have a digital proof of payment.

    <b>📜 History</b>
    View a list of the most recent transactions in the group.

    <b>📊 Balances</b>
    See a summary of who you owe and who owes you, as well as other outstanding debts in the group.

    <b>⚖️ Fair Splitting & Rounding</b>
    To ensure fairness and Shariah compliance, the bot handles rounding with full transparency.

    When an expense can't be split perfectly, each person's share is truncated (not rounded) to 3 decimal places. This prevents anyone from being overcharged. The tiny leftover amount is then assigned to the payer.

    - <b>Example 1:</b> 10 UZS split among 3 people.
      - Each person's share is truncated to 3.333.
      - Total collected: 3.333 * 3 = 9.999.
      - The 0.001 remainder is applied to the payer's share.

    - <b>Example 2:</b> 250 UZS split among 7 people.
      - Each person's share is truncated to 35.714.
      - Total collected: 35.714 * 7 = 249.998.
      - The 0.002 remainder is applied to the payer's share.
    """

    keyboard = telebot.types.InlineKeyboardMarkup()
    keyboard.add(telebot.types.InlineKeyboardButton("◀ Back to Main Menu", callback_data="dm:main_menu"))

    return text, keyboard

def render_settlement_message(settlement: dict, from_user_name: str, to_user_name: str, files: list[dict] = None, new_balance: int = None, is_overpayment: bool = False) -> tuple[str, telebot.types.InlineKeyboardMarkup]:
    amount_str = format_amount(settlement['amount_u5'] / 100000)
    status = settlement.get('status', 'pending')

    to_user = get_user(settlement['to_user_id'])
    to_user_mention = f'<a href="tg://user?id={to_user["tg_id"]}">{to_user_name}</a>' if to_user else to_user_name

    text = f"💸 <b>Settlement</b>\n\n"
    text += f"{from_user_name} has paid {to_user_mention} {amount_str}.\n\n"

    if is_overpayment:
        text += f"⚠️ <b>Overpayment Warning</b>\n"
        text += f"By confirming this settlement, {to_user_name} will owe {from_user_name} {format_amount(abs(new_balance) / 100000)}.\n\n"
    elif new_balance is not None:
        text += f"💰 <b>Expected Balance</b>\n"
        if new_balance == 0:
            text += f"{from_user_name} and {to_user_name} will be settled up.\n\n"
        else:
            text += f"{from_user_name} will still owe {to_user_name} {format_amount(new_balance / 100000)}.\n\n"

    if status == 'pending':
        text += f"⏳ Waiting for {to_user_mention} to confirm..."
    elif status == 'confirmed':
        text += f"✅ Confirmed by {to_user_mention}."
    elif status == 'rejected':
        text += f"❌ Rejected by {to_user_mention}."

    if files:
        file_links = []
        for i, file_info in enumerate(files):
            file_link = f"https://t.me/c/{str(FILES_CHANNEL_ID)[4:]}/{file_info['origin_channel_message_id']}"
            file_type = "Image" if file_info['mime'] in ['image/jpeg', 'image/png'] else "File"
            file_links.append(f'<a href="{file_link}">{file_type} {i+1}</a>')
        text += f"\n\n📎 <b>Proof:</b>\n" + "\n".join(file_links)

    created_at = datetime.fromisoformat(settlement['created_at']).strftime('%b %d, %Y, %H:%M')
    text += f"\n\n🗓️ {created_at}"

    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    if status == 'pending':
        keyboard.add(
            telebot.types.InlineKeyboardButton("✅ Confirm", callback_data=f"dm:confirm_settlement:{settlement['id']}"),
            telebot.types.InlineKeyboardButton("❌ Reject", callback_data=f"dm:reject_settlement:{settlement['id']}")
        )
    elif status == 'rejected':
        keyboard.add(
            telebot.types.InlineKeyboardButton("✏️ Edit & Resubmit", callback_data=f"dm:edit_settlement:{settlement['id']}"),
            telebot.types.InlineKeyboardButton("🗑️ Delete Settlement", callback_data=f"dm:delete_settlement:{settlement['id']}")
        )

    return text, keyboard
