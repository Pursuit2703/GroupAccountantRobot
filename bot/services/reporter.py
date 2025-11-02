import csv
from datetime import datetime
import io
from bot.db.repos import get_full_group_history, get_expense_files, get_settlement_files
from bot.config import FILES_CHANNEL_ID

def generate_csv_report(chat_id: int) -> io.StringIO:
    history = get_full_group_history(chat_id)
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['Date', 'Time', 'Type', 'Payer/From', 'Payee/To', 'Amount', 'Description', 'Category', 'Message Link', 'File Links'])
    
    # Write data
    for event in history:
        event_dt = datetime.fromisoformat(event['created_at'])
        event_date = event_dt.strftime('%Y-%m-%d')
        event_time = event_dt.strftime('%H:%M:%S')
        
        amount = event['amount_u5'] / 100000
        
        message_link = f"https://t.me/c/{str(chat_id)[4:]}/{event['message_id']}" if event['message_id'] else ""
        
        file_links = []
        if event['type'] == 'expense':
            files = get_expense_files(event['id'])
        elif event['type'] == 'settlement':
            files = get_settlement_files(event['id'])
        else:
            files = []
            
        for file_info in files:
            channel_id = str(FILES_CHANNEL_ID)[4:]
            file_links.append(f"https://t.me/c/{channel_id}/{file_info['origin_channel_message_id']}")
            
        writer.writerow([
            event_date,
            event_time,
            event['type'].capitalize(),
            event['payer_name'] if event['type'] == 'expense' else event['from_user_name'],
            "" if event['type'] == 'expense' else event['to_user_name'],
            amount,
            event['description'],
            event['category'],
            message_link,
            ", ".join(file_links)
        ])
        
    output.seek(0)
    return output
