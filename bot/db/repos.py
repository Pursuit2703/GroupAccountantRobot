
import sqlite3
import json
from bot.db.connection import get_connection
from bot.logger import get_logger
logger = get_logger(__name__)

def create_group_if_not_exists(chat_id: int):
    with get_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO groups (chat_id, last_activity_at) VALUES (?, datetime('now'))", (chat_id,))

def get_group(chat_id: int) -> dict | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM groups WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_group_settings(chat_id: int) -> dict:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT settings_json FROM groups WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        if row and row['settings_json']:
            return json.loads(row['settings_json'])
        return {}

def update_group_settings(chat_id: int, settings: dict) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE groups SET settings_json = ? WHERE chat_id = ?", (json.dumps(settings), chat_id))

def create_or_update_group_menu(chat_id: int, message_id: int) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO groups (chat_id, menu_message_id, menu_message_created_at, menu_message_last_updated_at, last_activity_at)
            VALUES (?, ?, datetime('now'), datetime('now'), datetime('now'))
            ON CONFLICT(chat_id) DO UPDATE SET
                menu_message_id = excluded.menu_message_id,
                menu_message_last_updated_at = excluded.menu_message_last_updated_at,
                last_activity_at = datetime('now')
        """, (chat_id, message_id))

def update_group_last_activity(chat_id: int) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE groups SET last_activity_at = datetime('now') WHERE chat_id = ?", (chat_id,))

def get_groups_with_old_menus(timeout_seconds: int) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT * FROM groups 
            WHERE menu_message_id IS NOT NULL 
            AND last_activity_at < datetime('now', '-' || ? || ' seconds')
        """, (timeout_seconds,))
        return [dict(row) for row in cursor.fetchall()]

def set_menu_message_id(chat_id: int, menu_message_id: int | None) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE groups SET menu_message_id = ? WHERE chat_id = ?", (menu_message_id, chat_id))

def create_user_if_not_exists(tg_id: int, username: str | None, display_name: str | None) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (tg_id, username, display_name) VALUES (?, ?, ?)",
                       (tg_id, username, display_name))

        cursor.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
        user_id = cursor.fetchone()[0]
        return user_id

def create_draft(chat_id: int, user_id: int, draft_type: str, expires_at: str) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO drafts (chat_id, user_id, type, expires_at) VALUES (?, ?, ?, ?)",
                       (chat_id, user_id, draft_type, expires_at))
        draft_id = cursor.lastrowid
        return draft_id

def get_draft_by_id(draft_id: int) -> dict | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_draft_owner_by_message_id(chat_id: int, message_id: int) -> int | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_id FROM drafts
            WHERE chat_id = ? AND json_extract(data_json, '$.wizard_message_id') = ?
        """, (chat_id, message_id))
        row = cursor.fetchone()
        return row['user_id'] if row else None


def get_active_draft(chat_id: int, user_id: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, type, step, data_json, expires_at, user_id
            FROM drafts
            WHERE chat_id = ? AND user_id = ? AND expires_at > datetime('now')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (chat_id, user_id),
        )
        row = cursor.fetchone()
        if row:
            return {
                "id": row[0],
                "type": row[1],
                "step": row[2],
                "data_json": row[3],
                "expires_at": row[4],
                "user_id": row[5],
            }
        return None


def get_active_drafts_by_user(chat_id: int, user_id: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, type, step, data_json, expires_at
            FROM drafts
            WHERE chat_id = ? AND user_id = ? AND expires_at > datetime('now')
            ORDER BY created_at DESC
            """,
            (chat_id, user_id),
        )
        rows = cursor.fetchall()
        drafts = []
        for row in rows:
            drafts.append(
                {
                    "id": row[0],
                    "type": row[1],
                    "step": row[2],
                    "data_json": row[3],
                    "expires_at": row[4],
                }
            )
        return drafts




def update_draft(draft_id: int, data_json: dict, step: int, expires_at: str) -> None:
    logger.debug(f"Updating draft {draft_id} with data: {data_json}")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE drafts SET data_json = ?, step = ?, expires_at = ?, updated_at = datetime('now') WHERE id = ?",
                       (json.dumps(data_json), step, expires_at, draft_id))

def add_user_to_group_if_not_exists(user_id: int, chat_id: int) -> None:
    if chat_id > 0:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO group_users (user_id, chat_id) VALUES (?, ?)", (user_id, chat_id))

def get_group_members(chat_id: int, exclude_user_id: int | None = None, exclude_from_settings: bool = True) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        
        excluded_members = []
        if exclude_from_settings:
            settings = get_group_settings(chat_id)
            excluded_members = settings.get('excluded_members', [])
        
        logger.info(f"Fetching group members for chat_id: {chat_id}, excluding: {excluded_members}")
        
        query = """
            SELECT DISTINCT u.id, u.display_name 
            FROM users u
            JOIN group_users gu ON u.id = gu.user_id
            WHERE gu.chat_id = ?
        """
        params = [chat_id]
        
        if exclude_user_id is not None:
            query += " AND u.id != ?"
            params.append(exclude_user_id)
        
        if excluded_members:
            query += f" AND u.id NOT IN ({','.join('?' for _ in excluded_members)})"
            params.extend(excluded_members)
            
        cursor.execute(query, params)
        members = [dict(row) for row in cursor.fetchall()]
        logger.info(f"Found {len(members)} group members for chat {chat_id}: {members}")
        return members

def get_user_display_name(user_id: int) -> str | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT display_name FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return row['display_name'] if row else None

def get_user(user_id: int) -> dict | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def set_active_wizard_user_id(chat_id: int, user_id: int | None) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        if user_id:
            cursor.execute("UPDATE groups SET active_wizard_user_id = ?, active_wizard_locked_at = datetime('now') WHERE chat_id = ?", (user_id, chat_id))
        else:
            cursor.execute("UPDATE groups SET active_wizard_user_id = NULL, active_wizard_locked_at = NULL WHERE chat_id = ?", (chat_id,))

def set_settings_editor_id(chat_id: int, user_id: int | None) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        if user_id:
            cursor.execute("UPDATE groups SET settings_editor_id = ?, settings_locked_at = datetime('now') WHERE chat_id = ?", (user_id, chat_id))
        else:
            cursor.execute("UPDATE groups SET settings_editor_id = NULL, settings_locked_at = NULL WHERE chat_id = ?", (chat_id,))

def delete_file_by_id(file_row_id: int) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM files WHERE id = ?", (file_row_id,))

def create_expense(chat_id, payer_id, amount_u5, description, category) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO expenses (chat_id, payer_id, amount_u5, description, category)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, payer_id, amount_u5, description, category),
        )
        return cursor.lastrowid

def create_expense_debtors(expense_id, debtors, share_u5) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        for debtor_id in debtors:
            cursor.execute(
                """
                INSERT INTO expense_debtors (expense_id, debtor_id, share_u5)
                VALUES (?, ?, ?)
                """,
                (expense_id, debtor_id, share_u5),
            )

def get_expense(expense_id: int) -> dict | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_expense_debtors(expense_id: int) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ed.*, u.display_name, u.tg_id FROM expense_debtors ed JOIN users u ON ed.debtor_id = u.id WHERE ed.expense_id = ?", (expense_id,))
        return [dict(row) for row in cursor.fetchall()]

def get_expense_files(expense_id: int) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id as file_row_id, file_id, origin_channel_message_id, mime, size FROM files WHERE related_type = 'expense' AND related_id = ?",
            (str(expense_id),),
        )
        return [dict(row) for row in cursor.fetchall()]

def update_file_relation(file_row_id: int, related_type: str, related_id: int) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE files SET related_type = ?, related_id = ? WHERE id = ?",
            (related_type, str(related_id), file_row_id),
        )

def update_debtor_status(expense_id: int, debtor_id: int, status: str) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE expense_debtors SET status = ?, status_at = datetime('now') WHERE expense_id = ? AND debtor_id = ?",
            (status, expense_id, debtor_id),
        )

def reject_expense(expense_id: int) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE expenses SET rejected = 1, rejected_at = datetime('now') WHERE id = ?",
            (expense_id,),
        )
        
def delete_expense(expense_id: int) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))


def upsert_debt(from_user_id: int, to_user_id: int, amount_u5: int) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        # Netting logic from idea.md
        # 1. Get existing debt from_user -> to_user
        cursor.execute("SELECT amount_u5 FROM debts WHERE from_user_id = ? AND to_user_id = ?", (from_user_id, to_user_id))
        debt_xy = cursor.fetchone()
        if debt_xy:
            new_amount = debt_xy[0] + amount_u5
            cursor.execute("UPDATE debts SET amount_u5 = ?, updated_at = datetime('now') WHERE from_user_id = ? AND to_user_id = ?", (new_amount, from_user_id, to_user_id))
        else:
            # 2. Get existing debt to_user -> from_user
            cursor.execute("SELECT amount_u5 FROM debts WHERE from_user_id = ? AND to_user_id = ?", (to_user_id, from_user_id))
            debt_yx = cursor.fetchone()
            if debt_yx:
                if amount_u5 >= debt_yx[0]:
                    new_amount = amount_u5 - debt_yx[0]
                    cursor.execute("DELETE FROM debts WHERE from_user_id = ? AND to_user_id = ?", (to_user_id, from_user_id))
                    if new_amount > 0:
                        cursor.execute("INSERT INTO debts (from_user_id, to_user_id, amount_u5) VALUES (?, ?, ?)", (from_user_id, to_user_id, new_amount))
                else:
                    new_amount = debt_yx[0] - amount_u5
                    cursor.execute("UPDATE debts SET amount_u5 = ?, updated_at = datetime('now') WHERE from_user_id = ? AND to_user_id = ?", (new_amount, to_user_id, from_user_id))
            else:
                cursor.execute("INSERT INTO debts (from_user_id, to_user_id, amount_u5) VALUES (?, ?, ?)", (from_user_id, to_user_id, amount_u5))

def get_debts_for_group(chat_id: int) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                d.from_user_id,
                u_from.display_name AS from_user_display_name,
                d.to_user_id,
                u_to.display_name AS to_user_display_name,
                d.amount_u5
            FROM
                debts d
            JOIN
                users u_from ON d.from_user_id = u_from.id
            JOIN
                users u_to ON d.to_user_id = u_to.id
            JOIN
                group_users gu_from ON d.from_user_id = gu_from.user_id
            JOIN
                group_users gu_to ON d.to_user_id = gu_to.user_id
            WHERE
                gu_from.chat_id = ? AND gu_to.chat_id = ? AND d.amount_u5 >= 100
            """,
            (chat_id, chat_id)
        )
        result = [dict(row) for row in cursor.fetchall()]
        logger.debug(f"get_debts_for_group result: {result}")
        return result

def get_user_balance_summary(user_id: int, chat_id: int) -> dict:
    with get_connection() as conn:
        cursor = conn.cursor()

        # Get total owed and total owed to user
        cursor.execute(
            """
            SELECT
                IFNULL(SUM(CASE WHEN d.from_user_id = ? THEN d.amount_u5 ELSE 0 END), 0) AS total_owed,
                IFNULL(SUM(CASE WHEN d.to_user_id = ? THEN d.amount_u5 ELSE 0 END), 0) AS total_owed_to_user
            FROM
                debts d
            JOIN
                group_users gu_from ON d.from_user_id = gu_from.user_id
            JOIN
                group_users gu_to ON d.to_user_id = gu_to.user_id
            WHERE
                (d.from_user_id = ? OR d.to_user_id = ?)
                AND gu_from.chat_id = ? AND gu_to.chat_id = ?;
            """,
            (user_id, user_id, user_id, user_id, chat_id, chat_id)
        )
        summary = dict(cursor.fetchone())

        # Get detailed debts involving the user
        cursor.execute(
            """
            SELECT
                d.from_user_id,
                u_from.display_name AS from_user_display_name,
                d.to_user_id,
                u_to.display_name AS to_user_display_name,
                d.amount_u5
            FROM
                debts d
            JOIN
                users u_from ON d.from_user_id = u_from.id
            JOIN
                users u_to ON d.to_user_id = u_to.id
            JOIN
                group_users gu_from ON d.from_user_id = gu_from.user_id
            JOIN
                group_users gu_to ON d.to_user_id = gu_to.user_id
            WHERE
                (d.from_user_id = ? OR d.to_user_id = ?)
                AND gu_from.chat_id = ? AND gu_to.chat_id = ? AND d.amount_u5 >= 100;
            """,
            (user_id, user_id, chat_id, chat_id)
        )
        detailed_debts = [dict(row) for row in cursor.fetchall()]
        logger.debug(f"get_user_balance_summary detailed_debts: {detailed_debts}")

        summary['detailed_debts'] = detailed_debts
        return summary

def get_group_history(chat_id: int, limit: int = 10, offset: int = 0) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                'expense' as type,
                e.id,
                e.created_at,
                p.display_name as payer_name,
                e.amount_u5,
                e.description,
                e.category,
                NULL as from_user_name,
                NULL as to_user_name
            FROM expenses e
            JOIN users p ON e.payer_id = p.id
            WHERE e.chat_id = ? AND e.rejected = 0 AND e.id NOT IN (
                SELECT DISTINCT expense_id FROM expense_debtors WHERE status = 'pending'
            )
            UNION ALL
            SELECT
                'settlement' as type,
                s.id,
                s.created_at,
                NULL as payer_name,
                s.amount_u5,
                NULL as description,
                NULL as category,
                fu.display_name as from_user_name,
                tu.display_name as to_user_name
            FROM settlements s
            JOIN users fu ON s.from_user_id = fu.id
            JOIN users tu ON s.to_user_id = tu.id
            WHERE s.chat_id = ? AND s.status = 'confirmed'
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (chat_id, chat_id, limit, offset))
        return [dict(row) for row in cursor.fetchall()]

def get_full_group_history(chat_id: int) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                'expense' as type,
                e.id,
                e.created_at,
                e.message_id,
                p.display_name as payer_name,
                e.amount_u5,
                e.description,
                e.category,
                NULL as from_user_name,
                NULL as to_user_name
            FROM expenses e
            JOIN users p ON e.payer_id = p.id
            WHERE e.chat_id = ? AND e.rejected = 0 AND e.id NOT IN (
                SELECT DISTINCT expense_id FROM expense_debtors WHERE status = 'pending'
            )
            UNION ALL
            SELECT
                'settlement' as type,
                s.id,
                s.created_at,
                s.message_id,
                NULL as payer_name,
                s.amount_u5,
                NULL as description,
                NULL as category,
                fu.display_name as from_user_name,
                tu.display_name as to_user_name
            FROM settlements s
            JOIN users fu ON s.from_user_id = fu.id
            JOIN users tu ON s.to_user_id = tu.id
            WHERE s.chat_id = ? AND s.status = 'confirmed'
            ORDER BY created_at DESC
            LIMIT 10000
        """, (chat_id, chat_id))
        return [dict(row) for row in cursor.fetchall()]

def create_settlement(chat_id: int, from_user_id: int, to_user_id: int, amount_u5: int) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO settlements (chat_id, from_user_id, to_user_id, amount_u5)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, from_user_id, to_user_id, amount_u5),
        )
        return cursor.lastrowid

def get_settlement(settlement_id: int) -> dict | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM settlements WHERE id = ?", (settlement_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def update_settlement_status(settlement_id: int, status: str) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE settlements SET status = ?, status_at = datetime('now'), confirmed_at = CASE WHEN ? = 'confirmed' THEN datetime('now') ELSE NULL END WHERE id = ?",
            (status, status, settlement_id),
        )


def get_settlement_files(settlement_id: int) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id as file_row_id, file_id, origin_channel_message_id, mime, size FROM files WHERE related_type = 'settlement' AND related_id = ?",
            (str(settlement_id),),
        )
        return [dict(row) for row in cursor.fetchall()]

def delete_settlement(settlement_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM settlements WHERE id = ?", (settlement_id,))

def update_expense_message_id(expense_id: int, message_id: int):
    with get_connection() as conn:
        conn.execute("UPDATE expenses SET message_id = ? WHERE id = ?", (message_id, expense_id))

def update_settlement_message_id(settlement_id: int, message_id: int):
    with get_connection() as conn:
        conn.execute("UPDATE settlements SET message_id = ? WHERE id = ?", (message_id, settlement_id))

def get_debt_between_users(user1_id: int, user2_id: int) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        # Debt from user1 to user2
        cursor.execute("SELECT amount_u5 FROM debts WHERE from_user_id = ? AND to_user_id = ?", (user1_id, user2_id))
        debt1 = cursor.fetchone()
        # Debt from user2 to user1
        cursor.execute("SELECT amount_u5 FROM debts WHERE from_user_id = ? AND to_user_id = ?", (user2_id, user1_id))
        debt2 = cursor.fetchone()

        debt1_amount = debt1[0] if debt1 else 0
        debt2_amount = debt2[0] if debt2 else 0

        return debt1_amount - debt2_amount

def get_users_owed_by_user(user_id: int, chat_id: int) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                d.to_user_id AS user_id,
                u.display_name,
                d.amount_u5
            FROM
                debts d
            JOIN
                users u ON d.to_user_id = u.id
            JOIN
                group_users gu ON d.to_user_id = gu.user_id
            WHERE
                d.from_user_id = ? AND gu.chat_id = ? AND d.amount_u5 >= 100;
            """,
            (user_id, chat_id)
        )
        return [dict(row) for row in cursor.fetchall()]

def get_owed_amount(from_user_id: int, to_user_id: int) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT amount_u5 FROM debts WHERE from_user_id = ? AND to_user_id = ?", (from_user_id, to_user_id))
        row = cursor.fetchone()
        return row['amount_u5'] if row else 0

def get_spending_by_category(chat_id: int) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT category, SUM(amount_u5) as total_amount
            FROM expenses
            WHERE chat_id = ? AND rejected = 0 AND id NOT IN (
                SELECT DISTINCT expense_id FROM expense_debtors WHERE status = 'pending'
            )
            GROUP BY category
            ORDER BY total_amount DESC
        """, (chat_id,))
        return [dict(row) for row in cursor.fetchall()]


def get_old_stale_drafts() -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM drafts WHERE expires_at < datetime('now')")
        return [dict(row) for row in cursor.fetchall()]

def get_old_rejected_expenses(seconds: int) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT DISTINCT e.id, e.chat_id, e.message_id
            FROM expenses e
            JOIN expense_debtors ed ON e.id = ed.expense_id
            WHERE ed.status = 'rejected'
            AND ed.status_at < datetime('now', '-' || ? || ' seconds')
        """, (seconds,))
        return [dict(row) for row in cursor.fetchall()]

def get_old_rejected_settlements(seconds: int) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT id, chat_id, message_id
            FROM settlements
            WHERE status = 'rejected'
            AND status_at < datetime('now', '-' || ? || ' seconds')
        """, (seconds,))
        return [dict(row) for row in cursor.fetchall()]

def get_old_pending_expenses(seconds: int) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT DISTINCT e.id, e.chat_id, e.message_id
            FROM expenses e
            JOIN expense_debtors ed ON e.id = ed.expense_id
            WHERE ed.status = 'pending'
            AND e.created_at < datetime('now', '-' || ? || ' seconds')
        """, (seconds,))
        return [dict(row) for row in cursor.fetchall()]

def get_old_pending_settlements(seconds: int) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT id, chat_id, message_id
            FROM settlements
            WHERE status = 'pending'
            AND created_at < datetime('now', '-' || ? || ' seconds')
        """, (seconds,))
        return [dict(row) for row in cursor.fetchall()]
def get_who_paid_how_much_by_period(chat_id: int, days: int) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT u.display_name, SUM(e.amount_u5) as total_amount
            FROM expenses e
            JOIN users u ON e.payer_id = u.id
            WHERE e.chat_id = ? AND e.created_at >= date('now', '-{days} days') AND e.rejected = 0 AND e.id NOT IN (
                SELECT DISTINCT expense_id FROM expense_debtors WHERE status = 'pending'
            )
            GROUP BY u.display_name
            ORDER BY total_amount DESC
        """, (chat_id,))
        return [dict(row) for row in cursor.fetchall()]
