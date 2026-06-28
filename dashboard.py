import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# ================================================
# PAGE CONFIG
# ================================================
st.set_page_config(
    page_title="LabourConnect — AI Dashboard",
    page_icon="🛠️",
    layout="wide"
)

# ================================================
# FIREBASE CONNECTION
# (cached so it only connects once per session,
#  not on every button click / interaction)
# ================================================
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        cred = credentials.Certificate("serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
    return firestore.client()

try:
    db = init_firebase()
except Exception as e:
    st.error(
        "Could not connect to Firebase. Make sure `serviceAccountKey.json` "
        "is in the same folder as this script.\n\n"
        f"Error: {e}"
    )
    st.stop()

# ================================================
# DATA LOADING
# (cached for 60 seconds so the dashboard doesn't
#  hit Firestore on every single rerun)
# ================================================
@st.cache_data(ttl=60)
def load_data():
    workers = [doc.to_dict() for doc in db.collection('workers').stream()]
    contractors = [doc.to_dict() for doc in db.collection('contractors').stream()]
    jobs = [doc.to_dict() for doc in db.collection('jobs').stream()]
    return workers, contractors, jobs

workers, contractors, jobs = load_data()


def parse_date_str(value):
    """Firestore stores these as ISO8601 strings (from Dart's
    DateTime.now().toIso8601String()). Parse safely, return None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except (ValueError, TypeError):
        return None


# ================================================
# HEADER
# ================================================
st.title("🛠️ LabourConnect — AI Agent Dashboard")
st.caption("Live data from Firestore · auto-refreshes every 60 seconds")

if st.button("🔄 Refresh now"):
    st.cache_data.clear()
    st.rerun()

st.divider()

# ================================================
# TOP-LEVEL METRICS
# ================================================
today = datetime.now().date()
jobs_today = sum(1 for j in jobs if parse_date_str(j.get('postedAt')) == today)
workers_today = sum(1 for w in workers if parse_date_str(w.get('registeredAt')) == today)

col1, col2, col3, col4 = st.columns(4)
col1.metric("👷 Registered Workers", len(workers), f"+{workers_today} today" if workers_today else None)
col2.metric("🏗️ Registered Contractors", len(contractors))
col3.metric("📋 Jobs Posted", len(jobs), f"+{jobs_today} today" if jobs_today else None)

avg_wage = None
if jobs:
    wage_values = []
    for j in jobs:
        try:
            wage_values.append(int(str(j.get('wage', '0')).strip()))
        except ValueError:
            pass
    if wage_values:
        avg_wage = sum(wage_values) // len(wage_values)
col4.metric("💰 Average Wage Offered", f"₹{avg_wage}/day" if avg_wage else "—")

st.divider()

# ================================================
# CHARTS — ROW 1: Skills breakdown
# ================================================
left, right = st.columns(2)

with left:
    st.subheader("Workers by Skill")
    if workers:
        df = pd.DataFrame(workers)
        if 'skill' in df.columns:
            skill_counts = df['skill'].replace('', 'Not specified').value_counts()
            st.bar_chart(skill_counts)
        else:
            st.info("No skill data found.")
    else:
        st.info("No workers registered yet.")

with right:
    st.subheader("Jobs by Skill Required")
    if jobs:
        df = pd.DataFrame(jobs)
        if 'skill' in df.columns:
            job_skill_counts = df['skill'].replace('', 'Not specified').value_counts()
            st.bar_chart(job_skill_counts)
        else:
            st.info("No skill data found.")
    else:
        st.info("No jobs posted yet.")

# ================================================
# CHARTS — ROW 2: Locations
# ================================================
left2, right2 = st.columns(2)

with left2:
    st.subheader("Workers by Location")
    if workers:
        df = pd.DataFrame(workers)
        if 'location' in df.columns:
            loc_counts = df['location'].replace('', 'Not specified').value_counts().head(10)
            st.bar_chart(loc_counts)
    else:
        st.info("No workers registered yet.")

with right2:
    st.subheader("Jobs by Location")
    if jobs:
        df = pd.DataFrame(jobs)
        if 'location' in df.columns:
            job_loc_counts = df['location'].replace('', 'Not specified').value_counts().head(10)
            st.bar_chart(job_loc_counts)
    else:
        st.info("No jobs posted yet.")

st.divider()

# ================================================
# RECENT ACTIVITY TABLES
# ================================================
st.subheader("📋 Recently Posted Jobs")
if jobs:
    jobs_df = pd.DataFrame(jobs)
    display_cols = [c for c in ['title', 'skill', 'location', 'wage', 'startDate', 'postedAt'] if c in jobs_df.columns]
    if 'postedAt' in jobs_df.columns:
        jobs_df = jobs_df.sort_values('postedAt', ascending=False)
    st.dataframe(jobs_df[display_cols].head(10), use_container_width=True, hide_index=True)
else:
    st.info("No jobs posted yet.")

st.subheader("👷 Recently Registered Workers")
if workers:
    workers_df = pd.DataFrame(workers)
    display_cols = [c for c in ['name', 'skill', 'location', 'experience', 'registeredAt'] if c in workers_df.columns]
    if 'registeredAt' in workers_df.columns:
        workers_df = workers_df.sort_values('registeredAt', ascending=False)
    st.dataframe(workers_df[display_cols].head(10), use_container_width=True, hide_index=True)
else:
    st.info("No workers registered yet.")

st.subheader("🏗️ Recently Registered Contractors")
if contractors:
    contractors_df = pd.DataFrame(contractors)
    display_cols = [c for c in ['name', 'company', 'location', 'workType', 'registeredAt'] if c in contractors_df.columns]
    if 'registeredAt' in contractors_df.columns:
        contractors_df = contractors_df.sort_values('registeredAt', ascending=False)
    st.dataframe(contractors_df[display_cols].head(10), use_container_width=True, hide_index=True)
else:
    st.info("No contractors registered yet.")

st.divider()
st.caption(
    "Note: AI Wage Advisor and Safety Check results are computed live in the "
    "Flutter app and aren't saved to Firestore yet, so they don't appear here. "
    "That can be added later by logging each AI result to a new collection."
)