# app.py
# Streamlit Meal Attendance App (v2) – Google Sheet as Master (secured)
# -----------------------------------------------------------
# - Reads the master list LIVE from a Google Sheet (CSV export link)
# - Matches trainees by last 4 digits of phone
# - Logs attendance to a local CSV (meal_log.csv)
# - Admin panel to preview master, validate, export or clear logs
# - Google Sheet URL is hidden from normal users; only admin can override session URL

import streamlit as st
import pandas as pd
import re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# ----------------- App Config -----------------
st.set_page_config(page_title="Meal Attendance – v2 (Sheet Master)", page_icon="🍽️", layout="centered")
st.title("🍽️ Meal Attendance – v2 (Google Sheet Master)")

# Admin password (basic gate). Change this.
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "cteagms25")

# Local log file (CSV)
LOG_FILE = Path("meal_log.csv")

REQUIRED_COLS = {"FullName", "Phone"}
IST = ZoneInfo("Asia/Kolkata")

# ----------------- Helpers -----------------

def _clean_phone(s: str) -> str:
    return re.sub(r"\D", "", str(s or ""))


def load_master_df(sheet_url: str) -> pd.DataFrame:
    if not sheet_url:
        st.error("Master sheet URL not configured. Ask the admin to set it.")
        return pd.DataFrame(columns=sorted(REQUIRED_COLS | {"PhoneLast4", "FullNameNorm"}))
    try:
        df = pd.read_csv(sheet_url, dtype=str).fillna("")
    except Exception as e:
        st.error(f"Failed to load Google Sheet CSV: {e}")
        return pd.DataFrame(columns=sorted(REQUIRED_COLS | {"PhoneLast4", "FullNameNorm"}))

    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        st.error(f"Master sheet is missing required columns: {sorted(missing)}")
        return pd.DataFrame(columns=sorted(REQUIRED_COLS | {"PhoneLast4", "FullNameNorm"}))

    # Normalize columns
    df["Phone"] = df["Phone"].apply(_clean_phone)
    df["PhoneLast4"] = df["Phone"].apply(lambda s: s[-4:] if len(s) >= 4 else s)
    df["FullNameNorm"] = df["FullName"].str.strip().str.lower()

    # Optional helpful inferred columns (safe if absent)
    for col in ("EmployeeID", "TraineeID", "BatchStart", "BatchEnd"):
        if col not in df.columns:
            df[col] = ""
    return df


def append_log(row: dict):
    ts = datetime.now(IST)
    new = {
        "TimestampISO": ts.isoformat(timespec="seconds"),
        "Date": ts.strftime("%Y-%m-%d"),
        "Time": ts.strftime("%H:%M:%S"),
        "FullName": row.get("FullName", ""),
        "PhoneLast4": row.get("PhoneLast4", ""),
        "EmployeeID": row.get("EmployeeID", ""),
        "TraineeID": row.get("TraineeID", ""),
    }
    df_new = pd.DataFrame([new])
    if LOG_FILE.exists():
        df_old = pd.read_csv(LOG_FILE, dtype=str).fillna("")
        df = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df = df_new
    df.to_csv(LOG_FILE, index=False)
    return new


def load_log() -> pd.DataFrame:
    if LOG_FILE.exists():
        return pd.read_csv(LOG_FILE, dtype=str).fillna("")
    return pd.DataFrame(columns=["TimestampISO", "Date", "Time", "FullName", "PhoneLast4", "EmployeeID", "TraineeID"])  # noqa: E501


def get_master_url() -> str:
    if "sheet_url_override" in st.session_state and st.session_state["sheet_url_override"]:
        return st.session_state["sheet_url_override"]
    return st.secrets.get("MASTER_SHEET_CSV_URL", "")

# ----------------- Sidebar (no public URL input) -----------------
st.sidebar.header("⚙️ Configuration")
st.sidebar.caption("Master list source is configured by the admin.")

# ----------------- Load Master -----------------
MASTER_URL = get_master_url()
master_df = load_master_df(MASTER_URL)

# ----------------- Validation Badges -----------------
col_a, col_b, col_c = st.columns(3)
with col_a:
    st.metric("Master rows", len(master_df))
with col_b:
    blanks = int((master_df["FullName"].astype(str).str.strip() == "").sum()) if not master_df.empty else 0
    st.metric("Blank names", blanks)
with col_c:
    bad_phones = int((master_df["Phone"].str.len() < 4).sum()) if not master_df.empty else 0
    st.metric("Phones < 4 digits", bad_phones)

# Potential duplicate last-4s
if not master_df.empty:
    dup_last4 = master_df.groupby("PhoneLast4").size().reset_index(name="count")
    clash_count = int((dup_last4["count"] > 1).sum())
    st.info(f"⚠️ Last-4 collisions: {clash_count} group(s)")

# ----------------- Main: Attendance Form -----------------
st.subheader("✅ Mark Attendance")
with st.form("attend_form", clear_on_submit=True):
    phone_last4 = st.text_input("Enter last 4 digits of your phone", max_chars=4)
    submitted = st.form_submit_button("Mark Present")

if submitted:
    last4 = re.sub(r"\D", "", phone_last4 or "")[-4:]
    if len(last4) < 4:
        st.error("Please enter exactly 4 digits.")
    elif master_df.empty:
        st.error("Master sheet not loaded. Admin needs to configure it.")
    else:
        matches = master_df[master_df["PhoneLast4"] == last4]
        if matches.empty:
            st.error("No trainee found with that last-4.")
        elif len(matches) == 1:
            row = matches.iloc[0].to_dict()
            saved = append_log(row)
            st.success(f"Marked present: {saved['FullName']} at {saved['Time']}")
        else:
            st.warning("Multiple trainees share these last 4 digits. Please select your name:")
            options = [f"{r.FullName} (Emp:{r.EmployeeID}, Trainee:{r.TraineeID})" for _, r in matches.iterrows()]
            choice = st.selectbox("Select your name", options, index=None, placeholder="Choose...")
            if choice:
                idx = options.index(choice)
                row = matches.iloc[idx].to_dict()
                saved = append_log(row)
                st.success(f"Marked present: {saved['FullName']} at {saved['Time']}")

# ----------------- Live Log View -----------------
st.subheader("📒 Today’s Logs")
log_df = load_log()
if not log_df.empty:
    today = datetime.now(IST).strftime("%Y-%m-%d")
    today_df = log_df[log_df["Date"] == today]
    st.dataframe(today_df.tail(20), use_container_width=True)
else:
    st.write("No logs yet today.")

# ----------------- Admin Panel -----------------
st.divider()
st.subheader("🔐 Admin Panel")
admin_pwd = st.text_input("Admin password", type="password")
if admin_pwd == ADMIN_PASSWORD:
    st.success("Admin unlocked")
    with st.expander("Preview master (first 25 rows)"):
        st.dataframe(master_df.head(25), use_container_width=True)

    with st.expander("Master data source (admin-only)"):
        st.write("You can set a session-only override for the master source below.")
        new_url = st.text_input(
            "New Google Sheet CSV URL (optional override for THIS session)",
            value="",
            placeholder="https://docs.google.com/spreadsheets/d/.../pub?gid=0&single=true&output=csv",
        )
        if st.button("Use this URL for this session"):
            if new_url.strip():
                st.session_state["sheet_url_override"] = new_url.strip()
                st.success("Session override set. The app will now use this URL.")
            else:
                st.session_state.pop("sheet_url_override", None)
                st.info("Cleared session override. Reverting to the default (secrets).")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Export full log (CSV)"):
            st.download_button(
                label="Download meal_log.csv",
                data=log_df.to_csv(index=False).encode("utf-8"),
                file_name="meal_log.csv",
                mime="text/csv",
            )
    with col2:
        if st.button("Show log tail (100)"):
            st.dataframe(log_df.tail(100), use_container_width=True)
    with col3:
        if st.button("Clear ALL logs", type="primary"):
            LOG_FILE.unlink(missing_ok=True)
            st.warning("All logs cleared.")
else:
    st.info("Enter admin password to access admin tools.")

# ----------------- Footer -----------------
st.caption(
    "v2 – Uses Google Sheet as master. Required columns: FullName, Phone. Timezone: Asia/Kolkata."
)

