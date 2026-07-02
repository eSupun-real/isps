import sqlite3
import os

db_path = "../uploads/isps_hbt.db"
if not os.path.exists(db_path):
    db_path = "uploads/isps_hbt.db"

conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("SELECT id, error, status, response FROM llm_logs WHERE status != 'success' ORDER BY id DESC LIMIT 5")
for row in c.fetchall():
    print(f"ID: {row[0]}")
    print(f"Status: {row[2]}")
    print(f"Error: {row[1]}")
    print("--- RESPONSE ---")
    print(row[3])
    print("=" * 60)
conn.close()
