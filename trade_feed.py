import sqlite3
import os
from datetime import datetime
import pytz

IST = pytz.timezone('Asia/Kolkata')
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trade_feed.db')


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                underlying  TEXT    NOT NULL,
                signal      TEXT,
                index_price REAL,
                option_symbol TEXT,
                entry_price REAL,
                sl_price    REAL,
                target_price REAL,
                exit_price  REAL,
                profit      REAL,
                comment     TEXT,
                status      TEXT DEFAULT 'PENDING',
                created_at  TEXT,
                updated_at  TEXT
            )
        ''')
        conn.commit()


def insert_trade(underlying, signal, index_price=None, option_symbol=None,
                 sl_price=None, target_price=None, comment=None, status='PENDING'):
    now = datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')
    with _connect() as conn:
        cur = conn.execute(
            '''INSERT INTO trades
               (underlying, signal, index_price, option_symbol,
                sl_price, target_price, comment, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (underlying, signal, index_price, option_symbol,
             sl_price, target_price, comment, status, now, now)
        )
        conn.commit()
        return cur.lastrowid


def update_trade(trade_id, **kwargs):
    if not kwargs or not trade_id:
        return
    kwargs['updated_at'] = datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')
    cols = ', '.join(f'{k} = ?' for k in kwargs)
    vals = list(kwargs.values()) + [int(trade_id)]
    with _connect() as conn:
        conn.execute(f'UPDATE trades SET {cols} WHERE id = ?', vals)
        conn.commit()


def get_recent_trades(limit=50):
    with _connect() as conn:
        rows = conn.execute(
            'SELECT * FROM trades ORDER BY id DESC LIMIT ?', (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
