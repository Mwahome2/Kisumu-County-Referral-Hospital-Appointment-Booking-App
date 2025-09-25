# app.py
import os
import io
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date, timedelta
import hashlib
from twilio.rest import Client

# ==========================
# --- PAGE CONFIG (MUST BE FIRST) ---
# ==========================
st.set_page_config(page_title="Kisumu Hospital Appointments", layout="wide")

# ==========================
# --- DATABASE SETUP ---
# ==========================
DB_PATH = "kisumu_hospital.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# create main tables and columns
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
              insurance_verified INTEGER DEFAULT 0,
              notes TEXT,
              cancel_reason TEXT)''')
conn.commit()

# helper to add missing columns in older DBs
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
ensure_column_exists("appointments", "notes", "TEXT")
ensure_column_exists("appointments", "cancel_reason", "TEXT")

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
        "book_btn": "Book Appointment",
        "booking_success": "✅ Appointment booked for {name} on {date}",
        "booking_ref": "📌 Your Booking Reference: {ref}",
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
        "book_btn": "Weka Miadi",
        "booking_success": "✅ Miadi imewekwa kwa {name} mnamo {date}",
        "booking_ref": "📌 Kumbukumbu ya Miadi Yako: {ref}",
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
        # extras (basic swahili)
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
# --- ADMIN SEED ---
# ==========================
admin_check = c.execute("SELECT * FROM users WHERE username=?", ("admin",)).fetchone()
if not admin_check:
    c.execute("INSERT INTO users (username, password_hash, role, department) VALUES (?, ?, ?, ?)",
              ("admin", hashlib.sha256("admin123".encode()).hexdigest(), "admin", "ALL"))
    conn.commit()

# ==========================
# --- SESSION STATE INIT ---
# ==========================
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = None
    st.session_state["role"] = None

if "now_serving_id" not in st.session_state:
    st.session_state["now_serving_id"] = None

# used for edit-mode toggle and delete confirmation flags
# these will be created dynamically as needed in session_state

# ==========================
# --- HELPERS & CRUD ---
# ==========================
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_booking_ref(appt_id):
    return f"APPT-{datetime.now().strftime('%Y%m%d')}-{appt_id:03d}"

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

def get_appointments_df():
    df = pd.read_sql("SELECT * FROM appointments ORDER BY date ASC, created_at ASC", conn)
    if not df.empty:
        df['date_dt'] = pd.to_datetime(df['date'], errors='coerce')
    return df

def update_appointment_field(appt_id, field, value):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(f"UPDATE appointments SET {field}=?, updated_at=? WHERE id=?", (value, now, appt_id))
    conn.commit()

def delete_appointment(appt_id):
    c.execute("DELETE FROM appointments WHERE id=?", (appt_id,))
    conn.commit()

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
# --- APP MAIN LAYOUT ---
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
        submit = st.form_submit_button(t["book_btn"])
        if submit:
            if not patient_name.strip() or not phone.strip():
                st.warning("Please fill all required fields.")
            else:
                appt_id, ref, tele_link = insert_appointment(patient_name.strip(), phone.strip(), department, doctor.strip(), date_)
                st.success(t["booking_success"].format(name=patient_name, date=date_))
                st.info(t["booking_ref"].format(ref=ref))
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
                st.info(f"🏥 Dept: {row['department']} | 📅 Date: {row['date']} | Ref: {row['booking_ref']} | Telemedicine: {row['telemedicine_link']}")
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

    # ---- Filters / Search ----
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
        # date filtering (safe coercion)
        if isinstance(filtered.get('date_dt', None), pd.Series):
            filtered = filtered[(filtered['date_dt'].dt.date >= date_from) & (filtered['date_dt'].dt.date <= date_to)]
        if dept_filter != "All":
            filtered = filtered[filtered['department'] == dept_filter]
        if status_filter != "All":
            filtered = filtered[filtered['status'] == status_filter]
        if search_q and search_q.strip():
            s = search_q.strip().lower()
            filtered = filtered[filtered.apply(lambda r: s in str(r['patient_name']).lower() or s in str(r['phone']).lower() or s in str(r.get('booking_ref', '')).lower(), axis=1)]

    # ---- Summary cards ----
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

    # ---- Now Serving controls ----
    st.subheader(t["now_serving"])
    # if none set, choose the next pending/confirmed appointment by date
    now_id = st.session_state.get("now_serving_id", None)
    if now_id is None and not df.empty:
        next_row = df[df['stage'].isin(['pending', 'confirmed'])].sort_values(['date_dt', 'created_at']).head(1)
        if not next_row.empty:
            st.session_state["now_serving_id"] = int(next_row.iloc[0]['id'])
            now_id = st.session_state["now_serving_id"]

    if now_id:
        current = c.execute("SELECT * FROM appointments WHERE id=?", (now_id,)).fetchone()
        if current:
            cols_now = st.columns([3,1,1,1])
            with cols_now[0]:
                st.write(f"📌 {current['patient_name']} | {current['department']} | {current['date']} | Ref: {current['booking_ref']} | Stage: {current['stage']}")
            with cols_now[1]:
                if st.button(t["next_patient"], key=f"now_next_{now_id}"):
                    # mark done and move to next
                    update_appointment_field(now_id, "stage", "done")
                    st.session_state["now_serving_id"] = None
                    st.success("Marked as done and moving to next.")
                    st.rerun()
            with cols_now[2]:
                if st.button(t["skip_patient"], key=f"now_skip_{now_id}"):
                    # skip: leave stage as pending or flagged; set now_serving None to pick next
                    st.session_state["now_serving_id"] = None
                    st.success("Skipped. Next patient will be selected.")
                    st.rerun()
            with cols_now[3]:
                if st.button(t["recall_patient"], key=f"now_recall_{now_id}"):
                    send_notification(current['phone'], f"Hello {current['patient_name']}, please proceed to the clinic. Ref: {current['booking_ref']}")
                    st.success("Recall/Reminder sent.")
    else:
        st.info("No patients currently in queue.")

    st.markdown("---")

    # ---- Appointment list (detailed) ----
    st.subheader("📋 Appointment List")
    if filtered.empty:
        st.info("No appointments match the filters.")
    else:
        # iterate appointments
        for _, r in filtered.iterrows():
            appt_id = int(r['id'])
            header_label = f"📌 {r['patient_name']} | {r['department']} | {r['date']} | Status: {r['status']} | Stage: {r['stage']} | Ref: {r['booking_ref']}"
            with st.expander(header_label, expanded=False):
                st.write(f"📱 Phone: {r['phone']} | Doctor: {r['doctor']} | Notes: {r['notes'] if r['notes'] else 'None'}")
                # Action row
                act_col1, act_col2, act_col3, act_col4, act_col5 = st.columns([1,1,1,1,1])

                # Confirm
                with act_col1:
                    if st.button(t["confirm_btn"], key=f"confirm_{appt_id}"):
                        update_appointment_field(appt_id, "status", "confirmed")
                        update_appointment_field(appt_id, "stage", "confirmed")
                        send_notification(r['phone'], f"Your appointment ({r['booking_ref']}) is confirmed for {r['date']}")
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
                        send_notification(r['phone'], f"Reminder: Hello {r['patient_name']}, your appointment is on {r['date']}. Ref: {r['booking_ref']}")
                        st.success("Reminder sent (or simulated).")

                # Delete (two-step confirm)
                with act_col5:
                    confirm_flag_key = f"confirm_delete_{appt_id}"
                    if st.session_state.get(confirm_flag_key, False):
                        st.warning(t["delete_confirm"])
                        if st.button("Yes, delete", key=f"confirm_del_yes_{appt_id}"):
                            delete_appointment(appt_id)
                            send_notification(r['phone'], f"Your appointment ({r.get('booking_ref')}) was deleted by staff.")
                            st.success("Appointment deleted.")
                            # reset flag
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

                # Edit (opens a small inline form)
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
                            e_date = st.date_input("Date", value=current_date_value, key=f"edit_date_{appt_id}")
                            e_sub = st.form_submit_button(t["edit_save"], key=f"edit_save_{appt_id}")
                            if e_sub:
                                c.execute("""UPDATE appointments SET patient_name=?, phone=?, department=?, doctor=?, date=?, updated_at=? WHERE id=?""",
                                          (e_name.strip(), e_phone.strip(), e_dept.strip(), e_doc.strip(), str(e_date), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), appt_id))
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

                # Reschedule quick (date picker + button)
                with er_col2:
                    try:
                        default_rs_date = pd.to_datetime(r['date']).date()
                    except Exception:
                        default_rs_date = date.today()
                    rs_date = st.date_input("Reschedule to", value=default_rs_date, key=f"resched_date_{appt_id}")
                    if st.button(t["reschedule_btn"], key=f"resched_btn_{appt_id}"):
                        update_appointment_field(appt_id, "date", str(rs_date))
                        send_notification(r['phone'], f"Your appointment ({r['booking_ref']}) has been rescheduled to {rs_date}")
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
    st.markdown("---")
    st.subheader("Export Data")
    # CSV
    try:
        csv_bytes = df.to_csv(index=False).encode('utf-8')
        st.download_button(t["export_csv"], data=csv_bytes, file_name='appointments.csv', mime='text/csv')
    except Exception:
        st.error("Failed to prepare CSV export.")

    # Excel: try BytesIO
    try:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="appointments")
            writer.save()
        excel_data = output.getvalue()
        st.download_button(t["export_excel"], data=excel_data, file_name="appointments.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception:
        # engine not available or error — fallback skip
        st.info("Excel export is not available in this environment. CSV download still works.")

    st.markdown("---")
    st.subheader(t["analytics"])
    if df.empty:
        st.info("No data to show.")
    else:
        try:
            st.write(f"Total appointments: {len(df)}")
            st.bar_chart(df['department'].value_counts())
            st.bar_chart(df['stage'].value_counts())
        except Exception:
            st.info("Unable to render analytics charts for the current data.")

# End of app.py

