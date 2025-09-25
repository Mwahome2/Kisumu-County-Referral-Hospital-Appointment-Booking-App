# app.py
import os
import io
import requests
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date, timedelta, time as dtime
import hashlib
from twilio.rest import Client
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import threading
import uvicorn

# ==========================
# --- FASTAPI API ---
# ==========================
api = FastAPI()

@api.post("/api/book")
async def api_book(request: Request):
    """
    API to create an appointment booking.
    Expects JSON: { "patient_name": "John Doe", "phone": "2547...", "department": "OPD", "doctor": "Dr. A", "date": "2025-09-28", "time": "09:00" }
    """
    try:
        data = await request.json()
        name = data.get("patient_name", "").strip()
        phone = data.get("phone", "").strip()
        dept = data.get("department", "").strip()
        doctor = data.get("doctor", "").strip()
        appt_date = data.get("date")
        appt_time = data.get("time")

        if not name or not phone or not dept or not appt_date or not appt_time:
            return JSONResponse({"success": False, "error": "Missing required fields"}, status_code=400)

        # Insert appointment using your existing helper
        appt_id, ref, ticket, tele_link = insert_appointment(
            name, phone, dept, doctor, appt_date, appt_time
        )

        return JSONResponse({
            "success": True,
            "appointment_id": appt_id,
            "booking_ref": ref,
            "ticket_number": ticket,
            "telemedicine_link": tele_link
        })

    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

# ==========================
# --- PAGE CONFIG (MUST BE FIRST) ---
# ==========================
st.set_page_config(page_title="🏥 Kisumu Hospital Appointments", layout="wide")

# ==========================
# --- DATABASE SETUP ---
# ==========================
DB_PATH = "kisumu_hospital.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# create main tables and columns (preserve everything + new columns time & ticket_number)
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
              time TEXT,
              status TEXT,
              stage TEXT DEFAULT 'pending',
              created_at TEXT,
              updated_at TEXT,
              clinic_id INTEGER,
              booking_ref TEXT,
              ticket_number TEXT,
              telemedicine_link TEXT,
              notification_sent INTEGER DEFAULT 0,
              insurance_verified INTEGER DEFAULT 0,
              notes TEXT,
              cancel_reason TEXT)''')
conn.commit()

# table to record queue sync attempts (so queue can be reconciled if API fails)
c.execute('''CREATE TABLE IF NOT EXISTS queue_sync
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
              appointment_id INTEGER,
              patient_name TEXT,
              ticket TEXT,
              department TEXT,
              booking_ref TEXT,
              status TEXT DEFAULT 'pending',
              created_at TEXT)''')
conn.commit()

# helper to add missing columns in older DBs
def ensure_column_exists(table, column_name, column_def):
    info = c.execute(f"PRAGMA table_info({table})").fetchall()
    columns = [row[1] for row in info]
    if column_name not in columns:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_def}")
        conn.commit()

# ensure older DBs get new columns
ensure_column_exists("appointments", "telemedicine_link", "TEXT")
ensure_column_exists("appointments", "notification_sent", "INTEGER DEFAULT 0")
ensure_column_exists("appointments", "insurance_verified", "INTEGER DEFAULT 0")
ensure_column_exists("appointments", "clinic_id", "INTEGER DEFAULT 1")
ensure_column_exists("appointments", "booking_ref", "TEXT")
ensure_column_exists("appointments", "ticket_number", "TEXT")
ensure_column_exists("appointments", "stage", "TEXT DEFAULT 'pending'")
ensure_column_exists("appointments", "notes", "TEXT")
ensure_column_exists("appointments", "cancel_reason", "TEXT")
ensure_column_exists("appointments", "time", "TEXT")

# ==========================
# --- LOCALIZATION TEXT ---
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
        "preferred_time": "Preferred Time",
        "book_btn": "Book Appointment",
        "booking_success": "✅ Appointment booked for {name} on {date} at {time}",
        "booking_ref": "📌 Your Booking Reference: {ref}",
        "ticket_number": "🎟️ Your Ticket Number: {ticket}",
        "telemedicine": "💻 Telemedicine link (if applicable): {link}",
        "check_status": "🔍 Check Appointment Status",
        "enter_ref_phone": "Enter your booking reference or phone number",
        "no_appt_found": "No appointment found.",
        "status_pending": "⏳ Status: Pending",
        "status_confirmed": "✅ Status: Confirmed",
        "status_cancelled": "❌ Status: Cancelled",
        "staff_manage": "📋 Manage Appointments (Queue)",
        "analytics": "📊 Analytics Dashboard",
        "stage_label": "Stage",
        "update_stage": "Update Stage",
        "stages": ["pending", "confirmed", "in consultation", "done"],
        # extras
        "confirm_btn": "Confirm",
        "cancel_btn": "Cancel",
        "cancel_reason": "Cancel Reason (optional)",
        "edit_btn": "Edit",
        "reschedule_btn": "Reschedule",
        "send_reminder_btn": "Send Reminder",
        "notes_label": "Staff Notes",
        "save_notes_btn": "Save Note",
        "delete_btn": "Delete",
        "delete_confirm": "Confirm delete — this is permanent.",
        "now_serving": "Now Serving",
        "next_patient": "Next Patient",
        "skip_patient": "Skip",
        "recall_patient": "Recall",
        "search_placeholder": "Search by name, phone, or ref",
        "export_csv": "Download CSV",
        "export_excel": "Download Excel",
        "edit_save": "Save Changes",
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
        "preferred_time": "Muda Uliyochagua",
        "book_btn": "Weka Miadi",
        "booking_success": "✅ Miadi imewekwa kwa {name} mnamo {date} saa {time}",
        "booking_ref": "📌 Kumbukumbu ya Miadi Yako: {ref}",
        "ticket_number": "🎟️ Namba Yako ya Tiketi: {ticket}",
        "telemedicine": "💻 Kiungo cha Telemedicine (ikiwa kinapatikana): {link}",
        "check_status": "🔍 Angalia Hali ya Miadi",
        "enter_ref_phone": "Weka kumbukumbu ya miadi au namba ya simu",
        "no_appt_found": "Hakuna miadi iliyopatikana.",
        "status_pending": "⏳ Hali: Inasubiri",
        "status_confirmed": "✅ Hali: Imethibitishwa",
        "status_cancelled": "❌ Hali: Imefutwa",
        "staff_manage": "📋 Dhibiti Miadi (Orodha ya Wateja)",
        "analytics": "📊 Dashibodi ya Takwimu",
        "stage_label": "Kipindi",
        "update_stage": "Sasisha Kipindi",
        "stages": ["pending", "confirmed", "in consultation", "done"],
        # extras
        "confirm_btn": "Thibitisha",
        "cancel_btn": "Ghairi",
        "cancel_reason": "Sababu ya kughairi (hiari)",
        "edit_btn": "Hariri",
        "reschedule_btn": "Panga upya",
        "send_reminder_btn": "Tuma Kumbusho",
        "notes_label": "Maelezo ya Wafanyakazi",
        "save_notes_btn": "Hifadhi Kumbukumbu",
        "delete_btn": "Futa",
        "delete_confirm": "Thibitisha kufuta — hii ni ya kudumu.",
        "now_serving": "Inahudumiwa sasa",
        "next_patient": "Mgonjwa Ifuatayo",
        "skip_patient": "Ruka",
        "recall_patient": "Rudia",
        "search_placeholder": "Tafuta kwa jina, simu, au kumbukumbu",
        "export_csv": "Pakua CSV",
        "export_excel": "Pakua Excel",
        "edit_save": "Hifadhi Mabadiliko",
    }
}

# language selector
st.sidebar.title("🌐 Language / Lugha")
if "language" not in st.session_state:
    st.session_state["language"] = "en"
st.session_state["language"] = st.sidebar.selectbox(
    "Choose Language / Chagua Lugha", ["en", "sw"], index=0 if st.session_state["language"] == "en" else 1
)
lang = st.session_state["language"]
t = languages[lang]

# ==========================
# --- TWILIO / NOTIFICATIONS ---
# ==========================
try:
    account_sid = st.secrets["TWILIO_ACCOUNT_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]
    twilio_number = st.secrets["TWILIO_PHONE"]
except Exception:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_number = os.getenv("TWILIO_PHONE", "")

def send_notification(phone, msg):
    """Send via Twilio if configured, otherwise show simulated info."""
    if account_sid and auth_token and twilio_number:
        try:
            client = Client(account_sid, auth_token)
            if "whatsapp" in twilio_number.lower():
                client.messages.create(body=msg, from_=twilio_number, to=f"whatsapp:+{phone}")
            else:
                client.messages.create(body=msg, from_=twilio_number, to=f"+{phone}")
        except Exception as e:
            st.warning(f"⚠️ SMS/WhatsApp not sent: {e}")
    else:
        st.info(f"ℹ️ Simulated notification:\nTo: {phone}\nMessage: {msg}")

# ==========================
# --- HELPERS & CRUD ---
# ==========================
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_booking_ref(appt_id):
    return f"APPT-{datetime.now().strftime('%Y%m%d')}-{appt_id:03d}"

def generate_ticket_number(appt_id):
    return f"TKT-{datetime.now().strftime('%Y%m%d')}-{appt_id:04d}"

def queue_api_add(patient_name, ticket, department, booking_ref):
    """
    Try to POST to the Smart Queue app API.
    If API fails, record in queue_sync table for later reconciliation.
    """
    endpoint = st.secrets.get("SMART_QUEUE_API") if "SMART_QUEUE_API" in st.secrets else os.getenv("SMART_QUEUE_API_URL", "https://smart-queue-system-management-ignquprgpzmjvjjhtzzpwm.streamlit.app/api/add_ticket")
    payload = {"name": patient_name, "ticket": ticket, "department": department, "booking_ref": booking_ref}
    try:
        resp = requests.post(endpoint, json=payload, timeout=5)
        if resp.status_code == 200:
            return True
        else:
            # record pending sync
            c.execute("INSERT INTO queue_sync (appointment_id, patient_name, ticket, department, booking_ref, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (None, patient_name, ticket, department, booking_ref, "failed", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            st.warning(f"Queue API responded {resp.status_code}. Saved sync for later.")
            return False
    except Exception as e:
        # store to queue_sync for later retry
        c.execute("INSERT INTO queue_sync (appointment_id, patient_name, ticket, department, booking_ref, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (None, patient_name, ticket, department, booking_ref, "pending", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        st.info("Queue sync failed; saved locally for retry.")
        return False

def insert_appointment(patient_name, phone, department, doctor, appt_date, appt_time, clinic_id=1):
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # store date and time separately, keep backward-compatible fields too
    c.execute("""INSERT INTO appointments 
                 (patient_name, phone, department, doctor, date, time, status, stage, created_at, updated_at, clinic_id) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (patient_name, phone, department, doctor, str(appt_date), str(appt_time), "pending", "pending", created_at, created_at, clinic_id))
    conn.commit()
    appt_id = c.lastrowid
    ref = generate_booking_ref(appt_id)
    ticket = generate_ticket_number(appt_id)
    tele_link = f"https://telemed.example.com/{ref}"
    c.execute("""UPDATE appointments 
                 SET booking_ref=?, ticket_number=?, telemedicine_link=?, updated_at=? 
                 WHERE id=?""",
              (ref, ticket, tele_link, created_at, appt_id))
    conn.commit()

    # notify patient
    msg = f"Hello {patient_name}, your appointment for {appt_date} at {appt_time} is received.\nReference: {ref}\nTicket: {ticket}\nTelemedicine: {tele_link}"
    send_notification(phone, msg)
    c.execute("UPDATE appointments SET notification_sent=? WHERE id=?", (1, appt_id))
    conn.commit()

    # Try to add to Smart Queue (API). If fails, recorded to queue_sync table.
    queue_api_add(patient_name, ticket, department, ref)

    return appt_id, ref, ticket, tele_link

def get_appointments_df():
    df = pd.read_sql("SELECT * FROM appointments ORDER BY date ASC, time ASC, created_at ASC", conn)
    if not df.empty:
        # try combine date + time to datetime
        try:
            # ensure both strings exist
            df['time'] = df['time'].fillna("")
            df['date_dt'] = pd.to_datetime(df['date'].astype(str) + " " + df['time'].astype(str), errors='coerce')
        except Exception:
            df['date_dt'] = pd.to_datetime(df['date'], errors='coerce')
    return df

def update_appointment_field(appt_id, field, value):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # protect against SQL injection in field name by allowing only expected columns:
    allowed = {"patient_name","phone","department","doctor","date","time","status","stage","ticket_number","booking_ref","telemedicine_link","notes","cancel_reason"}
    if field not in allowed:
        raise ValueError("Invalid field update attempt")
    c.execute(f"UPDATE appointments SET {field}=?, updated_at=? WHERE id=?", (value, now, appt_id))
    conn.commit()

def delete_appointment(appt_id):
    c.execute("DELETE FROM appointments WHERE id=?", (appt_id,))
    conn.commit()

# ==========================
# --- ADMIN SEED & SESSION ---
# ==========================
admin_check = c.execute("SELECT * FROM users WHERE username=?", ("admin",)).fetchone()
if not admin_check:
    c.execute("INSERT INTO users (username, password_hash, role, department) VALUES (?, ?, ?, ?)",
              ("admin", hashlib.sha256("admin123".encode()).hexdigest(), "admin", "ALL"))
    conn.commit()

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = None
    st.session_state["role"] = None

if "now_serving_id" not in st.session_state:
    st.session_state["now_serving_id"] = None

# ==========================
# --- AUTH UI ---
# ==========================
def manual_login():
    st.subheader("🔑 Staff Login")
    uname = st.text_input("Username", key="login_user")
    pwd = st.text_input("Password", type="password", key="login_pass")
    if st.button("Login", key="login_btn"):
        hashed = hash_password(pwd)
        row = c.execute("SELECT role FROM users WHERE username=? AND password_hash=?", (uname, hashed)).fetchone()
        if row:
            st.session_state["logged_in"] = True
            st.session_state["username"] = uname
            st.session_state["role"] = row["role"]
            st.success(f"✅ Logged in as {uname} ({row['role']})")
            st.rerun()
        else:
            st.error("Username/Password is incorrect")
    st.write("Quick admin login:")
    if st.button("Login as admin", key="quick_admin"):
        st.session_state["logged_in"] = True
        st.session_state["username"] = "admin"
        st.session_state["role"] = "admin"
        st.success("✅ Logged in as admin")
        st.rerun()

def manual_logout():
    if st.sidebar.button("Logout"):
        st.session_state["logged_in"] = False
        st.session_state["username"] = None
        st.session_state["role"] = None
        st.session_state["now_serving_id"] = None
        st.rerun()

# ==========================
# --- APP LAYOUT ---
# ==========================
st.title(t["title"])
menu_choice = st.sidebar.selectbox("Menu", t["menu"])

# show logged-in user on sidebar
if st.session_state["logged_in"]:
    st.sidebar.write(f"👤 {st.session_state['username']}")
    if st.sidebar.button("Logout", key="sidebar_logout"):
        manual_logout()

# --------------------------
# PATIENT BOOKING
# --------------------------
if menu_choice == t["menu"][0]:
    st.subheader(t["patient_booking"])
    with st.form("booking_form"):
        patient_name = st.text_input(t["patient_name"])
        phone = st.text_input(t["phone_number"])
        department = st.selectbox(t["department"], ["OPD", "MCH/FP", "Dental", "Surgery", "Orthopedics", "Eye"])
        doctor = st.text_input(t["doctor"])
        date_ = st.date_input(t["preferred_date"], min_value=date.today())
        time_ = st.time_input(t["preferred_time"], value=dtime(hour=9, minute=0))
        submit = st.form_submit_button(t["book_btn"])
        if submit:
            if not patient_name.strip() or not phone.strip():
                st.warning("Please fill all required fields.")
            else:
                appt_id, ref, ticket, tele_link = insert_appointment(
                    patient_name.strip(), phone.strip(), department, doctor.strip(), date_, time_
                )
                st.success(t["booking_success"].format(name=patient_name, date=date_, time=time_))
                st.info(t["booking_ref"].format(ref=ref))
                st.info(t["ticket_number"].format(ticket=ticket))
                st.info(t["telemedicine"].format(link=tele_link))

# --------------------------
# PATIENT STATUS CHECK
# --------------------------
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
                st.info(f"🏥 Dept: {row['department']} | 📅 Date: {row['date']} {row['time']} | Ref: {row['booking_ref']} | Ticket: {row['ticket_number']} | Telemedicine: {row['telemedicine_link']}")
                status_text = {"pending": t["status_pending"], "confirmed": t["status_confirmed"], "cancelled": t["status_cancelled"]}
                st.info(status_text.get(row["status"], row["status"]))
            else:
                st.error(t["no_appt_found"])

# --------------------------
# STAFF DASHBOARD
# --------------------------
elif menu_choice == t["menu"][2]:
    # require login
    if not st.session_state["logged_in"]:
        manual_login()
        st.stop()

    # header
    st.subheader(f"👤 Welcome, {st.session_state['username']}")
    st.header(t["staff_manage"])

    # fetch df
    df = get_appointments_df()

    # Staff Panel Menu
    staff_menu = st.sidebar.radio("Staff Panel", ["Manage Appointments", "Analytics", "Search / Filter", "Export Data"])

    # ---- Manage Appointments ----
    if staff_menu == "Manage Appointments":
        st.subheader("📋 Manage Appointments (Queue)")
        if df.empty:
            st.info("No appointments yet.")
        else:
            # Filters & search
            with st.expander("🔎 Search / Filter", expanded=True):
                col1, col2, col3, col4 = st.columns([3,2,2,2])
                with col1:
                    search_q = st.text_input(t["search_placeholder"], key="search_q")
                with col2:
                    date_from = st.date_input("From", value=date.today() - timedelta(days=7), key="filter_from")
                with col3:
                    date_to = st.date_input("To", value=date.today() + timedelta(days=30), key="filter_to")
                with col4:
                    dept_options = ["All"] + (sorted(df['department'].dropna().unique().tolist()) if not df.empty else [])
                    dept_filter = st.selectbox("Department", dept_options, key="filter_dept")
                    status_options = ["All"] + (sorted(df['status'].dropna().unique().tolist()) if not df.empty else [])
                    status_filter = st.selectbox("Status", status_options, key="filter_status")

            # apply filters
            filtered = df.copy()
            if not filtered.empty:
                if 'date_dt' in filtered:
                    filtered = filtered[(filtered['date_dt'].dt.date >= date_from) & (filtered['date_dt'].dt.date <= date_to)]
                if dept_filter != "All":
                    filtered = filtered[filtered['department'] == dept_filter]
                if status_filter != "All":
                    filtered = filtered[filtered['status'] == status_filter]
                if search_q and search_q.strip():
                    s = search_q.strip().lower()
                    filtered = filtered[filtered.apply(lambda r: s in str(r['patient_name']).lower() or s in str(r['phone']).lower() or s in str(r.get('booking_ref', '')).lower(), axis=1)]

            # Summary cards
            colA, colB, colC, colD = st.columns(4)
            total = len(df)
            today = date.today()
            total_today = int(len(df[df['date_dt'].dt.date == today])) if not df.empty and 'date_dt' in df else 0
            pending = int(len(df[df['status'] == 'pending'])) if not df.empty else 0
            confirmed = int(len(df[df['status'] == 'confirmed'])) if not df.empty else 0
            with colA:
                st.metric("Total Appointments", total)
            with colB:
                st.metric("Today", total_today)
            with colC:
                st.metric("Pending", pending)
            with colD:
                st.metric("Confirmed", confirmed)

            st.markdown("---")

            # Now Serving controls
            st.subheader(t["now_serving"])
            now_id = st.session_state.get("now_serving_id", None)
            if now_id is None and not df.empty:
                next_row = df[df['stage'].isin(['pending', 'confirmed'])].sort_values(['date_dt', 'created_at']).head(1)
                if not next_row.empty:
                    st.session_state["now_serving_id"] = int(next_row.iloc[0]['id'])
                    now_id = st.session_state["now_serving_id"]

            if now_id:
                current = c.execute("SELECT * FROM appointments WHERE id=?", (now_id,)).fetchone()
                if current:
                    # ---- START: SAFE HANDLING FOR `current` (fixed) ----
                    try:
                        # Try converting sqlite3.Row (or similar) to dict
                        rowd = dict(current)
                    except Exception:
                        try:
                            # pandas Series fallback
                            rowd = current.to_dict()
                        except Exception:
                            # last resort: attempt key access and build dict
                            rowd = {}
                            try:
                                # sqlite3.Row supports keys() in many envs
                                for k in current.keys():
                                    rowd[k] = current[k]
                            except Exception:
                                # give up and present minimal info
                                rowd = {}

                    # Use .get safely for all fields
                    patient_name_disp = rowd.get('patient_name', 'N/A')
                    department_disp = rowd.get('department', 'N/A')
                    date_disp = rowd.get('date', '')
                    time_disp = rowd.get('time', '')
                    booking_ref_disp = rowd.get('booking_ref', 'N/A')
                    stage_disp = rowd.get('stage', 'N/A')
                    ticket_disp = rowd.get('ticket_number', 'N/A')

                    cols_now = st.columns([3,1,1,1])
                    with cols_now[0]:
                        st.write(f"📌 {patient_name_disp} | {department_disp} | {date_disp} {time_disp} | Ref: {booking_ref_disp} | Stage: {stage_disp} | Ticket: {ticket_disp}")
                    # ---- END: SAFE HANDLING FOR `current` ----

                    with cols_now[1]:
                        if st.button(t["next_patient"], key=f"now_next_{now_id}"):
                            update_appointment_field(now_id, "stage", "done")
                            st.session_state["now_serving_id"] = None
                            st.success("Marked as done and moving to next.")
                            st.rerun()
                    with cols_now[2]:
                        if st.button(t["skip_patient"], key=f"now_skip_{now_id}"):
                            st.session_state["now_serving_id"] = None
                            st.success("Skipped. Next patient will be selected.")
                            st.rerun()
                    with cols_now[3]:
                        if st.button(t["recall_patient"], key=f"now_recall_{now_id}"):
                            # for recall we use direct current row data if available
                            try:
                                phone_to_call = rowd.get('phone', None) or current['phone']
                            except Exception:
                                phone_to_call = rowd.get('phone', None)
                            if phone_to_call:
                                send_notification(phone_to_call, f"Hello {patient_name_disp}, please proceed to the clinic. Ref: {booking_ref_disp}")
                            else:
                                # fallback: try to directly access
                                try:
                                    send_notification(current['phone'], f"Hello {patient_name_disp}, please proceed to the clinic. Ref: {booking_ref_disp}")
                                except Exception:
                                    st.warning("Unable to fetch phone to send recall.")
                            st.success("Recall/Reminder sent.")
            else:
                st.info("No patients currently in queue.")

            st.markdown("---")

            # Appointment list
            st.subheader("📋 Appointment List")
            for _, r in filtered.iterrows():
                appt_id = int(r['id'])
                header_label = f"📌 {r['patient_name']} | {r['department']} | {r['date']} {r['time']} | Status: {r['status']} | Stage: {r['stage']} | Ref: {r['booking_ref']} | Ticket: {r.get('ticket_number', '')}"
                with st.expander(header_label, expanded=False):
                    st.write(f"📱 Phone: {r['phone']} | Doctor: {r['doctor']} | Notes: {r['notes'] if r['notes'] else 'None'}")
                    # Action row
                    act_col1, act_col2, act_col3, act_col4, act_col5 = st.columns([1,1,1,1,1])

                    # Confirm
                    with act_col1:
                        if st.button(t["confirm_btn"], key=f"confirm_{appt_id}"):
                            update_appointment_field(appt_id, "status", "confirmed")
                            update_appointment_field(appt_id, "stage", "confirmed")
                            send_notification(r['phone'], f"Your appointment ({r['booking_ref']}) is confirmed for {r['date']} {r['time']}")
                            st.success("Appointment confirmed.")
                            st.rerun()

                    # Cancel (with reason)
                    with act_col2:
                        cancel_key = f"cancel_reason_{appt_id}"
                        cancel_reason = st.text_input(t["cancel_reason"], key=cancel_key)
                        if st.button(t["cancel_btn"], key=f"cancel_btn_{appt_id}"):
                            update_appointment_field(appt_id, "status", "cancelled")
                            update_appointment_field(appt_id, "stage", "cancelled")
                            update_appointment_field(appt_id, "cancel_reason", cancel_reason or "No reason provided")
                            send_notification(r['phone'], f"Your appointment ({r['booking_ref']}) has been cancelled. Reason: {cancel_reason or 'N/A'}")
                            st.warning("Appointment cancelled.")
                            st.rerun()

                    # Update stage
                    with act_col3:
                        stage_options = t["stages"]
                        try:
                            idx = stage_options.index(r['stage']) if r['stage'] in stage_options else 0
                        except Exception:
                            idx = 0
                        new_stage = st.selectbox(t["update_stage"], stage_options, index=idx, key=f"stage_sel_{appt_id}")
                        if st.button("🔄 Update Stage", key=f"upstage_btn_{appt_id}"):
                            update_appointment_field(appt_id, "stage", new_stage)
                            st.success("Stage updated.")
                            st.rerun()

                    # Send reminder
                    with act_col4:
                        if st.button(t["send_reminder_btn"], key=f"remind_btn_{appt_id}"):
                            send_notification(r['phone'], f"Reminder: Hello {r['patient_name']}, your appointment is on {r['date']} {r['time']}. Ref: {r['booking_ref']}, Ticket: {r.get('ticket_number','')}")
                            st.success("Reminder sent (or simulated).")

                    # Delete (two-step)
                    with act_col5:
                        confirm_flag_key = f"confirm_delete_{appt_id}"
                        if st.session_state.get(confirm_flag_key, False):
                            st.warning(t["delete_confirm"])
                            if st.button("Yes, delete", key=f"confirm_del_yes_{appt_id}"):
                                delete_appointment(appt_id)
                                send_notification(r['phone'], f"Your appointment ({r.get('booking_ref')}) was deleted by staff.")
                                st.success("Appointment deleted.")
                                st.session_state[confirm_flag_key] = False
                                st.rerun()
                            if st.button("Cancel", key=f"confirm_del_no_{appt_id}"):
                                st.session_state[confirm_flag_key] = False
                                st.info("Delete cancelled.")
                                st.rerun()
                        else:
                            if st.button(t["delete_btn"], key=f"del_btn_{appt_id}"):
                                st.session_state[confirm_flag_key] = True
                                st.rerun()

                    # Second row: Edit / Reschedule / Notes
                    er_col1, er_col2, er_col3 = st.columns([2,1,3])

                    # Edit (inline form)
                    with er_col1:
                        edit_flag = f"edit_mode_{appt_id}"
                        if st.session_state.get(edit_flag, False):
                            with st.form(f"edit_form_{appt_id}"):
                                e_name = st.text_input("Name", value=r['patient_name'], key=f"edit_name_{appt_id}")
                                e_phone = st.text_input("Phone", value=r['phone'], key=f"edit_phone_{appt_id}")
                                e_dept = st.text_input("Department", value=r['department'], key=f"edit_dept_{appt_id}")
                                e_doc = st.text_input("Doctor", value=r['doctor'], key=f"edit_doc_{appt_id}")
                                try:
                                    current_date_value = pd.to_datetime(r['date']).date()
                                except Exception:
                                    current_date_value = date.today()
                                try:
                                    current_time_value = pd.to_datetime(r['time']).time()
                                except Exception:
                                    current_time_value = dtime(hour=9, minute=0)
                                e_date = st.date_input("Date", value=current_date_value, key=f"edit_date_{appt_id}")
                                e_time = st.time_input("Time", value=current_time_value, key=f"edit_time_{appt_id}")
                                e_sub = st.form_submit_button(t["edit_save"], key=f"edit_save_{appt_id}")
                                if e_sub:
                                    c.execute("""UPDATE appointments SET patient_name=?, phone=?, department=?, doctor=?, date=?, time=?, updated_at=? WHERE id=?""",
                                              (e_name.strip(), e_phone.strip(), e_dept.strip(), e_doc.strip(), str(e_date), str(e_time), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), appt_id))
                                    conn.commit()
                                    st.success("Appointment updated.")
                                    st.session_state[edit_flag] = False
                                    st.rerun()
                            if st.button("Cancel Edit", key=f"cancel_edit_{appt_id}"):
                                st.session_state[edit_flag] = False
                                st.rerun()
                        else:
                            if st.button(t["edit_btn"], key=f"open_edit_{appt_id}"):
                                st.session_state[edit_flag] = True
                                st.rerun()

                    # Reschedule quick (date + time)
                    with er_col2:
                        try:
                            default_rs_date = pd.to_datetime(r['date']).date()
                        except Exception:
                            default_rs_date = date.today()
                        try:
                            default_rs_time = pd.to_datetime(r['time']).time()
                        except Exception:
                            default_rs_time = dtime(hour=9, minute=0)
                        rs_date = st.date_input("Reschedule to", value=default_rs_date, key=f"resched_date_{appt_id}")
                        rs_time = st.time_input("Time", value=default_rs_time, key=f"resched_time_{appt_id}")
                        if st.button(t["reschedule_btn"], key=f"resched_btn_{appt_id}"):
                            update_appointment_field(appt_id, "date", str(rs_date))
                            update_appointment_field(appt_id, "time", str(rs_time))
                            send_notification(r['phone'], f"Your appointment ({r['booking_ref']}) has been rescheduled to {rs_date} {rs_time}")
                            st.success("Rescheduled and patient notified.")
                            st.rerun()

                    # Notes
                    with er_col3:
                        notes_val = r['notes'] if r['notes'] else ""
                        note_text = st.text_area(t["notes_label"], value=notes_val, key=f"notes_{appt_id}", height=100)
                        if st.button(t["save_notes_btn"], key=f"save_notes_{appt_id}"):
                            update_appointment_field(appt_id, "notes", note_text.strip())
                            st.success("Note saved.")
                            st.rerun()

    # ---- Export & Analytics ----
    elif staff_menu == "Analytics":
        st.subheader("📊 Analytics Dashboard")
        if df.empty:
            st.info("No data to show.")
        else:
            try:
                today = date.today()
                week_start = today - timedelta(days=today.weekday())
                month_start = today.replace(day=1)
                total_today = len(df[df['date_dt'].dt.date == today])
                total_week = len(df[(df['date_dt'].dt.date >= week_start) & (df['date_dt'].dt.date <= today)])
                total_month = len(df[(df['date_dt'].dt.date >= month_start) & (df['date_dt'].dt.date <= today)])
                st.info(f"Total Appointments Today: {total_today}")
                st.info(f"Total Appointments This Week: {total_week}")
                st.info(f"Total Appointments This Month: {total_month}")
                st.info(f"Pending: {len(df[df['status']=='pending'])} | Confirmed: {len(df[df['status']=='confirmed'])} | Cancelled: {len(df[df['status']=='cancelled'])}")
                st.bar_chart(df['department'].value_counts())
                st.bar_chart(df['stage'].value_counts())
            except Exception:
                st.info("Unable to render analytics charts for the current data.")

    elif staff_menu == "Search / Filter":
        st.subheader("🔍 Search / Filter Appointments")
        dept_filter = st.selectbox("Department", ["All"] + df['department'].unique().tolist())
        status_filter = st.selectbox("Status", ["All", "pending", "confirmed", "cancelled"])
        stage_filter = st.selectbox("Stage", ["All"] + df['stage'].unique().tolist())
        df_filtered = df
        if dept_filter != "All":
            df_filtered = df_filtered[df_filtered['department'] == dept_filter]
        if status_filter != "All":
            df_filtered = df_filtered[df_filtered['status'] == status_filter]
        if stage_filter != "All":
            df_filtered = df_filtered[df_filtered['stage'] == stage_filter]
        st.dataframe(df_filtered)

    elif staff_menu == "Export Data":
        st.subheader("📤 Export Appointments Data")
        # CSV
        try:
            csv_bytes = df.to_csv(index=False).encode('utf-8')
            st.download_button(t["export_csv"], data=csv_bytes, file_name='appointments.csv', mime='text/csv')
        except Exception:
            st.error("Failed to prepare CSV export.")
        # Excel
        try:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False, sheet_name="appointments")
                writer.save()
            excel_data = output.getvalue()
            st.download_button(t["export_excel"], data=excel_data, file_name="appointments.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception:
            st.info("Excel export unavailable; CSV is provided.")
def run_api():
    uvicorn.run(api, host="0.0.0.0", port=8000)

# Run FastAPI server in a background thread
threading.Thread(target=run_api, daemon=True).start()

# End of app.py

