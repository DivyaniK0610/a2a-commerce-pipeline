"""
database.py — SQLite schema initialization and CRUD helpers
A2A Commerce Pipeline | Razorpay Buildathon Track 1
"""

import sqlite3
import uuid
import json
from datetime import datetime

DB_PATH = "a2a_commerce.db"


def get_connection():
    """Returns a SQLite connection with row_factory for dict-like rows."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrency
    return conn


def init_db():
    """Creates all tables if they don't exist."""
    conn = get_connection()
    cur = conn.cursor()

    # ── Inventory ──────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            item_id     TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            description TEXT,
            price       REAL NOT NULL,
            stock_count INTEGER NOT NULL DEFAULT 0,
            category    TEXT
        )
    """)

    # ── Orders ─────────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            transaction_id      TEXT PRIMARY KEY,
            razorpay_order_id   TEXT,
            item_id             TEXT,
            quantity            INTEGER,
            total_amount        REAL,
            status              TEXT DEFAULT 'created',
            created_at          TEXT
        )
    """)

    # ── Audit Logs (Immutable) ─────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            log_id          TEXT PRIMARY KEY,
            timestamp       TEXT NOT NULL,
            transaction_id  TEXT,
            action          TEXT NOT NULL,
            raw_payload     TEXT,
            status          TEXT
        )
    """)

    conn.commit()
    conn.close()
    print("[DB] Tables initialized.")


# ─────────────────────────────────────────────────────────────────────────────
# Inventory helpers
# ─────────────────────────────────────────────────────────────────────────────

def search_items(query: str) -> list[dict]:
    """Fuzzy search inventory by name (case-insensitive LIKE)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM inventory WHERE LOWER(name) LIKE LOWER(?) AND stock_count > 0",
        (f"%{query}%",)
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def get_item_by_id(item_id: str) -> dict | None:
    """Exact lookup by item_id."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM inventory WHERE item_id = ?", (item_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def check_stock(item_id: str, quantity: int) -> tuple[bool, int]:
    """
    Returns (is_available: bool, current_stock: int).
    Does NOT reserve — reservation happens at order creation.
    """
    item = get_item_by_id(item_id)
    if not item:
        return False, 0
    return item["stock_count"] >= quantity, item["stock_count"]


def decrement_stock(item_id: str, quantity: int) -> bool:
    """Atomically decrements stock. Returns True if successful."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE inventory
        SET stock_count = stock_count - ?
        WHERE item_id = ? AND stock_count >= ?
        """,
        (quantity, item_id, quantity)
    )
    success = cur.rowcount > 0
    conn.commit()
    conn.close()
    return success


# ─────────────────────────────────────────────────────────────────────────────
# Order helpers
# ─────────────────────────────────────────────────────────────────────────────

def create_order_record(item_id: str, quantity: int, total_amount: float,
                        razorpay_order_id: str = None) -> str:
    """Creates an order record and returns the transaction_id."""
    txn_id = str(uuid.uuid4())
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO orders (transaction_id, razorpay_order_id, item_id, quantity,
                            total_amount, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'created', ?)
        """,
        (txn_id, razorpay_order_id, item_id, quantity, total_amount,
         datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()
    return txn_id


def update_order_status(transaction_id: str, status: str):
    """Updates the status of an order."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE orders SET status = ? WHERE transaction_id = ?",
        (status, transaction_id)
    )
    conn.commit()
    conn.close()


def get_all_orders() -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders ORDER BY created_at DESC")
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Audit Log helpers
# ─────────────────────────────────────────────────────────────────────────────

def log_action(transaction_id: str, action: str, payload: dict, status: str):
    """
    Writes an immutable audit log entry.
    action examples: 'beckn_search', 'beckn_select', 'beckn_init', 'razorpay_create'
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO audit_logs (log_id, timestamp, transaction_id, action, raw_payload, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            datetime.utcnow().isoformat(),
            transaction_id,
            action,
            json.dumps(payload, ensure_ascii=False),
            status
        )
    )
    conn.commit()
    conn.close()


def get_all_logs() -> list[dict]:
    """Returns all audit logs ordered by timestamp descending."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC")
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows
