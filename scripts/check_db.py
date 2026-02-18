import sqlite3
import os

DB_PATH = "backend/data/agent_data.db"

def check_db():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("--- Tables ---")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    for table in tables:
        print(f"- {table[0]}")
        cursor.execute(f"PRAGMA table_info({table[0]})")
        columns = cursor.fetchall()
        col_names = [c[1] for c in columns]
        print(f"  Columns: {', '.join(col_names)}")
        
    conn.close()

if __name__ == "__main__":
    check_db()
