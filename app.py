import os
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date
import plotly.express as px
import hashlib
from twilio.rest import Client

# --- DB Setup ---
DB_PATH = "kisumu_hospital.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
c = conn.cursor()

# Create tables if not exist (base schema)
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

# --- Ensure columns (migrations for older DBs) ---
def ensure_column_exists(table, column_name, column_def):
    info = c.execute(f"PRAGMA table_info({table})").fetchall()
    columns = [row[1] for row in info]
    if column_name not in columns:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_def}")
        conn.commit()

# ensure clinic_id exists (default 1) and booking_ref exists
ensure_column_exists("appointments", "clinic_id", "INTEGER DEFAULT 1")
ensure_column_exists("appointments", "booking_ref", "TEXT")

# --- Helper: Hash password ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# --- Ensure admin exists ---
admin_check = c.execute("SELECT * FROM users WHERE username=?", ("admin",)).fetchone()
if not admin_check:
    c.execute("INSERT INTO users (username, password_hash, role, department) VALUES (?, ?, ?, ?)",
              ("admin", hash_password("admin123"), "admin", "ALL"))
    conn.commit()

# --- Session State for Auth ---
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
            st.rerun()   # fixed
        else:
            st.error("Username/Password is incorrect")

def manual_logout():
    if st.sidebar.button("Logout"):
        st.session_state["logged_in"] = False
        st.session_state["username"] = None
        st.session_state["role"] = None
        st.rerun()   # fixed

# --- Twilio Setup (Streamlit Secrets or environment fallback) ---
try:
    account_sid = st.secrets["TWILIO_ACCOUNT_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]
    twilio_number = st.secrets["TWILIO_PHONE"]
except Exception:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_number = os.getenv("TWILIO_PHONE", "")

def send_sms(phone, msg):
    """Send real SMS/WhatsApp if credentials exist, otherwise show simulated message."""
    if account_sid and auth_token and twilio_number:
        try:
            client = Client(account_sid, auth_token)
            if "whatsapp" in str(twilio_number).lower():
                client.messages.create(body=msg, from_=twilio_number, to=f"whatsapp:+{phone}")
            else:
                client.messages.create(body=msg, from_=twilio_number, to=f"+{phone}")
            st.success("📩 Notification sent successfully!")
        except Exception as e:
            st.warning(f"⚠️ SMS/WhatsApp not sent: {e}")
    else:
        st.info(f"ℹ️ Twilio not configured. Simulated notification:\nTo: {phone}\nMessage: {msg}")

# --- Utilities ---
def generate_booking_ref(appt_id):
    return f"APPT-{datetime.now().strftime('%Y%m%d')}-{appt_id:03d}"

def insert_appointment(patient_name, phone, department, doctor, appt_date, clinic_id=1):
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""INSERT INTO appointments 
                 (patient_name, phone, department, doctor, date, status, created_at, updated_at, clinic_id) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (patient_name, phone, department, doctor, str(appt_date), "pending", created_at, created_at, clinic_id))
    conn.commit()
    appt_id = c.lastrowid
    ref = generate_booking_ref(appt_id)
    c.execute("UPDATE appointments SET booking_ref=? WHERE id=?", (ref, appt_id))
    conn.commit()
    return appt_id, ref

# --- App Layout ---
st.title("🏥 Kisumu County Referral Hospital")

menu = ["Book Appointment", "Check Appointment Status", "Staff Login"]
choice = st.sidebar.selectbox("Menu", menu)

# --- Patient Side: Booking ---
if choice == "Book Appointment":
    st.subheader("📌 Patient Appointment Booking")
    with st.form("booking_form"):
        patient_name = st.text_input("Patient Name")
        phone = st.text_input("Phone Number")
        department = st.selectbox("Department", ["OPD", "MCH/FP", "Dental", "Surgery", "Orthopedics", "Eye"])
        doctor = st.text_input("Doctor (optional)")
        date_ = st.date_input("Preferred Date", min_value=date.today())
        submit = st.form_submit_button("Book Appointment")

        if submit:
            if not patient_name.strip():
                st.warning("Please enter patient name.")
            elif not phone.strip():
                st.warning("Please enter phone number.")
            else:
                appt_id, ref = insert_appointment(patient_name.strip(), phone.strip(), department, doctor.strip(), date_)
                st.success(f"✅ Appointment booked for {patient_name} on {date_}")
                st.info(f"📌 Your Booking Reference: **{ref}**")
                send_sms(phone.strip(), f"Hello {patient_name}, your appointment for {date_} is received. Reference: {ref}")

# --- Patient Side: Check Status ---
elif choice == "Check Appointment Status":
    st.subheader("🔍 Check Appointment Status")
    st.write("Enter your booking reference (e.g. APPT-20250923-001) or your phone number to find your appointment.")
    query = st.text_input("Reference or phone")
    if st.button("Check Status"):
        if not query.strip():
            st.warning("Please enter a reference or phone number.")
        else:
            q = query.strip()
            row = c.execute("SELECT id, patient_name, department, date, status, booking_ref, phone FROM appointments WHERE booking_ref=?", (q,)).fetchone()
            if not row:
                rows = c.execute("SELECT id, patient_name, department, date, status, booking_ref, phone FROM appointments WHERE phone LIKE ?", (f"%{q}%",)).fetchall()
                if not rows:
                    st.error("No appointment found with that reference or phone.")
                elif len(rows) == 1:
                    r = rows[0]
                    st.success(f"👤 Patient: {r[1]}")
                    st.info(f"🏥 Department: {r[2]} | 📅 Date: {r[3]} | Ref: {r[5]}")
                    status = r[4]
                    if status == "pending":
                        st.warning("⏳ Status: Pending (waiting for confirmation)")
                    elif status == "confirmed":
                        st.success("✅ Status: Confirmed")
                    elif status == "cancelled":
                        st.error("❌ Status: Cancelled")
                else:
                    st.info("Multiple appointments found for this phone number:")
                    dfhits = pd.DataFrame(rows, columns=["id", "patient_name", "department", "date", "status", "booking_ref", "phone"])
                    st.dataframe(dfhits)
            else:
                r = row
                st.success(f"👤 Patient: {r[1]}")
                st.info(f"🏥 Department: {r[2]} | 📅 Date: {r[3]} | Ref: {r[5]}")
                status = r[4]
                if status == "pending":
                    st.warning("⏳ Status: Pending (waiting for confirmation)")
                elif status == "confirmed":
                    st.success("✅ Status: Confirmed")
                elif status == "cancelled":
                    st.error("❌ Status: Cancelled")

# --- Staff Side: Queue & Analytics ---
elif choice == "Staff Login":
    if not st.session_state["logged_in"]:
        manual_login()
    else:
        manual_logout()
        role = st.session_state["role"]

        st.subheader("📋 Manage Appointments (Queue)")
        df = pd.read_sql("SELECT * FROM appointments ORDER BY created_at DESC", conn)

        if not df.empty:
            for i, row in df.iterrows():
                st.write(f"📌 {row['patient_name']} | {row['department']} | {row['date']} | Status: {row['status']} | Ref: {row.get('booking_ref', '')}")
                cols = st.columns([1,1,1])
                with cols[0]:
                    if st.button("Confirm", key=f"confirm{row['id']}"):
                        c.execute("UPDATE appointments SET status=?, updated_at=? WHERE id=?",
                                  ("confirmed", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row['id']))
                        conn.commit()
                        send_sms(row['phone'], f"Your appointment ({row.get('booking_ref','')}) is confirmed for {row['date']}.")
                        st.success(f"✅ Confirmed appointment {row['id']}")
                        st.rerun()   # fixed
                with cols[1]:
                    if st.button("Cancel", key=f"cancel{row['id']}"):
                        c.execute("UPDATE appointments SET status=?, updated_at=? WHERE id=?",
                                  ("cancelled", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row['id']))
                        conn.commit()
                        send_sms(row['phone'], f"Your appointment ({row.get('booking_ref','')}) has been cancelled.")
                        st.warning(f"❌ Cancelled appointment {row['id']}")
                        st.rerun()   # fixed
                with cols[2]:
                    st.write("")  # reserved for future actions
        else:
            st.info("No appointments yet.")

        if role == "admin":
            st.subheader("📊 Analytics Dashboard")
            if not df.empty:
                fig = px.histogram(df, x="department", color="status", title="Appointments by Department")
                st.plotly_chart(fig)
                fig2 = px.histogram(df, x="date", color="status", title="Appointments over Time")
                st.plotly_chart(fig2)
            else:
                st.info("No data for analytics yet.")

