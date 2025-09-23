import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date
import plotly.express as px
import hashlib
from twilio.rest import Client

# --- DB Setup ---
conn = sqlite3.connect("kisumu_hospital.db", check_same_thread=False)
c = conn.cursor()

# Create tables if not exist
c.execute('''CREATE TABLE IF NOT EXISTS users
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT UNIQUE,
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

# --- Helper: Hash password ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# --- Ensure admin exists ---
admin_check = c.execute("SELECT * FROM users WHERE username=?", ("admin",)).fetchone()
if not admin_check:
    c.execute("INSERT INTO users (username, password_hash, role, department) VALUES (?, ?, ?, ?)",
              ("admin", hash_password("admin123"), "admin", "ALL"))
    conn.commit()

# --- Manual Authentication ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = None
    st.session_state["role"] = None

def manual_login():
    st.subheader("🔑 Staff Login")
    uname = st.text_input("Username")
    pwd = st.text_input("Password", type="password")
    if st.button("Login"):
        hashed = hash_password(pwd)
        row = c.execute("SELECT role FROM users WHERE username=? AND password_hash=?", (uname, hashed)).fetchone()
        if row:
            st.session_state["logged_in"] = True
            st.session_state["username"] = uname
            st.session_state["role"] = row[0]
            st.success(f"✅ Logged in as {uname} ({row[0]})")
        else:
            st.error("Username/Password is incorrect")

def manual_logout():
    if st.sidebar.button("Logout"):
        st.session_state["logged_in"] = False
        st.session_state["username"] = None
        st.session_state["role"] = None
        st.experimental_rerun()

# --- Twilio Setup from Secrets ---
account_sid = st.secrets.get("TWILIO_ACCOUNT_SID")
auth_token = st.secrets.get("TWILIO_AUTH_TOKEN")
twilio_number = st.secrets.get("TWILIO_PHONE")

def send_sms(phone, msg):
    if account_sid and auth_token and twilio_number:
        try:
            from twilio.rest import Client
            client = Client(account_sid, auth_token)
            client.messages.create(
                body=msg,
                from_=twilio_number,
                to=f"whatsapp:+{phone}" if "whatsapp" in twilio_number else f"+{phone}"
            )
        except Exception as e:
            st.warning(f"⚠️ SMS/WhatsApp not sent: {e}")
    else:
        st.info("ℹ️ Twilio not configured. Skipping SMS.")

# --- Main App ---
if not st.session_state["logged_in"]:
    manual_login()
else:
    manual_logout()

    role = st.session_state["role"]
    st.title("🏥 Kisumu County Referral Hospital - Appointment Booking")

    # Receptionist Booking Page
    if role == "receptionist":
        st.subheader("📌 Book Appointment")
        with st.form("booking_form"):
            patient_name = st.text_input("Patient Name")
            phone = st.text_input("Phone Number")
            department = st.selectbox("Department", ["OPD", "MCH/FP", "Dental", "Surgery", "Orthopedics", "Eye"])
            doctor = st.text_input("Doctor (optional)")
            date_ = st.date_input("Preferred Date", min_value=date.today())
            submit = st.form_submit_button("Book Appointment")
            if submit and patient_name and phone:
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
                    if st.button(f"Confirm {row['id']}", key=f"confirm{row['id']}"):
                        c.execute("UPDATE appointments SET status=?, updated_at=? WHERE id=?",
                                  ("confirmed", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row['id']))
                        conn.commit()
                        send_sms(row['phone'], f"Your appointment at Kisumu Hospital is confirmed for {row['date']}.")
                        st.success(f"✅ Confirmed appointment {row['id']}")
                with col2:
                    if st.button(f"Cancel {row['id']}", key=f"cancel{row['id']}"):
                        c.execute("UPDATE appointments SET status=?, updated_at=? WHERE id=?",
                                  ("cancelled", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row['id']))
                        conn.commit()
                        send_sms(row['phone'], f"Your appointment at Kisumu Hospital has been cancelled.")
                        st.warning(f"❌ Cancelled appointment {row['id']}")
        else:
            st.info("No appointments yet.")

    # Analytics Dashboard
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
