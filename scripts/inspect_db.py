
import sqlite3
import json

def inspect_run(run_id):
    conn = sqlite3.connect("enterprise.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()
    
    if row:
        print(f"Run ID: {row['run_id']}")
        print(f"Status: {row['status']}")
        # print(f"Error Message: {row['error_message']}")
        print("-" * 20)
        for key in row.keys():
            print(f"{key}: {row[key]}")
    else:
        print("Run not found")
        
    conn.close()

if __name__ == "__main__":
    import sys
    run_id = sys.argv[1] if len(sys.argv) > 1 else "run_4285ef68d9114db8a4aa0eaa1a9af2d8"
    inspect_run(run_id)
