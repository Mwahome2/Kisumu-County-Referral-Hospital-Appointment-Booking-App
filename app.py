import os
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date, timedelta
import plotly.express as px
import hashlib
from twilio.rest import Client

# ==========================
# --- DATABASE SETUP ---
# ==========================
DB_PATH = "kisumu_hospital.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row  # allows dictionary-style access
c = conn.cursor()

# --- Base tables ---
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
              stage TEXT DEFAULT 'pending',
              created_at TEXT,
              updated_at TEXT,
              clinic_id INTEGER,
              booking_ref TEXT,
              telemedicine_link TEXT,
              notification_sent INTEGER DEFAULT 0,
              insurance_verified INTEGER DEFAULT 0)''')
conn.commit()

# --- Ensure columns exist (for older DBs) ---
def ensure_column_exists(table, column_name, column_def):
    info = c.execute(f"PRAGMA table_info({table})").fetchall()
    columns = [row[1] for row in info]
    if column_name not in columns:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_def}")
        conn.commit()

ensure_column_exists("appointments", "telemedicine_link", "TEXT")
ensure_column_exists("appointments", "notification_sent", "INTEGER DEFAULT 0")
ensure_column_exists("appointments", "insurance_verified", "INTEGER DEFAULT 0")
ensure_column_exists("appointments", "clinic_id", "INTEGER DEFAULT 1")
ensure_column_exists("appointments", "booking_ref", "TEXT")
ensure_column_exists("appointments", "stage", "TEXT DEFAULT 'pending'")

# ==========================
# --- MULTI-LANGUAGE SUPPORT ---
# ==========================
languages = {
    "en": {
        "title": "🏥 Kisumu County Referral Hospital",
        "menu": ["Book Appointment", "Check Appointment Status", "Staff Login"],
        "patient_booking": "📌 Patient Appointment Booking",
        "patient_name": "Patient Name",
        "phone_number": "Phone Number",
        "department": "Department",
        "doctor": "Doctor (optional)",
        "preferred_date": "Preferred Date",
        "book_btn": "Book Appointment",
        "booking_success": "✅ Appointment booked for {name} on {date}",
        "booking_ref": "📌 Your Booking Reference: {ref}",
        "telemedicine": "💻 Telemedicine link (if applicable): {link}",
        "check_status": "🔍 Check Appointment Status",
        "enter_ref_phone": "Enter your booking reference or phone number",
        "no_appt_found": "No appointment found.",
        "status_pending": "⏳ Status: Pending (waiting for confirmation)",
        "status_confirmed": "✅ Status: Confirmed",
        "status_cancelled": "❌ Status: Cancelled",
        "staff_manage": "📋 Manage Appointments (Queue)",
        "analytics": "📊 Analytics Dashboard",
        "stage_label": "Stage",
        "update_stage": "Update Stage",
        "stages": ["pending", "confirmed", "in consultation", "done"]
    },
    "sw": {
        "title": "🏥 Hospitali Kuu ya Rufaa ya Kaunti ya Kisumu",
        "menu": ["Weka Miadi", "Angalia Hali ya Miadi", "Ingia Staff"],
        "patient_booking": "📌 Weka Miadi ya Mgonjwa",
        "patient_name": "Jina la Mgonjwa",
        "phone_number": "Namba ya Simu",
        "department": "Idara",
        "doctor": "Daktari (hiari)",
        "preferred_date": "Tarehe Uliyoipendelea",
        "book_btn": "Weka Miadi",
        "booking_success": "✅ Miadi imewekwa kwa {name} mnamo {date}",
        "booking_ref": "📌 Kumbukumbu ya Miadi Yako: {ref}",
        "telemedicine": "💻 Kiungo cha Telemedicine (ikiwa kinapatikana): {link}",
        "check_status": "🔍 Angalia Hali ya Miadi",
        "enter_ref_phone": "Weka kumbukumbu ya miadi au namba ya simu",
        "no_appt_found": "Hakuna miadi iliyopatikana.",
        "status_pending": "⏳ Hali: Inasubiri uthibitisho",
        "status_confirmed": "✅ Hali: Imethibitishwa",
        "status_cancelled": "❌ Hali: Imefutwa",
        "staff_manage": "📋 Dhibiti Miadi (Orodha ya Wateja)",
        "analytics": "📊 Dashibodi ya Takwimu",
        "stage_label": "Kipindi cha huduma",
        "update_stage": "Sasisha Kipindi",
        "stages": ["pending", "confirmed", "in consultation", "done"]
    }
}

st.sidebar.title("🌐 Language / Lugha")
st.session_state["language"] = st.sidebar.selectbox(
    "Choose Language / Chagua Lugha", ["en", "sw"], index=0
)
lang = st.session_state["language"]
t = languages[lang]

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
# --- ADMIN CHECK ---
# ==========================
admin_check = c.execute("SELECT * FROM users WHERE username=?", ("admin",)).fetchone()
if not admin_check:
    c.execute("INSERT INTO users (username, password_hash, role, department) VALUES (?, ?, ?, ?)",
              ("admin", hash_password("admin123"), "admin", "ALL"))
    conn.commit()

# ==========================
# --- SESSION STATE ---
# ==========================
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = None
    st.session_state["role"] = None

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
            st.session_state["role"] = row["role"]
            st.success(f"✅ Logged in as {uname} ({row['role']})")
            st.experimental_rerun()
        else:
            st.error("Username/Password is incorrect")

def manual_logout():
    if st.sidebar.button("Logout"):
        st.session_state["logged_in"] = False
        st.session_state["username"] = None
        st.session_state["role"] = None
        st.experimental_rerun()

# ==========================
# --- APPOINTMENT INSERTION ---
# ==========================
def insert_appointment(patient_name, phone, department, doctor, appt_date, clinic_id=1):
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""INSERT INTO appointments 
                 (patient_name, phone, department, doctor, date, status, stage, created_at, updated_at, clinic_id) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (patient_name, phone, department, doctor, str(appt_date), "pending", "pending", created_at, created_at, clinic_id))
    conn.commit()
    appt_id = c.lastrowid
    ref = generate_booking_ref(appt_id)
    tele_link = f"https://telemed.example.com/{ref}"
    c.execute("""UPDATE appointments 
                 SET booking_ref=?, telemedicine_link=?, updated_at=? 
                 WHERE id=?""",
              (ref, tele_link, created_at, appt_id))
    conn.commit()
    msg = f"Hello {patient_name}, your appointment for {appt_date} is received. Reference: {ref}. Telemedicine link: {tele_link}"
    send_notification(phone, msg)
    c.execute("UPDATE appointments SET notification_sent=? WHERE id=?", (1, appt_id))
    conn.commit()
    return appt_id, ref, tele_link

# ==========================
# --- APP LAYOUT ---
# ==========================
st.title(t["title"])
menu_choice = st.sidebar.selectbox("Menu", t["menu"])

# --- PATIENT BOOKING ---
if menu_choice == t["menu"][0]:
    st.subheader(t["patient_booking"])
    with st.form("booking_form"):
        patient_name = st.text_input(t["patient_name"])
        phone = st.text_input(t["phone_number"])
        department = st.selectbox(t["department"], ["OPD", "MCH/FP", "Dental", "Surgery", "Orthopedics", "Eye"])
        doctor = st.text_input(t["doctor"])
        date_ = st.date_input(t["preferred_date"], min_value=date.today())
        submit = st.form_submit_button(t["book_btn"])
        if submit:
            if not patient_name.strip() or not phone.strip():
                st.warning("Please fill all required fields.")
            else:
                appt_id, ref, tele_link = insert_appointment(patient_name.strip(), phone.strip(), department, doctor.strip(), date_)
                st.success(t["booking_success"].format(name=patient_name, date=date_))
                st.info(t["booking_ref"].format(ref=ref))
                st.info(t["telemedicine"].format(link=tele_link))

# --- PATIENT STATUS CHECK ---
elif menu_choice == t["menu"][1]:
    st.subheader(t["check_status"])
    query = st.text_input(t["enter_ref_phone"])
    if st.button("Check Status"):
        if not query.strip():
            st.warning("Please enter a reference or phone number.")
        else:
            q = query.strip()
            row = c.execute("SELECT * FROM appointments WHERE booking_ref=? OR phone LIKE ?", (q, f"%{q}%")).fetchone()
            if row:
                st.success(f"👤 Patient: {row['patient_name']}")
                st.info(f"🏥 Dept: {row['department']} | 📅 Date: {row['date']} | Ref: {row['booking_ref']} | Telemedicine: {row['telemedicine_link']}")
                status_text = {"pending": t["status_pending"], "confirmed": t["status_confirmed"], "cancelled": t["status_cancelled"]}
                st.info(status_text.get(row["status"], row["status"]))
            else:
                st.error(t["no_appt_found"])

# --- STAFF / ADMIN DASHBOARD ---
elif menu_choice == t["menu"][2]:
    if not st.session_state["logged_in"]:
        manual_login()
    else:
        manual_logout()
        st.subheader(f"👤 Welcome, {st.session_state['username']}")
        df = pd.read_sql("SELECT * FROM appointments ORDER BY created_at DESC", conn)

        # Staff Panel Menu
        staff_menu = st.sidebar.radio("Staff Panel", ["Manage Appointments", "Analytics", "Search / Filter", "Export Data"])

        if staff_menu == "Manage Appointments":
            st.subheader("📋 Manage Appointments (Queue)")
            if not df.empty:
                rerun_flag = False
                for i, row in df.iterrows():
                    st.write(f"📌 {row['patient_name']} | {row['department']} | {row['date']} | Status: {row['status']} | Stage: {row['stage']} | Ref: {row['booking_ref']}")
                    cols = st.columns([1,1,1])
                    with cols[0]:
                        if st.button("Confirm", key=f"confirm{row['id']}"):
                            c.execute("UPDATE appointments SET status=?, stage=?, updated_at=? WHERE id=?",
                                      ("confirmed", "confirmed", datetime.now().strftime('%Y-%m-%d %H:%M:%S'), row['id']))
                            conn.commit()
                            send_notification(row['phone'], f"Your appointment ({row['booking_ref']}) is confirmed for {row['date']}")
                            st.success(f"✅ Confirmed appointment {row['id']}")
                            rerun_flag = True
                    with cols[1]:
                        if st.button("Cancel", key=f"cancel{row['id']}"):
                            c.execute("UPDATE appointments SET status=?, stage=?, updated_at=? WHERE id=?",
                                      ("cancelled", "cancelled", datetime.now().strftime('%Y-%m-%d %H:%M:%S'), row['id']))
                            conn.commit()
                            send_notification(row['phone'], f"Your appointment ({row['booking_ref']}) has been cancelled.")
                            st.warning(f"❌ Cancelled appointment {row['id']}")
                            rerun_flag = True
                    with cols[2]:
                        new_stage = st.selectbox(t["update_stage"], t["stages"], index=t["stages"].index(row['stage']), key=f"stage{row['id']}")
                        if st.button(f"Update Stage", key=f"updatestage{row['id']}"):
                            c.execute("UPDATE appointments SET stage=?, updated_at=? WHERE id=?",
                                      (new_stage, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), row['id']))
                            conn.commit()
                            st.success(f"✅ Updated stage for {row['patient_name']} to {new_stage}")
                            rerun_flag = True
                if rerun_flag:
                    st.experimental_rerun()

        elif staff_menu == "Analytics":
            st.subheader("📊 Analytics Dashboard")
            today = date.today()
            week_start = today - timedelta(days=today.weekday())
            month_start = today.replace(day=1)
            
            df['date_dt'] = pd.to_datetime(df['date'])
            total_today = len(df[df['date_dt'].dt.date == today])
            total_week = len(df[(df['date_dt'].dt.date >= week_start) & (df['date_dt'].dt.date <= today)])
            total_month = len(df[(df['date_dt'].dt.date >= month_start) & (df['date_dt'].dt.date <= today)])
            
            st.info(f"Total Appointments Today: {total_today}")
            st.info(f"Total Appointments This Week: {total_week}")
            st.info(f"Total Appointments This Month: {total_month}")
            
            st.info(f"Pending: {len(df[df['status']=='pending'])} | Confirmed: {len(df[df['status']=='confirmed'])} | Cancelled: {len(df[df['status']=='cancelled'])}")
            
            st.bar_chart(df['department'].value_counts())
            st.bar_chart(df['stage'].value_counts())

        elif staff_menu == "Search / Filter":
            st.subheader("🔍 Search / Filter Appointments")
            dept_filter = st.selectbox("Department", ["All"] + df['department'].unique().tolist())
            status_filter = st.selectbox("Status", ["All", "pending", "confirmed", "cancelled"])
            filtered = df
            if dept_filter != "All":
                filtered = filtered[filtered['department'] == dept_filter]
            if status_filter != "All":
                filtered = filtered[filtered['status'] == status_filter]
            st.dataframe(filtered)

        elif staff_menu == "Export Data":
            st.subheader("💾 Export Appointments Data")
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("Download CSV", data=csv, file_name='appointments.csv', mime='text/csv')

