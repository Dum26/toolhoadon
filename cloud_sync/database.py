import sqlite3
import json
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal

from config import DB_PATH
from models import InventoryItem


def connect():
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ma_hang TEXT NOT NULL UNIQUE,
        ten_hang TEXT NOT NULL,
        ton_kho TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(inventory)")}
    if "active" not in columns:
        connection.execute("ALTER TABLE inventory ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
    connection.execute("""CREATE TABLE IF NOT EXISTS sync_info (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        filters_json TEXT,
        updated_at TEXT NOT NULL
    )""")
    return connection


def save_inventory(items: list[InventoryItem], filters=None) -> int:
    if not items:
        raise ValueError("Báo cáo không có dòng hàng hợp lệ; database chưa được thay đổi.")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(connect()) as db, db:
        db.execute("UPDATE inventory SET active = 0")
        db.executemany("""INSERT INTO inventory (ma_hang, ten_hang, ton_kho, updated_at, active)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(ma_hang) DO UPDATE SET
                ten_hang=excluded.ten_hang, ton_kho=excluded.ton_kho,
                updated_at=excluded.updated_at, active=1""",
            [(x.ma_hang, x.ten_hang, str(x.ton_kho), now) for x in items])
        db.execute("""INSERT INTO sync_info (id, filters_json, updated_at) VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET filters_json=excluded.filters_json,
            updated_at=excluded.updated_at""", (json.dumps(filters, ensure_ascii=False) if filters else None, now))
    return len(items)


def _number(value):
    number = Decimal(value)
    return int(number) if number == number.to_integral_value() else float(number)


def _item(row):
    return {"ma_hang": row["ma_hang"], "ten_hang": row["ten_hang"],
            "ton_kho": _number(row["ton_kho"]), "updated_at": row["updated_at"]}


def list_inventory():
    with closing(connect()) as db:
        rows = db.execute("SELECT ma_hang, ten_hang, ton_kho, updated_at FROM inventory WHERE active = 1 ORDER BY ma_hang COLLATE NOCASE").fetchall()
    return [_item(row) for row in rows]


def get_inventory(ma_hang):
    with closing(connect()) as db:
        row = db.execute("SELECT ma_hang, ten_hang, ton_kho, updated_at FROM inventory WHERE active = 1 AND ma_hang = ? COLLATE NOCASE", (ma_hang,)).fetchone()
    return _item(row) if row else None


def last_sync_info():
    with closing(connect()) as db:
        row = db.execute("SELECT filters_json, updated_at FROM sync_info WHERE id = 1").fetchone()
    return {"filters": json.loads(row["filters_json"]) if row and row["filters_json"] else None,
            "updated_at": row["updated_at"] if row else None}
