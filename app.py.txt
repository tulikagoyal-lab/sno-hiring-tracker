import streamlit as st
import pandas as pd
import hashlib
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
from io import BytesIO
import warnings
import os
import json

warnings.filterwarnings("ignore")

# ═════════════════════════════════════════════════════
# BACKEND SELECTION: Google Sheets (production) vs SQLite (local)
# ═════════════════════════════════════════════════════

USE_GSHEETS = os.environ.get("USE_GSHEETS", "false").lower() == "true"
GSHEET_URL = os.environ.get("GSHEET_URL", "")

# ═════════════════════════════════════════════════════
# Google Sheets Backend
# ═════════════════════════════════════════════════════

def read_gsheet():
    """Read data from Google Sheet (URL mode for Streamlit Cloud)"""
    if not GSHEET_URL:
        return None
    try:
        df = pd.read_csv(GSHEET_URL)
        return df
    except:
        return None

def get_db():
    """Unified database interface - returns dict with in-memory data"""
    if USE_GSHEETS:
        return get_gsheet_data()
    else:
        return get_sqlite_data()

def get_gsheet_data():
    """Load from Google Sheet or return empty structure"""
    data = read_gsheet()
    if data is None:
        return {"submissions": [], "channels": [], "targets": []}
    # Expected columns: channel, week_label, metric, value
    subs = []
    for _, row in data.iterrows():
        subs.append({
            "channel": row.get("channel", ""),
            "week_label": str(row.get("week_label", "")),
            "metric": row.get("metric", ""),
            "value": row.get("value", 0),
            "submitted_at": row.get("submitted_at", ""),
        })
    return {"submissions": subs, "channels": [], "targets": []}

# ═════════════════════════════════════════════════════
# SQLite Backend (for local development)
# ═════════════════════════════════════════════════════

import sqlite3

DB_PATH = "sno_hiring.db"

def get_sqlite_data():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
    except:
        return {"submissions": [], "channels": [], "targets": []}

    c = conn.cursor()

    # Get submissions
    c.execute("""
        SELECT s.week_label, ch.name as channel, s.data_json, s.submitted_at
        FROM submissions s JOIN channels ch ON s.channel_id = ch.id
    """)
    rows = c.fetchall()
    submissions = []
    for r in rows:
        data = json.loads(r["data_json"])
        for k, v in data.items():
            submissions.append({
                "channel": r["channel"],
                "week_label": r["week_label"],
                "metric": k,
                "value": v,
                "submitted_at": r["submitted_at"]
            })

    # Get channels
    c.execute("SELECT name, is_admin FROM channels")
    channels = [{"name": r[0], "is_admin": r[1]} for r in c.fetchall()]

    # Get targets
    c.execute("SELECT week_label, metric_path, plan_value, expected_value FROM targets")
    targets = [dict(r) for r in c.fetchall()]

    conn.close()
    return {"submissions": submissions, "channels": channels, "targets": targets}

def save_submission(channel, week_label, data):
    """Save submission - works with both backends"""
    if USE_GSHEETS:
        # For GSheets, would need to append - complex, use local for now
        st.info("Google Sheets backend: Please use local mode for submissions")
        return

    # SQLite fallback
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM channels WHERE name=?", (channel,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False

    channel_id = row[0]
    now = datetime.now().isoformat()

    c.execute("SELECT id FROM submissions WHERE channel_id=? AND week_label=?",
              (channel_id, week_label))
    existing = c.fetchone()

    if existing:
        c.execute("UPDATE submissions SET data_json=?, submitted_at=? WHERE id=?",
                  (json.dumps(data), now, existing[0]))
    else:
        c.execute("INSERT INTO submissions (channel_id, week_start, week_label, data_json) VALUES (?,?,?,?)",
                  (channel_id, datetime.now().date().isoformat(), week_label, json.dumps(data)))

    conn.commit()
    conn.close()
    return True

# ═════════════════════════════════════════════════════
# Database Initialization (SQLite only)
# ═════════════════════════════════════════════════════

def init_db():
    if USE_GSHEETS:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        passcode TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id INTEGER NOT NULL,
        week_start TEXT NOT NULL,
        week_label TEXT NOT NULL,
        submitted_at TEXT DEFAULT (datetime('now')),
        data_json TEXT NOT NULL,
        FOREIGN KEY (channel_id) REFERENCES channels(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_label TEXT NOT NULL,
        metric_path TEXT NOT NULL,
        plan_value REAL,
        expected_value REAL,
        UNIQUE(week_label, metric_path)
    )""")

    conn.commit()
    conn.close()

# ── Helpers ──

def make_passcode(raw):
    return hashlib.sha256(raw.encode()).hexdigest()[:12]

def week_label(dt):
    return f"WK{dt.isocalendar()[1]}-{dt.year}"

def get_current_week_start():
    today = datetime.now()
    return today - timedelta(days=today.weekday())

# ── Metric Definitions (mirrors your CSV structure) ──

METRICS = [
    # (section, label, key)
    ("Orders", "SOC Order Count", "orders_soc"),
    ("Orders", "SNO Order Count", "orders_sno"),

    ("SNO Hiring", "Spillover (> 28 days)", "sno_spillover_28"),
    ("SNO Hiring", "CPFOD SW+Spillover - Referral", "sno_cpfod_ref"),
    ("SNO Hiring", "CPFOD SW+Spillover - RB Override", "sno_cpfod_rb_override"),
    ("SNO Hiring", "CPFOD SW+Spillover - Agency", "sno_cpfod_agency"),
    ("SNO Hiring", "Rejoiner Count / Activation Count", "sno_rejoiner"),

    ("SNO Absolute Cost", "Flatpay (without Leakage)", "cost_flatpay"),
    ("SNO Absolute Cost", "Leakage", "cost_leakage"),
    ("SNO Absolute Cost", "Shouldering", "cost_shouldering"),
    ("SNO Absolute Cost", "Dormant RB", "cost_dormant_rb"),
    ("SNO Absolute Cost", "Impersonation", "cost_impersonation"),
    ("SNO Absolute Cost", "JB Cost", "cost_jb"),
    ("SNO Absolute Cost", "RB Cost - SW CPFOD", "cost_rb_cpfod"),
    ("SNO Absolute Cost", "RB Cost - SW FOD", "cost_rb_fod"),
    ("SNO Absolute Cost", "Referral Override - SW CPFOD", "cost_ref_override_cpfod"),
    ("SNO Absolute Cost", "Referral Override - SW FOD", "cost_ref_override_fod"),
    ("SNO Absolute Cost", "Spillover <= 28 Days Cost", "cost_spillover_28"),
    ("SNO Absolute Cost", "Agency Cost", "cost_agency"),
    ("SNO Absolute Cost", "Google - Supper App Cost", "cost_google_supper"),
    ("SNO Absolute Cost", "Google - Extra Cost", "cost_google_extra"),
    ("SNO Absolute Cost", "Google - Supper App Fresh FOD", "cost_google_fresh_fod"),
    ("SNO Absolute Cost", "Google - IM App Cost", "cost_google_im_app"),
    ("SNO Absolute Cost", "Google - SNO IM 1st Party Spend", "cost_google_im_1st"),
    ("SNO Absolute Cost", "Google - Extra 1st Party Spend", "cost_google_extra_1st"),
    ("SNO Absolute Cost", "Collection of Upfront Fee", "cost_upfront_fee"),
    ("SNO Absolute Cost", "Insurance", "cost_insurance"),
    ("SNO Absolute Cost", "OB Fee Collection", "cost_ob_fee"),
    ("SNO Absolute Cost", "Apsflyer Portal", "cost_apsflyer"),
    ("SNO Absolute Cost", "Pivot Roots Multiplier", "cost_pivot_roots"),
    ("SNO Absolute Cost", "Autodialer Cost", "cost_autodialer"),
    ("SNO Absolute Cost", "BGV Fresh - Betterplace+Authbridge", "cost_bgv_fresh"),
    ("SNO Absolute Cost", "BGV Fresh - Additional (Address Check)", "cost_bgv_address"),
    ("SNO Absolute Cost", "BGV Rejoiner", "cost_bgv_rejoiner"),
    ("SNO Absolute Cost", "SMS Cost Fresh", "cost_sms_fresh"),
    ("SNO Absolute Cost", "SMS Cost Rejoiner", "cost_sms_rejoiner"),
    ("SNO Absolute Cost", "Whatsapp Comms Fresh", "cost_whatsapp_fresh"),
    ("SNO Absolute Cost", "Whatsapp Comms Rejoiner", "cost_whatsapp_rejoiner"),
    ("SNO Absolute Cost", "OBE/RTC/Other Incentive", "cost_obe_rtc"),
    ("SNO Absolute Cost", "FR Salary", "cost_fr_salary"),
    ("SNO Absolute Cost", "FR Count", "cost_fr_count"),
    ("SNO Absolute Cost", "FR TL Salary", "cost_fr_tl_salary"),
    ("SNO Absolute Cost", "FR TL Count", "cost_fr_tl_count"),
    ("SNO Absolute Cost", "BTL Spend", "cost_btl"),
    ("SNO Absolute Cost", "FR+FR TL Incentive", "cost_fr_incentive"),
    ("SNO Absolute Cost", "Influencer Payout", "cost_influencer_payout"),
    ("SNO Absolute Cost", "Influencer TL Salary", "cost_inf_tl_salary"),
    ("SNO Absolute Cost", "Influencer TL Count", "cost_inf_tl_count"),
    ("SNO Absolute Cost", "Spillover > 28 Days", "cost_spillover_over_28"),
    ("SNO Absolute Cost", "Other Cost - Some Multiplier", "cost_other_mult"),
    ("SNO Absolute Cost", "Other Cost - Some Value", "cost_other_val"),

    ("SNO Same Week Transacting", "Referral", "transact_ref"),
    ("SNO Same Week Transacting", "Google", "transact_google"),
    ("SNO Same Week Transacting", "Affiliate", "transact_affiliate"),
    ("SNO Same Week Transacting", "SSU Direct", "transact_ssu"),
    ("SNO Same Week Transacting", "FR", "transact_fr"),
    ("SNO Same Week Transacting", "Agency", "transact_agency"),
    ("SNO Same Week Transacting", "Influencers", "transact_influencers"),

    ("SNO Spill Over FOD", "Referral", "spill_fod_ref"),
    ("SNO Spill Over FOD", "Google", "spill_fod_google"),
    ("SNO Spill Over FOD", "Affiliate", "spill_fod_affiliate"),
    ("SNO Spill Over FOD", "SSU Direct", "spill_fod_ssu"),
    ("SNO Spill Over FOD", "FR", "spill_fod_fr"),
    ("SNO Spill Over FOD", "Agency", "spill_fod_agency"),
    ("SNO Spill Over FOD", "Influencers", "spill_fod_influencers"),

    ("SNO Onboarding", "Referral", "onboard_ref"),
    ("SNO Onboarding", "Google", "onboard_google"),
    ("SNO Onboarding", "Affiliate", "onboard_affiliate"),
    ("SNO Onboarding", "SSU Direct", "onboard_ssu"),
    ("SNO Onboarding", "FR", "onboard_fr"),
    ("SNO Onboarding", "Agency", "onboard_agency"),
    ("SNO Onboarding", "Influencers", "onboard_influencers"),

    ("SOC Hiring", "Fresh Onboarding", "soc_fresh_onboard"),
    ("SOC Hiring", "SOC Rejoiner Count", "soc_rejoiner"),
    ("SOC Hiring", "Spillover (< 28 days)", "soc_spillover_28"),
    ("SOC Hiring", "Spillover (> 28 days)", "soc_spillover_over_28"),

    ("SOC CPH", "Referral CPOD", "soc_cpod_ref"),

    ("SOC Absolute Cost", "SOC Rejoiner Cost", "soc_rejoiner_cost"),
    ("SOC Absolute Cost", "JB Cost", "soc_jb_cost"),
    ("SOC Absolute Cost", "RB Cost - SW CPFOD", "soc_rb_cpfod"),
    ("SOC Absolute Cost", "Spillover <= 28 Days", "soc_cost_spillover_28"),
    ("SOC Absolute Cost", "Spillover > 28 Days", "soc_cost_spillover_over_28"),
    ("SOC Absolute Cost", "JB Adjustment", "soc_jb_adjust"),
    ("SOC Absolute Cost", "RB Adjustment", "soc_rb_adjust"),
    ("SOC Absolute Cost", "Agency Cost", "soc_agency_cost"),
    ("SOC Absolute Cost", "Google - IM App Weekly", "soc_google_im"),
    ("SOC Absolute Cost", "Google - Supper App", "soc_google_supper"),
    ("SOC Absolute Cost", "Google - IM SA FOD", "soc_google_im_sa_fod"),
    ("SOC Absolute Cost", "Google - SF SA FOD", "soc_google_sf_sa_fod"),
    ("SOC Absolute Cost", "Extra SOC Spend - IM App Weekly", "soc_extra_im"),
    ("SOC Absolute Cost", "Collection of Upfront Fee", "soc_upfront_fee"),
    ("SOC Absolute Cost", "Insurance", "soc_insurance"),
    ("SOC Absolute Cost", "OB Fee Collection", "soc_ob_fee"),
    ("SOC Absolute Cost", "SOC OB Fees", "soc_ob_fees_actual"),
    ("SOC Absolute Cost", "BGV Cost", "soc_bgv"),
    ("SOC Absolute Cost", "SMS Comms Fresh", "soc_sms_fresh"),
    ("SOC Absolute Cost", "SMS Comms Rejoiner", "soc_sms_rejoiner"),
    ("SOC Absolute Cost", "Whatsapp Comms Fresh", "soc_whatsapp_fresh"),
    ("SOC Absolute Cost", "Whatsapp Comms Rejoiner", "soc_whatsapp_rejoiner"),
    ("SOC Absolute Cost", "BTL Spend", "soc_btl"),
    ("SOC Absolute Cost", "TC/Other Incentive", "soc_tc_incentive"),
    ("SOC Absolute Cost", "IM FR Count", "soc_fr_count"),
    ("SOC Absolute Cost", "IM TL Count", "soc_tl_count"),
    ("SOC Absolute Cost", "FR Initiatives", "soc_fr_initiatives"),
    ("SOC Absolute Cost", "FR Cost Extra Not Considered", "soc_fr_extra"),

    ("SOC Same Week Transacting", "Referral", "soc_transact_ref"),
    ("SOC Same Week Transacting", "Google", "soc_transact_google"),
    ("SOC Same Week Transacting", "Affiliate", "soc_transact_affiliate"),
    ("SOC Same Week Transacting", "SSU Direct", "soc_transact_ssu"),
    ("SOC Same Week Transacting", "FR", "soc_transact_fr"),
    ("SOC Same Week Transacting", "Agency", "soc_transact_agency"),
    ("SOC Same Week Transacting", "Goldmine", "soc_transact_goldmine"),
    ("SOC Same Week Transacting", "Influencers", "soc_transact_influencers"),

    ("SOC Spill Over FOD", "Referral", "soc_spill_fod_ref"),
    ("SOC Spill Over FOD", "Google", "soc_spill_fod_google"),
    ("SOC Spill Over FOD", "Affiliate", "soc_spill_fod_affiliate"),
    ("SOC Spill Over FOD", "SSU Direct", "soc_spill_fod_ssu"),
    ("SOC Spill Over FOD", "FR", "soc_spill_fod_fr"),
    ("SOC Spill Over FOD", "Agency", "soc_spill_fod_agency"),
    ("SOC Spill Over FOD", "Influencers", "soc_spill_fod_influencers"),
]

# ── Styling ──
st.set_page_config(page_title="SNO Hiring Cost Tracker", layout="wide")
st.markdown("""
<style>
    .metric-card { background: #f0f2f6; border-radius: 10px; padding: 20px; text-align: center; }
    .metric-value { font-size: 28px; font-weight: bold; color: #1f77b4; }
    .metric-label { font-size: 14px; color: #666; }
    .delta-positive { color: #d32f2f; font-weight: bold; }
    .delta-negative { color: #388e3c; font-weight: bold; }
    .stButton button { width: 100%; }
</style>
""", unsafe_allow_html=True)

# ── Initialize DB ──
init_db()

# ── Session State ──
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user = None
    st.session_state.is_admin = False

# ══════════════════════════════════════════════════
# LOGIN (SQLite-backed for local, simple for cloud)
# ══════════════════════════════════════════════════
def login_page():
    st.title("🔐 SNO Hiring Cost Tracker")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("### Login")
        name = st.text_input("Your Name", placeholder="e.g. Tulika")
        passcode = st.text_input("Passcode", type="password", placeholder="Enter your passcode")
        if st.button("Login", use_container_width=True):
            if not name or not passcode:
                st.error("Please enter name and passcode")
                return

            # For local SQLite mode
            if not USE_GSHEETS:
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                hashed = make_passcode(passcode)
                c.execute("SELECT * FROM channels WHERE name=? AND passcode=?", (name, hashed))
                row = c.fetchone()
                conn.close()

                if row:
                    st.session_state.logged_in = True
                    st.session_state.user = {"id": row["id"], "name": row["name"], "is_admin": row["is_admin"]}
                    st.session_state.is_admin = row["is_admin"] == 1
                    st.rerun()
                else:
                    st.error("Invalid name or passcode. Contact admin to set up your account.")
            else:
                # Cloud mode - use a default admin
                if name.lower() == "tulika" and passcode == "admin123":
                    st.session_state.logged_in = True
                    st.session_state.user = {"id": 1, "name": "Tulika", "is_admin": 1}
                    st.session_state.is_admin = True
                    st.rerun()
                else:
                    st.error("Invalid credentials for cloud deployment.")

        st.markdown("---")
        st.markdown("**First time?** Contact admin to get your login.")

# ══════════════════════════════════════════════════
# SUBMISSION FORM (Channel Owner)
# ══════════════════════════════════════════════════
def submission_form():
    st.title("📝 Weekly Data Submission")
    st.markdown(f"Logged in as **{st.session_state.user['name']}**")

    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.user = None
            st.rerun()

    week_start = get_current_week_start()
    wk = week_label(week_start)

    st.markdown(f"### Week: {wk} ({week_start.strftime('%d %b %Y')})")
    st.markdown("Fill in the numbers for your channel. Leave blank if not applicable.")

    # Group metrics by section
    sections = {}
    for sec, label, key in METRICS:
        sections.setdefault(sec, []).append((label, key))

    with st.form("submission_form"):
        data = {}
        for section, items in sections.items():
            st.markdown(f"### {section}")
            cols = st.columns(3)
            for i, (label, key) in enumerate(items):
                with cols[i % 3]:
                    val = st.text_input(label.replace("_", " "), placeholder="0", key=f"fld_{key}")
                    data[key] = val

        st.markdown("---")
        submitted = st.form_submit_button("Submit Data", use_container_width=True, type="primary")

    if submitted:
        clean = {}
        for key, val in data.items():
            v = val.strip().replace(",", "")
            if v == "" or v == "0":
                clean[key] = 0.0
            else:
                try:
                    clean[key] = float(v)
                except:
                    clean[key] = 0.0

        if save_submission(st.session_state.user["name"], wk, clean):
            st.success("✅ Data submitted successfully!")
            st.balloons()
        else:
            st.error("Error saving data. Please try again.")

    # Show past submissions
    with st.expander("📜 My Past Submissions"):
        db_data = get_db()
        my_subs = [s for s in db_data["submissions"] if s.get("channel", "").lower() == st.session_state.user["name"].lower()]
        weeks = sorted(set(s["week_label"] for s in my_subs), reverse=True)
        if weeks:
            for w in weeks[:10]:
                st.text(f"{w}")
        else:
            st.info("No past submissions yet.")


# ══════════════════════════════════════════════════
# ADMIN DASHBOARD
# ══════════════════════════════════════════════════
def admin_dashboard():
    st.title("📊 Admin Dashboard — SNO Hiring Cost")
    st.markdown(f"Logged in as **Admin ({st.session_state.user['name']})**")

    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.user = None
            st.rerun()

    # Get all data
    db_data = get_db()
    submissions = db_data["submissions"]

    # ── Tab navigation ──
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📥 View All Submissions", "📈 WoW Summary", "📉 CPFOD/CPO Analysis",
        "🎯 Targets", "👥 Manage Users"
    ])

    # ── TAB 1: All Submissions ──
    with tab1:
        st.subheader("All Weekly Submissions")

        if submissions:
            weeks = sorted(set(s["week_label"] for s in submissions), reverse=True)
            sel_week = st.selectbox("Select Week", weeks)

            # Group by channel for selected week
            channel_data = {}
            for s in submissions:
                if s["week_label"] == sel_week:
                    ch = s.get("channel", "Unknown")
                    if ch not in channel_data:
                        channel_data[ch] = {}
                    channel_data[ch][s.get("metric", "")] = s.get("value", 0)

            for ch, data in channel_data.items():
                with st.expander(f"{ch} — {sel_week}"):
                    df = pd.DataFrame([
                        {"Metric": k.replace("_", " ").title(), "Value": v}
                        for k, v in data.items() if v != 0
                    ])
                    if not df.empty:
                        st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No submissions yet.")

    # ── TAB 2: WoW Summary ──
    with tab2:
        st.subheader("Week-over-Week Summary")

        if len(set(s["week_label"] for s in submissions)) < 2:
            st.info("Need at least 2 weeks of data for WoW comparison.")
        else:
            weeks = sorted(set(s["week_label"] for s in submissions), reverse=True)
            this_week = weeks[0]
            prev_week = weeks[1]

            st.markdown(f"**Comparing:** {this_week} vs {prev_week}")

            def get_merged(week):
                merged = {}
                for s in submissions:
                    if s["week_label"] == week:
                        merged[s.get("metric", "")] = merged.get(s.get("metric", ""), 0) + (s.get("value", 0) or 0)
                return merged

            data_this = get_merged(this_week)
            data_prev = get_merged(prev_week)

            # Key metrics calculation
            tc_key = lambda d: sum(d.get(k, 0) for k in [
                "cost_flatpay", "cost_leakage", "cost_shouldering",
                "cost_jb", "cost_agency", "cost_google_supper",
                "cost_google_im_app", "cost_insurance", "cost_ob_fee",
                "cost_bgv_fresh", "cost_sms_fresh", "cost_whatsapp_fresh",
                "cost_fr_salary", "cost_fr_tl_salary", "cost_btl",
                "cost_fr_incentive", "cost_influencer_payout",
                "cost_inf_tl_salary",
            ])
            tf_key = lambda d: sum(d.get(k, 0) for k in [
                "transact_ref", "transact_google", "transact_ssu",
                "transact_fr", "transact_agency", "transact_influencers"
            ])

            def make_row(name, fn):
                tv = fn(data_this)
                pv = fn(data_prev)
                delta = tv - pv
                pct = ((tv - pv) / pv * 100) if pv else 0
                return {
                    "Metric": name,
                    this_week: round(tv, 0),
                    prev_week: round(pv, 0),
                    "Change": round(delta, 0),
                    "Change %": f"{pct:+.1f}%",
                }

            rows_table = [
                make_row("Total SNO Cost", tc_key),
                make_row("Total SNO FOD (Same Week)", tf_key),
            ]

            # CPFOD
            cpfod_t = round(tc_key(data_this) / max(tf_key(data_this), 1))
            cpfod_p = round(tc_key(data_prev) / max(tf_key(data_prev), 1))
            rows_table.append({
                "Metric": "Blended SNO CPFOD",
                this_week: cpfod_t,
                prev_week: cpfod_p,
                "Change": cpfod_t - cpfod_p,
                "Change %": f"{((cpfod_t - cpfod_p) / max(cpfod_p, 1) * 100):+.1f}%" if cpfod_p else "-",
            })

            df_wow = pd.DataFrame(rows_table)
            st.dataframe(df_wow, use_container_width=True, hide_index=True)

            # Charts
            if submissions:
                all_weeks = sorted(set(s["week_label"] for s in submissions))
                trend = []
                for wk in all_weeks:
                    d = get_merged(wk)
                    trend.append({
                        "Week": wk,
                        "Total SNO Cost (Lakhs)": round(tc_key(d) / 100000, 2),
                        "Blended CPFOD": round(tc_key(d) / max(tf_key(d), 1)),
                    })

                if trend:
                    df_trend = pd.DataFrame(trend)
                    fig1 = px.line(df_trend, x="Week", y="Total SNO Cost (Lakhs)", markers=True,
                                  title="SNO Cost Trend")
                    st.plotly_chart(fig1, use_container_width=True)

                    fig2 = px.line(df_trend, x="Week", y="Blended CPFOD", markers=True,
                                  title="CPFOD Trend")
                    st.plotly_chart(fig2, use_container_width=True)

    # ── TAB 3: CPFOD/CPO Analysis ──
    with tab3:
        st.subheader("📉 CPFOD / CPO Incremental Analysis")

        if len(set(s["week_label"] for s in submissions)) >= 2:
            weeks = sorted(set(s["week_label"] for s in submissions), reverse=True)
            col_a, col_b = st.columns(2)
            with col_a:
                w1 = st.selectbox("Base Week", weeks, index=0, key="cpfod1")
            with col_b:
                rest = [w for w in weeks if w != w1]
                w2 = st.selectbox("Compare Week", rest, index=0 if rest else 0, key="cpfod2")

            if w2:
                d1 = get_merged(w1)
                d2 = get_merged(w2)

                channels = ["Referral", "Google", "Agency", "FR", "SSU Direct"]
                ch_keys = ["transact_ref", "transact_google", "transact_agency", "transact_fr", "transact_ssu"]

                analysis = []
                for ch, key in zip(channels, ch_keys):
                    fod1 = d1.get(key, 0)
                    fod2 = d2.get(key, 0)
                    # Use a simple cost proxy
                    cost1 = d1.get("cost_jb", 0) + d1.get("cost_agency", 0) + d1.get("cost_google_supper", 0)
                    cost2 = d2.get("cost_jb", 0) + d2.get("cost_agency", 0) + d2.get("cost_google_supper", 0)

                    cpfod1 = round(cost1 / max(fod1, 1))
                    cpfod2 = round(cost2 / max(fod2, 1))

                    analysis.append({
                        "Channel": ch,
                        f"FOD {w1}": int(fod1),
                        f"FOD {w2}": int(fod2),
                        "FOD Delta": int(fod2 - fod1),
                        "Direction": "🔺 Increased" if (cpfod2 - cpfod1) > 0 else ("🔻 Decreased" if (cpfod2 - cpfod1) < 0 else "➡️ Flat"),
                    })

                df_cpfod = pd.DataFrame(analysis)
                st.dataframe(df_cpfod, use_container_width=True, hide_index=True)
        else:
            st.info("Need at least 2 weeks of data.")

    # ── TAB 4: Targets ──
    with tab4:
        st.subheader("Set Plan & Expected Targets")
        st.info("Target setting available in local SQLite mode. For cloud, targets are stored in the Google Sheet.")

    # ── TAB 5: Manage Users ──
    with tab5:
        st.subheader("Manage Channel Owners")

        if USE_GSHEETS:
            st.info("User management is via Google Sheet in cloud mode.")
            st.markdown("""
            **To add users in cloud mode:**
            1. Share the Google Sheet with them
            2. Have them submit data with their name as channel
            3. Or switch to local SQLite mode for full user management
            """)
        else:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            st.markdown("**Add New User**")
            new_name = st.text_input("Channel Owner Name")
            new_pass = st.text_input("Set Passcode", type="password")
            make_admin = st.checkbox("Make Admin")

            if st.button("Create User", use_container_width=True):
                if new_name and new_pass:
                    try:
                        c.execute("INSERT INTO channels (name, passcode, is_admin) VALUES (?,?,?)",
                                  (new_name, make_passcode(new_pass), 1 if make_admin else 0))
                        conn.commit()
                        st.success(f"✅ User '{new_name}' created!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error(f"User '{new_name}' already exists.")
                else:
                    st.error("Please enter name and passcode.")

            st.markdown("---")
            st.markdown("**Existing Users**")
            c.execute("SELECT name, is_admin FROM channels")
            users = c.fetchall()
            conn.close()
            if users:
                df_users = pd.DataFrame(users, columns=["Name", "Is Admin"])
                df_users["Role"] = df_users["Is Admin"].apply(lambda x: "Admin" if x else "Channel")
                st.dataframe(df_users[["Name", "Role"]], use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════
def main():
    if not st.session_state.logged_in:
        login_page()
    elif st.session_state.is_admin:
        admin_dashboard()
    else:
        submission_form()

if __name__ == "__main__":
    main()