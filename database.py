import sqlite3
import os
from contextlib import contextmanager

DB_FILE = os.environ.get("DB_FILE", "app.db")

def get_raw_connection():
    # Connect and configure WAL mode and busy timeout (5.0s = 5000ms)
    conn = sqlite3.connect(DB_FILE, timeout=5.0)
    conn.row_factory = sqlite3.Row
    # Configure journal mode and foreign keys
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

@contextmanager
def get_db():
    conn = get_raw_connection()
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        # Create transactions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                amount REAL NOT NULL,
                timestamp TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        # Index user_id for faster lookups/aggregations
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions (user_id);")

        # Create user_summaries table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_summaries (
                user_id TEXT PRIMARY KEY,
                total_spent REAL NOT NULL DEFAULT 0.0,
                transaction_count INTEGER NOT NULL DEFAULT 0,
                active_days INTEGER NOT NULL DEFAULT 0,
                score REAL NOT NULL DEFAULT 0.0,
                last_transaction_time TEXT
            );
        """)
        # Index on score for faster ranking fetches
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_summaries_score ON user_summaries (score DESC);")
        conn.commit()
