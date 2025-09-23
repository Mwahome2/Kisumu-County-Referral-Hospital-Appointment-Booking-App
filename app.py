import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date
import plotly.express as px
import streamlit_authenticator as stauth
import hashlib
from twilio.rest import Client

# --- DB Setup ---
conn = sqlite3.connect("kisumu_hospital.db", check_same_thread=False)
c = conn.cursor()

# Tables
c.execute('''CREATE TABLE IF NOT EXISTS users
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT,
              password_hash TEXT,
              role TEXT,
              department TEXT)''')

c.execute('''CREATE TABLE IF NOT EXISTS appointments
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
              patient_name TEXT,
              phone TEXT,
              department TEXT,
              doctor TEXT,
              date TEXT,
              status TEXT,
              created_at TEXT,
              updated_at TEXT,
              clinic_id INTEGER)''')
conn.commit()

# --- Helper: Hash passwords ---
def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

# --- Authentication ---
usernames = [row[0] for row in c.execute("SELECT username FROM users").fetchall()]
passwords = [row[0] for row in c.execute("SELECT password_hash FROM users").fetchall()]
roles = [row[0] for row in c.execute("SELECT role FROM users").fetchall()]

credentials = {"usernames": {}}
for i, u in enumerate(usernames):
    credentials["usernames"][u] = {"password": passwords[i], "role": roles[i]}

authenticator = stauth.Authenticate(
    credentials, "kisumu_app", "abcdef", cookie_expiry_days=1
)

name, authentication_status, username = authenticator.login("Login", "main")

# --- Main App ---
if authentication_status:

    authenticator.logout("Logout", "sidebar")

    role = c.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()[0]

    st.title("🏥 Kisumu County Referral Hospital - Appointment Booking")

    if role == "receptionist":
        st.subheader("📌 Book Appointment")
        with st.form("booking_form"):
            patient_name = st.text_input("Patient Name")
            phone = st.text_input("Phone Number")
            department = st.selectbox("Department", ["OPD", "MCH/FP", "Dental", "Surgery", "Orthopedics", "Eye"])
            doctor = st.text_input("Doctor (optional)")
            date_ = st.date_input("Preferred Date", min_value=date.today())
            submit = st.form_submit_button("Book Appointment")
            if submit:
                created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c.execute("""INSERT INTO appointments 
                             (patient_name, phone, department, doctor, date, status, created_at, updated_at, clinic_id) 
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                          (patient_name, phone, department, doctor, str(date_), "pending", created_at, created_at, 1))
                conn.commit()
                st.success(f"✅ Appointment booked for {patient_name} on {date_}")

    # Staff/Admin Dashboard
    if role in ["doctor", "admin", "receptionist"]:
        st.subheader("📋 Manage Appointments")
        df = pd.read_sql("SELECT * FROM appointments", conn)

        if not df.empty:
            for i, row in df.iterrows():
                st.write(f"📌 {row['patient_name']} | {row['department']} | {row['date']} | Status: {row['status']}")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"Confirm {row['id']}", key=f"c{row['id']}"):
                        c.execute("UPDATE appointments SET status=?, updated_at=? WHERE id=?",
                                  ("confirmed", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row['id']))
                        conn.commit()
                        # Send SMS/WhatsApp (Twilio example)
                        try:
                            client = Client("TWILIO_SID", "TWILIO_AUTH")
                            message = client.messages.create(
                                body=f"Your appointment at Kisumu Hospital is confirmed for {row['date']}.",
                                from_="whatsapp:+14155238886",
                                to=f"whatsapp:+{row['phone']}"
                            )
                        except:
                            st.warning("⚠️ SMS/WhatsApp not sent (check Twilio setup).")
                with col2:
                    if st.button(f"Cancel {row['id']}", key=f"x{row['id']}"):
                        c.execute("UPDATE appointments SET status=?, updated_at=? WHERE id=?",
                                  ("cancelled", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row['id']))
                        conn.commit()

        else:
            st.info("No appointments yet.")

    # Analytics
    if role == "admin":
        st.subheader("📊 Analytics Dashboard")
        df = pd.read_sql("SELECT * FROM appointments", conn)
        if not df.empty:
            fig = px.histogram(df, x="department", color="status", title="Appointments by Department")
            st.plotly_chart(fig)
            fig2 = px.histogram(df, x="date", color="status", title="Appointments over Time")
            st.plotly_chart(fig2)
        else:
            st.info("No data for analytics yet.")

elif authentication_status == False:
    st.error("Username/Password is incorrect")
else:
    st.warning("Please login to continue.")
