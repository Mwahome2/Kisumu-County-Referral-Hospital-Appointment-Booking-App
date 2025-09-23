import sqlite3, hashlib

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

conn = sqlite3.connect("kisumu_hospital.db")
c = conn.cursor()

# Ensure users table exists
c.execute('''CREATE TABLE IF NOT EXISTS users
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT UNIQUE,
              password_hash TEXT,
              role TEXT,
              department TEXT)''')

# Default users
default_users = [
    ("admin", "admin123", "admin", "ALL"),
    ("reception1", "receptionpw", "receptionist", "OPD"),
    ("doctor1", "doctorpw", "doctor", "Dental"),
]

for username, pwd, role, dept in default_users:
    password_hash = hash_password(pwd)
    c.execute(
        "INSERT OR REPLACE INTO users (username, password_hash, role, department) VALUES (?, ?, ?, ?)",
        (username, password_hash, role, dept),
    )

conn.commit()
conn.close()

print("✅ Default users created:")
print("   admin / admin123 (Admin)")
print("   reception1 / receptionpw (Receptionist)")
print("   doctor1 / doctorpw (Doctor)")
