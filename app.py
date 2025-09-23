import os
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date
import plotly.express as px
import hashlib
from twilio.rest import Client

# ==========================
# --- DATABASE SETUP ---
# ==========================
DB_PATH = "kisumu_hospital.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
c = conn.cursor()

# --- Tables for users & appointments (existing) ---
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
              clinic_id INTEGER,
              booking_ref TEXT,
              notification_sent INTEGER DEFAULT 0,
              telemedicine_link TEXT,
              insurance_verified INTEGER DEFAULT 0)''')
conn.commit()

# ==========================
# --- HELPER FUNCTIONS ---
# ==========================
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_booking_ref(appt_id):
    return f"APPT-{datetime.now().strftime('%Y%m%d')}-{appt_id:03d}"

# --- Twilio Setup ---
try:
    account_sid = st.secrets["TWILIO_ACCOUNT_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]
    twilio_number = st.secrets["TWILIO_PHONE"]
except Exception:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_number = os.getenv("TWILIO_PHONE", "")

def send_notification(phone, msg):
    """Send SMS/WhatsApp if configured"""
    if account_sid and auth_token and twilio_number:
        client = Client(account_sid, auth_token)
        try:
            if "whatsapp" in twilio_number.lower():
                client.messages.create(body=msg, from_=twilio_number, to=f"whatsapp:+{phone}")
            else:
                client.messages.create(body=msg, from_=twilio_number, to=f"+{phone}")
        except Exception as e:
            st.warning(f"⚠️ SMS/WhatsApp not sent: {e}")
    else:
        st.info(f"ℹ️ Simulated notification:\nTo: {phone}\nMessage: {msg}")

# ==========================
# --- SESSION STATE ---
# ==========================
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = None
    st.session_state["role"] = None
    st.session_state["language"] = "en"  # Multi-language support placeholder

# ==========================
# --- AUTHENTICATION ---
# ==========================
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
            st.rerun()
        else:
            st.error("Username/Password is incorrect")

def manual_logout():
    if st.sidebar.button("Logout"):
        st.session_state["logged_in"] = False
        st.session_state["username"] = None
        st.session_state["role"] = None
        st.rerun()

# ==========================
# --- APPOINTMENT INSERTION ---
# ==========================
def insert_appointment(patient_name, phone, department, doctor, appt_date, clinic_id=1):
    """Insert appointment and generate booking ref + optional telemedicine"""
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""INSERT INTO appointments 
                 (patient_name, phone, department, doctor, date, status, created_at, updated_at, clinic_id) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (patient_name, phone, department, doctor, str(appt_date), "pending", created_at, created_at, clinic_id))
    conn.commit()
    appt_id = c.lastrowid
    ref = generate_booking_ref(appt_id)
    tele_link = f"https://telemed.example.com/{ref}"  # Placeholder for telemedicine
    c.execute("UPDATE appointments SET booking_ref=?, telemedicine_link=? WHERE id=?", (ref, tele_link, appt_id))
    conn.commit()
    return appt_id, ref, tele_link

# ==========================
# --- APP LAYOUT ---
# ==========================
st.title("🏥 Kisumu County Referral Hospital")

menu = ["Book Appointment", "Check Appointment Status", "Staff Login"]
choice = st.sidebar.selectbox("Menu", menu)

# --------------------------
# --- PATIENT SIDE: BOOKING ---
# --------------------------
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
            if not patient_name.strip() or not phone.strip():
                st.warning("Please fill all required fields.")
            else:
                appt_id, ref, tele_link = insert_appointment(patient_name.strip(), phone.strip(), department, doctor.strip(), date_)
                st.success(f"✅ Appointment booked for {patient_name} on {date_}")
                st.info(f"📌 Your Booking Reference: **{ref}**")
                st.info(f"💻 Telemedicine link (if applicable): {tele_link}")
                send_notification(phone.strip(), f"Hello {patient_name}, your appointment for {date_} is received. Ref: {ref}")

# --------------------------
# --- PATIENT SIDE: STATUS ---
# --------------------------
elif choice == "Check Appointment Status":
    st.subheader("🔍 Check Appointment Status")
    query = st.text_input("Reference or phone")
    if st.button("Check Status"):
        if not query.strip():
            st.warning("Please enter a reference or phone number.")
        else:
            q = query.strip()
            row = c.execute("SELECT * FROM appointments WHERE booking_ref=? OR phone LIKE ?", (q, f"%{q}%")).fetchone()
            if row:
                st.success(f"👤 Patient: {row[1]}")
                st.info(f"🏥 Dept: {row[3]} | 📅 Date: {row[5]} | Ref: {row[10]} | Telemedicine: {row[13]}")
                st.info(f"Status: {row[6]}")
            else:
                st.error("No appointment found.")

# --------------------------
# --- STAFF SIDE: QUEUE & ANALYTICS ---
# --------------------------
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
                st.write(f"📌 {row['patient_name']} | {row['department']} | {row['date']} | Status: {row['status']} | Ref: {row['booking_ref']}")
                cols = st.columns([1,1,1])
                with cols[0]:
                    if st.button("Confirm", key=f"confirm{row['id']}"):
                        c.execute("UPDATE appointments SET status=?, updated_at=? WHERE id=?",
                                  ("confirmed", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row['id']))
                        conn.commit()
                        send_notification(row['phone'], f"Your appointment ({row['booking_ref']}) is confirmed for {row['date']}.")
                        st.rerun()
                with cols[1]:
                    if st.button("Cancel", key=f"cancel{row['id']}"):
                        c.execute("UPDATE appointments SET status=?, updated_at=? WHERE id=?",
                                  ("cancelled", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row['id']))
                        conn.commit()
                        send_notification(row['phone'], f"Your appointment ({row['booking_ref']}) has been cancelled.")
                        st.rerun()
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

# ==========================
# --- FUTURE FEATURES PLACEHOLDERS ---
# ==========================
"""
1️⃣ Real-time database: Replace SQLite with PostgreSQL or Firebase for live updates.
2️⃣ Multi-language support: Integrate i18n for patient-facing UI.
3️⃣ EHR integration: Use FHIR/HL7 APIs to sync patient records automatically.
4️⃣ Telemedicine: Integrate video consultation APIs.
5️⃣ Insurance: API or admin input for coverage verification and co-pay automation.
6️⃣ Notifications: Push notifications (Firebase) alongside SMS/WhatsApp.
"""
