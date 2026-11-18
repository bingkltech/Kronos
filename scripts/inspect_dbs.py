import sqlite3
import json
from decimal import Decimal

def inspect_db(db_path):
    print(f"=== {db_path} ===")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print("Tables:", tables)
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table})")
        cols = [col[1] for col in cursor.fetchall()]
        print(f"\nTable {table} columns: {cols}")
        rows = cursor.execute(f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT 15").fetchall()
        print(f"Total rows: {cursor.execute(f'SELECT count(*) FROM {table}').fetchone()[0]}")
        print(f"Latest {len(rows)} rows:")
        for r in rows:
            print(r)

if __name__ == "__main__":
    inspect_db("data/tiger_trades.db")
    inspect_db("data/trade_autopsies.db")
