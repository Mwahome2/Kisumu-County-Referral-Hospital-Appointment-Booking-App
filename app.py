import os
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date, timedelta
import hashlib
from twilio.rest import Client

# ==========================
# --- CONFIG / DB SETUP ---
# ==========================
DB_PATH = "kisumu_hospital.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# --- Create tables if not exist (full schema) ---
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
ensure_column_exists("appointments", "notes", "TEXT")
ensure_column_exists("appointments", "cancel_reason", "TEXT")

# ==========================
# --- MULTI-LANGUAGE TEXT ---
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
        "stages": ["pending", "confirmed", "in consultation", "done"],
        # Manage appointments extras
        "confirm_btn": "Confirm",
        "cancel_btn": "Cancel",
        "cancel_reason": "Cancel Reason (optional)",
        "edit_btn": "Edit",
        "reschedule_btn": "Reschedule",
        "send_reminder_btn": "Send Reminder",
        "notes_label": "Staff Notes",
        "save_notes_btn": "Save Note",
        "delete_btn": "Delete",
        "delete_confirm": "Are you sure? This will permanently delete the appointment.",
        "now_serving": "Now Serving",
        "next_patient": "Next Patient",
        "skip_patient": "Skip",
        "recall_patient": "Recall",
        "search_placeholder": "Search by name, phone, or ref",
        "export_csv": "Download CSV",
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
        "status_pending": "⏳ Hali: Inasubiri uthibitisho",
        "status_confirmed": "✅ Hali: Imethibitishwa",
        "status_cancelled": "❌ Hali: Imefutwa",
        "staff_manage": "📋 Dhibiti Miadi (Orodha ya Wateja)",
        "analytics": "📊 Dashibodi ya Takwimu",
        "stage_label": "Kipindi cha huduma",
        "update_stage": "Sasisha Kipindi",
        "stages": ["pending", "confirmed", "in consultation", "done"],
        # Manage appointments extras (basic Swahili)
        "confirm_btn": "Thibitisha",
        "cancel_btn": "Ghairi",
        "cancel_reason": "Sababu ya kughairi (hiari)",
        "edit_btn": "Hariri",
        "reschedule_btn": "Panga upya",
        "send_reminder_btn": "Tuma Kumbusho",
        "notes_label": "Maelezo ya Wafanyakazi",
        "save_notes_btn": "Hifadhi Kumbukumbu",
        "delete_btn": "Futa",
        "delete_confirm": "Una uhakika? Hii itafuta miadi kabisa.",
        "now_serving": "Inahudumiwa sasa",
        "next_patient": "Mgonjwa Ifuatayo",
        "skip_patient": "Ruka",
        "recall_patient": "Rudia",
        "search_placeholder": "Tafuta kwa jina, simu, au kumbukumbu",
        "export_csv": "Pakua CSV",
        "edit_save": "Hifadhi Mabadiliko",
    }
}

st.sidebar.title("🌐 Language / Lugha")
if "language" not in st.session_state:
    st.session_state["language"] = "en"
st.session_state["language"] = st.sidebar.selectbox(
    "Choose Language / Chagua Lugha", ["en", "sw"], index=0 if st.session_state["language"] == "en" else 1
)
lang = st.session_state["language"]
t = languages[lang]

# ==========================
# --- HELPERS / TWILIO ---
# ==========================
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_booking_ref(appt_id):
    return f"APPT-{datetime.now().strftime('%Y%m%d')}-{appt_id:03d}"

# Twilio
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
        try:
            client = Client(account_sid, auth_token)
            if "whatsapp" in twilio_number.lower():
                client.messages.create(body=msg, from_=twilio_number, to=f"whatsapp:+{phone}")
            else:
                client.messages.create(body=msg, from_=twilio_number, to=f"+{phone}")
        except Exception as e:
            st.warning(f"⚠️ SMS/WhatsApp not sent: {e}")
    else:
        # Simulate when Twilio not configured
        st.info(f"ℹ️ Simulated notification:\nTo: {phone}\nMessage: {msg}")

# ==========================
# --- ADMIN SEED ---
# ==========================
admin_check = c.execute("SELECT * FROM users WHERE username=?", ("admin",)).fetchone()
if not admin_check:
    c.execute("INSERT INTO users (username, password_hash, role, department) VALUES (?, ?, ?, ?)",
              ("admin", hash_password("admin123"), "admin", "ALL"))
    conn.commit()

# ==========================
# --- SESSION STATE INIT ---
# ==========================
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = None
    st.session_state["role"] = None

# track now serving id
if "now_serving_id" not in st.session_state:
    st.session_state["now_serving_id"] = None

# ==========================
# --- AUTHENTICATION UI ---
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
    # quick admin button
    st.write("Quick admin:")
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
# --- CRUD HELPERS ---
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

def get_appointments_df():
    df = pd.read_sql("SELECT * FROM appointments ORDER BY date ASC, created_at ASC", conn)
    if not df.empty:
        df['date_dt'] = pd.to_datetime(df['date'])
    return df

def update_appointment_field(appt_id, field, value):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(f"UPDATE appointments SET {field}=?, updated_at=? WHERE id=?", (value, now, appt_id))
    conn.commit()

def delete_appointment(appt_id):
    c.execute("DELETE FROM appointments WHERE id=?", (appt_id,))
    conn.commit()

# ==========================
# --- APP LAYOUT ---
# ==========================
st.set_page_config(page_title="Kisumu Hospital Appointments", layout="wide")
st.title(t["title"])
menu_choice = st.sidebar.selectbox("Menu", t["menu"])
# show logout on sidebar if logged in
if st.session_state["logged_in"]:
    st.sidebar.write(f"👤 {st.session_state['username']}")
    if st.sidebar.button("Logout"):
        st.session_state["logged_in"] = False
        st.session_state["username"] = None
        st.session_state["role"] = None
        st.session_state["now_serving_id"] = None
        st.rerun()

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
    # require login for staff
    if not st.session_state["logged_in"]:
        manual_login()
        st.stop()

    # staff panel header
    st.subheader(f"👤 Welcome, {st.session_state['username']}")
    st.header(t["staff_manage"])

    # Filters & search
    df = get_appointments_df()

    # Top row: Search, Date range, Department, Status
    with st.expander("🔎 Search / Filter", expanded=True):
        col1, col2, col3, col4 = st.columns([3,2,2,2])
        with col1:
            search_q = st.text_input(t["search_placeholder"], key="search_q")
        with col2:
            date_from = st.date_input("From", value=date.today() - timedelta(days=7), key="filter_from")
        with col3:
            date_to = st.date_input("To", value=date.today() + timedelta(days=30), key="filter_to")
        with col4:
            dept_options = ["All"] + (df['department'].dropna().unique().tolist() if not df.empty else [])
            dept_filter = st.selectbox("Department", dept_options, key="filter_dept")
            status_filter = st.selectbox("Status", ["All", "pending", "confirmed", "cancelled", "in consultation", "done"], key="filter_status")

    # Apply filters
    filtered = df.copy()
    if not filtered.empty:
        # date filtering
        filtered = filtered[(filtered['date_dt'].dt.date >= date_from) & (filtered['date_dt'].dt.date <= date_to)]
        # dept
        if dept_filter != "All":
            filtered = filtered[filtered['department'] == dept_filter]
        # status
        if status_filter != "All":
            filtered = filtered[filtered['status'] == status_filter]
        # search
        if search_q and search_q.strip():
            s = search_q.strip().lower()
            filtered = filtered[filtered.apply(lambda r: s in str(r['patient_name']).lower() or s in str(r['phone']).lower() or s in str(r.get('booking_ref', '')).lower(), axis=1)]

    # Summary cards
    col1, col2, col3, col4 = st.columns(4)
    total = len(df)
    today = date.today()
    total_today = len(df[df['date_dt'].dt.date == today]) if not df.empty else 0
    pending = len(df[df['status'] == 'pending']) if not df.empty else 0
    confirmed = len(df[df['status'] == 'confirmed']) if not df.empty else 0
    with col1:
        st.metric("Total Appointments", total)
    with col2:
        st.metric("Today", total_today)
    with col3:
        st.metric("Pending", pending)
    with col4:
        st.metric("Confirmed", confirmed)

    # Now serving card & queue controls
    st.markdown("---")
    st.subheader(t["now_serving"])
    # try to get current now_serving_id if set, else pick the next pending/confirmed appointment
    now_id = st.session_state.get("now_serving_id", None)
    if now_id is None:
        next_row = df[(df['stage'].isin(['pending','confirmed']))].head(1)
        if not next_row.empty:
            now_id = int(next_row.iloc[0]['id'])
            st.session_state["now_serving_id"] = now_id

    if now_id:
        row = c.execute("SELECT * FROM appointments WHERE id=?", (now_id,)).fetchone()
        if row:
            cols = st.columns([3,1,1,1])
            with cols[0]:
                st.write(f"📌 {row['patient_name']} | {row['department']} | {row['date']} | Ref: {row['booking_ref']} | Stage: {row['stage']}")
            with cols[1]:
                if st.button(t["next_patient"], key=f"next_patient_{now_id}"):
                    # mark current as done and move to next
                    update_appointment_field(now_id, "stage", "done")
                    st.session_state["now_serving_id"] = None
                    st.success("Marked as done and moving to next.")
                    st.rerun()
            with cols[2]:
                if st.button(t["skip_patient"], key=f"skip_patient_{now_id}"):
                    # skip: set to pending and find next; here we mark it pending and move on
                    update_appointment_field(now_id, "stage", "pending")
                    st.session_state["now_serving_id"] = None
                    st.success("Skipped. Next patient will be selected.")
                    st.rerun()
            with cols[3]:
                if st.button(t["recall_patient"], key=f"recall_patient_{now_id}"):
                    # send a reminder/recall
                    send_notification(row['phone'], f"Hello {row['patient_name']}, please proceed to the clinic. Ref: {row['booking_ref']}")
                    st.success("Recall/Reminder sent.")
    else:
        st.info("No patients currently in queue.")

    st.markdown("---")

    # Manage appointment list (detailed rows)
    st.subheader("📋 Appointment List")
    if filtered.empty:
        st.info("No appointments match the filters.")
    else:
        # loop rows
        for _, r in filtered.iterrows():
            appt_id = int(r['id'])
            with st.expander(f"📌 {r['patient_name']} | {r['department']} | {r['date']} | Status: {r['status']} | Stage: {r['stage']} | Ref: {r['booking_ref']}", expanded=False):
                cols = st.columns([3,1,1,1])
                # Action: Confirm
                with cols[0]:
                    if st.button(t["confirm_btn"], key=f"confirm_{appt_id}"):
                        update_appointment_field(appt_id, "status", "confirmed")
                        update_appointment_field(appt_id, "stage", "confirmed")
                        send_notification(r['phone'], f"Your appointment ({r['booking_ref']}) is confirmed for {r['date']}")
                        st.success("Appointment confirmed.")
                        st.rerun()

                # Action: Cancel (with optional reason)
                with cols[1]:
                    cancel_reason_input = st.text_input(t["cancel_reason"], key=f"cancel_reason_{appt_id}")
                    if st.button(t["cancel_btn"], key=f"cancel_{appt_id}"):
                        update_appointment_field(appt_id, "status", "cancelled")
                        update_appointment_field(appt_id, "stage", "cancelled")
                        update_appointment_field(appt_id, "cancel_reason", cancel_reason_input or "No reason provided")
                        send_notification(r['phone'], f"Your appointment ({r['booking_ref']}) has been cancelled. Reason: {cancel_reason_input or 'N/A'}")
                        st.warning("Appointment cancelled.")
                        st.rerun()

                # Action: Update Stage (selectbox + update)
                with cols[2]:
                    new_stage = st.selectbox(t["update_stage"], t["stages"], index=t["stages"].index(r['stage']) if r['stage'] in t["stages"] else 0, key=f"stage_sel_{appt_id}")
                    if st.button("Update Stage", key=f"update_stage_btn_{appt_id}"):
                        update_appointment_field(appt_id, "stage", new_stage)
                        st.success("Stage updated.")
                        st.rerun()

                # Action: Send Reminder
                with cols[3]:
                    if st.button(t["send_reminder_btn"], key=f"remind_{appt_id}"):
                        send_notification(r['phone'], f"Reminder: Hello {r['patient_name']}, your appointment is on {r['date']}. Ref: {r['booking_ref']}")
                        st.success("Reminder sent (or simulated).")

                # Below action row: Edit, Reschedule, Notes, Delete
                col_edit, col_resched, col_notes, col_delete = st.columns([2,2,3,1])

                # Edit form (name, phone, department, doctor)
                with col_edit:
                    if st.button(t["edit_btn"], key=f"edit_toggle_{appt_id}"):
                        # render inline edit form
                        with st.form(f"edit_form_{appt_id}", clear_on_submit=False):
                            ename = st.text_input("Name", value=r['patient_name'], key=f"edit_name_{appt_id}")
                            ephone = st.text_input("Phone", value=r['phone'], key=f"edit_phone_{appt_id}")
                            edept = st.text_input("Department", value=r['department'], key=f"edit_dept_{appt_id}")
                            edoc = st.text_input("Doctor", value=r['doctor'], key=f"edit_doc_{appt_id}")
                            submitted = st.form_submit_button(t["edit_save"], key=f"edit_save_{appt_id}")
                            if submitted:
                                update_appointment_field(appt_id, "patient_name", ename.strip())
                                update_appointment_field(appt_id, "phone", ephone.strip())
                                update_appointment_field(appt_id, "department", edept.strip())
                                update_appointment_field(appt_id, "doctor", edoc.strip())
                                st.success("Appointment updated.")
                                st.rerun()

                # Reschedule (date picker)
                with col_resched:
                    new_date = st.date_input("Reschedule to", value=pd.to_datetime(r['date']).date(), key=f"resched_{appt_id}")
                    if st.button(t["reschedule_btn"], key=f"resched_btn_{appt_id}"):
                        update_appointment_field(appt_id, "date", str(new_date))
                        send_notification(r['phone'], f"Your appointment ({r['booking_ref']}) has been rescheduled to {new_date}")
                        st.success("Rescheduled and patient notified.")
                        st.rerun()

                # Notes area
                with col_notes:
                    note_text = st.text_area(t["notes_label"], value=r['notes'] if r['notes'] else "", key=f"notes_{appt_id}", height=80)
                    if st.button(t["save_notes_btn"], key=f"save_note_{appt_id}"):
                        update_appointment_field(appt_id, "notes", note_text.strip())
                        st.success("Note saved.")
                        st.rerun()

                # Delete (with confirmation)
                with col_delete:
                    if st.button(t["delete_btn"], key=f"delete_{appt_id}"):
                        if st.confirm(t["delete_confirm"] if "delete_confirm" in t else "Confirm delete?"):
                            delete_appointment(appt_id)
                            send_notification(r['phone'], f"Your appointment ({r.get('booking_ref')}) was deleted by staff.")
                            st.warning("Appointment deleted.")
                            st.rerun()
                        else:
                            st.info("Delete cancelled.")

    # Export data
    st.markdown("---")
    st.subheader("Export Data")
    df_export = df.drop(columns=['date_dt']) if not df.empty else df
    csv = df_export.to_csv(index=False).encode('utf-8')
    st.download_button(t["export_csv"], data=csv, file_name='appointments.csv', mime='text/csv')

    # Analytics quick view
    st.markdown("---")
    st.subheader(t["analytics"])
    if df.empty:
        st.info("No data to show.")
    else:
        # small analytics cards and charts
        st.write(f"Total appointments: {len(df)}")
        try:
            # simple counts
            st.bar_chart(df['department'].value_counts())
            st.bar_chart(df['stage'].value_counts())
        except Exception:
            pass

# End of app.py
