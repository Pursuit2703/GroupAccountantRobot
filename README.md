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

## Architecture

The project is structured in a modular way to separate concerns and make the codebase easy to maintain and extend.

*   `main.py`: The main entry point of the application. It initializes and runs the bot.
*   `bot/`: This directory contains all the core bot logic.
    *   `app.py`: The heart of the bot, containing the `Bot` class that manages all Telegram message handlers, callback query handlers, and the main application loop. It also runs a background thread for cleanup tasks.
    *   `config.py`: Manages the application's configuration by reading and parsing environment variables.
    *   `logger.py`: Configures the logging for the application.
    *   `categories.py`: Defines expense categories and related helper functions.
    *   `db/`: This package handles all database interactions.
        *   `connection.py`: Provides a context manager for creating and managing SQLite database connections.
        *   `migrations.py`: Defines the database schema and handles migrations.
        *   `repos.py`: The data access layer. It contains functions to query the database, abstracting SQL from the rest of the application.
    *   `services/`: This package contains the business logic of the application.
        *   `accounting.py`: Provides functions for calculating user balances and group debts.
        *   `draft_service.py`: Manages the lifecycle of draft messages for the interactive wizards.
        *   `file_service.py`: Handles the uploading and downloading of files (like receipts) to and from the designated Telegram channel.
        *   `menu_service.py`: Responsible for generating and handling the main menu.
        *   `reporter.py`: Generates user-facing reports, like CSV exports of expenses.
        *   `wizard_service.py`: Manages the state and flow of the interactive wizards for adding expenses and settlements.
    *   `ui/`: This package is responsible for the user interface.
        *   `renderers.py`: Contains functions that generate the text and interactive keyboards for all bot messages.
        *   `wizard_config.py`: Defines the structure and configuration for each step of the wizards.
        *   `wizard_helpers.py`: Provides helper functions and utilities for the wizard system.
    *   `utils/`: This package contains miscellaneous utility functions.
        *   `currency.py`: Provides helper functions for formatting currency values.
        *   `time.py`: Contains timezone-aware time and date utility functions.

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