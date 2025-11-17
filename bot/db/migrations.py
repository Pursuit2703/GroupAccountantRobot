import sqlite3
from bot.config import DB_TIMEZONE_OFFSET

def run_migrations(conn: sqlite3.Connection):
    cursor = conn.cursor()

    # Migration 001: Initial schema
    cursor.executescript(f"""
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS groups (
          chat_id INTEGER PRIMARY KEY,
          menu_message_id INTEGER,
          menu_message_created_at TEXT,
          settings_json TEXT,
          active_wizard_user_id INTEGER,
          active_wizard_locked_at TEXT,
          settings_editor_id INTEGER,
          settings_locked_at TEXT,
          last_activity_at TEXT,
          menu_message_last_updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          tg_id INTEGER UNIQUE NOT NULL,
          username TEXT,
          display_name TEXT,
          registered_at TEXT DEFAULT (datetime('now', '{DB_TIMEZONE_OFFSET}'))
        );

        CREATE TABLE IF NOT EXISTS group_users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          chat_id INTEGER NOT NULL,
          user_id INTEGER NOT NULL,
          joined_at TEXT DEFAULT (datetime('now', '{DB_TIMEZONE_OFFSET}')),
          FOREIGN KEY(chat_id) REFERENCES groups(chat_id) ON DELETE CASCADE,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
          UNIQUE(chat_id, user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_group_users_user_id ON group_users (user_id);
        CREATE INDEX IF NOT EXISTS idx_group_users_chat_id ON group_users (chat_id);

        CREATE TABLE IF NOT EXISTS drafts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          chat_id INTEGER NOT NULL,
          user_id INTEGER NOT NULL,
          type TEXT NOT NULL, -- 'expense' or 'settlement'
          step INTEGER NOT NULL DEFAULT 1,
          data_json TEXT NOT NULL DEFAULT '{{}}',
          created_at TEXT DEFAULT (datetime('now', '{DB_TIMEZONE_OFFSET}')),
          updated_at TEXT DEFAULT (datetime('now', '{DB_TIMEZONE_OFFSET}')),
          expires_at TEXT,
          locked INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_drafts_chat_user ON drafts(chat_id,user_id);

        CREATE TABLE IF NOT EXISTS expenses (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          expense_id TEXT UNIQUE, -- e.g. EXP20251028001
          chat_id INTEGER NOT NULL,
          payer_id INTEGER NOT NULL,
          amount_u5 INTEGER NOT NULL, -- amount * 1e5 for storing decimals
          description TEXT,
          category TEXT,
          created_at TEXT DEFAULT (datetime('now', '{DB_TIMEZONE_OFFSET}')),
          locked INTEGER DEFAULT 0,
          rejected INTEGER DEFAULT 0,
          rejected_at TEXT,
          message_id INTEGER,
          meta_json TEXT,
          FOREIGN KEY(chat_id) REFERENCES groups(chat_id),
          FOREIGN KEY(payer_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS expense_debtors (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          expense_id INTEGER NOT NULL, -- References expenses.id (integer primary key)
          debtor_id INTEGER NOT NULL,
          share_u5 INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', -- pending|confirmed|rejected
          status_at TEXT,
          FOREIGN KEY(expense_id) REFERENCES expenses(id) ON DELETE CASCADE,
          FOREIGN KEY(debtor_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_expense_debtors_expense ON expense_debtors(expense_id);

        CREATE TABLE IF NOT EXISTS debts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          from_user_id INTEGER NOT NULL,
          to_user_id INTEGER NOT NULL,
          amount_u5 INTEGER NOT NULL DEFAULT 0, -- Scaled by 100,000 to avoid floating point errors
          updated_at TEXT DEFAULT (datetime('now', '{DB_TIMEZONE_OFFSET}')),
          UNIQUE(from_user_id, to_user_id),
          FOREIGN KEY(from_user_id) REFERENCES users(id),
          FOREIGN KEY(to_user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_debts_from_user_id ON debts (from_user_id);
        CREATE INDEX IF NOT EXISTS idx_debts_to_user_id ON debts (to_user_id);

        CREATE TABLE IF NOT EXISTS settlements (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          settlement_id TEXT UNIQUE,
          chat_id INTEGER NOT NULL,
          from_user_id INTEGER NOT NULL, -- initiator (says they paid)
          to_user_id INTEGER NOT NULL,   -- counterparty (the one who should confirm)
          amount_u5 INTEGER NOT NULL,
          created_at TEXT DEFAULT (datetime('now', '{DB_TIMEZONE_OFFSET}')),
          status TEXT NOT NULL DEFAULT 'pending', -- pending|confirmed|rejected
          confirmed_at TEXT,
          status_at TIMESTAMP,
          confirmed_by INTEGER,
          reject_reason TEXT,
          message_id INTEGER,
          meta_json TEXT,
          FOREIGN KEY(chat_id) REFERENCES groups(chat_id),
          FOREIGN KEY(from_user_id) REFERENCES users(id),
          FOREIGN KEY(to_user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS files (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          file_id TEXT NOT NULL, -- Telegram file_id
          origin_channel_message_id INTEGER,
          uploader_user_id INTEGER,
          uploaded_at TEXT DEFAULT (datetime('now', '{DB_TIMEZONE_OFFSET}')),
          type TEXT,
          related_type TEXT, -- expense|settlement|draft
          related_id TEXT,
          mime TEXT,
          size INTEGER,
          FOREIGN KEY(uploader_user_id) REFERENCES users(id)
        );


    """)