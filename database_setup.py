import sqlite3, hashlib

conn = sqlite3.connect("kisumu_hospital.db")
c = conn.cursor()

password = hashlib.sha256("admin123".encode()).hexdigest()
c.execute("INSERT OR REPLACE INTO users (username, password_hash, role, department) VALUES (?, ?, ?, ?)",
          ("admin", password, "admin", "ALL"))

conn.commit()
conn.close()
print("✅ Admin user created: admin / admin123")
