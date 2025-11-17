# Group Accountant Robot

A sophisticated Telegram bot for managing shared expenses and debts within a group. It simplifies tracking who paid for what, who owes whom, and settling up, all through an intuitive, wizard-based interface.

## Features

- **Interactive Expense & Settlement Wizards:** A step-by-step guided process for adding expenses and paying off debts, ensuring all necessary information is captured accurately.
- **Receipt & Proof of Payment:** Users can upload photos or PDFs as receipts for expenses or as proof of payment for settlements.
- **Confirmation System:** Expenses and settlements are not finalized until the involved parties confirm them, preventing disputes and ensuring consensus. Debtors can confirm or reject expenses, and payees can confirm or reject settlements.
- **Real-Time Balance Tracking:** Check who owes whom at any time with a clear and concise balance summary.
- **Flexible Debtor Selection:** When adding an expense, you can select specific debtors or choose "Select All" to split the cost among all group members.
- **Automated Cleanup:** The bot automatically cleans up old, inactive wizards and expired pending/rejected requests to keep the chat and database tidy.
- **User-Specific Settings:** Users can manage their own settings, such as enabling auto-confirmation for expenses or settlements.
- **Robust Error Handling:** The bot is designed to be resilient, handling common issues like message deletion or concurrent user actions gracefully.

## Getting Started

Follow these instructions to get your own instance of the Group Accountant Robot up and running.

### Prerequisites

- Python 3.8+
- A Telegram Bot Token from [BotFather](https://t.me/BotFather)
- A public Telegram Channel to act as file storage, and its Channel ID.

### Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd GroupAccountantRobot
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

### Configuration

The bot is configured entirely through environment variables. You can set them directly in your shell or use a `.env` file (you would need to modify the code to use a library like `python-dotenv`).

| Variable                | Description                                                                                                | Default Value      |
| ----------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------ |
| `BOT_TOKEN`             | **(Required)** Your Telegram bot token.                                                                    | `None`             |
| `FILES_CHANNEL_ID`      | **(Required)** The ID of the public Telegram channel where the bot will store uploaded files (receipts, etc.). | `None`             |
| `ADMIN_USER_IDS`        | A comma-separated list of Telegram user IDs that have admin privileges for the bot.                        | `""` (empty)       |
| `DB_PATH`               | The file path for the SQLite database.                                                                     | `debt_manager.db`  |
| `LOG_LEVEL`             | The logging level for the application.                                                                     | `DEBUG`            |
| `DRAFT_TTL_SECONDS`     | The time in seconds an inactive wizard stays open before being automatically deleted.                        | `3600` (1 hour)    |
| `REJECTED_TTL_SECONDS`  | The time in seconds a rejected expense or settlement message stays in the chat before being deleted.         | `86400` (1 day)    |
| `PENDING_TTL_SECONDS`   | The time in seconds a pending expense or settlement message stays in the chat before being deleted.          | `172800` (2 days)  |
| `DB_TIMEZONE_OFFSET`    | The timezone offset for database timestamps to ensure TTL calculations are correct.                        | `'+5 hours'`       |
| `CURRENCY`              | The currency symbol to display for amounts.                                                                | `UZS`              |
| `SCALE`                 | The internal scale for currency calculations to handle floating-point arithmetic safely.                   | `100000`           |

### Running the Bot

Once the environment variables are set, you can run the bot with a single command:

```bash
python main.py
```

The bot will start polling for updates from Telegram.

## Usage

1.  Add the bot to your Telegram group.
2.  Send the `/start` or `/menu` command in the group.
3.  The bot will display the main menu, from which you can access all its features.
4.  Follow the on-screen wizards to add expenses, settle debts, and manage your group's finances.

## Contributing

Contributions are welcome! If you have a feature request, bug report, or want to contribute to the code, please feel free to open an issue or submit a pull request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.