import sqlite3
import os
import sys

# Ensure we can import backend modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.config import settings

def fix_db():
    print(f"Checking database at: {settings.database_url}")
    
    # Parse DB path from URL (sqlite:///./enterprise.db -> ./enterprise.db)
    db_path = settings.database_url.replace("sqlite:///", "")
    
    if not os.path.exists(db_path):
        print(f"Creating new database at {db_path}...")
        # Create empty file
        open(db_path, 'a').close()
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check for 'messages' table schema
    try:
        cursor.execute("PRAGMA table_info(messages)")
        columns = [row[1] for row in cursor.fetchall()]
        print(f"Messages table columns: {columns}")
        
        if 'id' in columns and 'message_id' not in columns:
            print("CRITICAL: Found 'id' column but missing 'message_id'. Migration needed.")
            # This would require a complex migration, usually handled by .sql files
            # For now, we prefer to let the SQL migrations run.
            pass
        elif 'message_id' in columns:
             print("Schema looks correct (has message_id).")
        else:
            print("Messages table might be missing.")

    except Exception as e:
        print(f"Error checking schema: {e}")
    finally:
        conn.close()

    # Run the bootstrap script for migrations if it exists
    bootstrap_script = os.path.join(os.path.dirname(__file__), "bootstrap.py")
    if os.path.exists(bootstrap_script):
        print("Running bootstrap.py to apply migrations...")
        os.system(f"python {bootstrap_script}")
    else:
        # Fallback: run init_db if available
        print("No bootstrap.py found. Trying to run migrations manually via backend...")
        # We can implement a direct migration runner here if needed, 
        # but usually the app startup does this. 
        # Let's try to run the server briefly to trigger migrations?
        # Or better, just advise the user to restart.
        print("Please restart the backend to apply pending migrations.")

if __name__ == "__main__":
    fix_db()
