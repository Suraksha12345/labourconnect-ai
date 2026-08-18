import streamlit as st
import pandas as pd
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

import firebase_admin
from firebase_admin import credentials, firestore
from cryptography.fernet import Fernet
import os
from dotenv import load_dotenv

load_dotenv()

GOVT_ID_ENCRYPTION_KEY = os.environ.get("GOVT_ID_ENCRYPTION_KEY", "")
_fernet = Fernet(GOVT_ID_ENCRYPTION_KEY.encode()) if GOVT_ID_ENCRYPTION_KEY else None

def decrypt_govt_id(encrypted_id):
    if not _fernet or not encrypted_id:
        return "—"
    try:
        return _fernet.decrypt(encrypted_id.encode()).decode()
    except Exception:
        return "Unable to decrypt"
    
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
    workers = []
    for doc in db.collection('workers').stream():
        w = doc.to_dict()
        w['_id'] = doc.id
        workers.append(w)

    contractors = []
    for doc in db.collection('contractors').stream():
        c = doc.to_dict()
        c['_id'] = doc.id
        contractors.append(c)

    jobs = [doc.to_dict() for doc in db.collection('jobs').stream()]

    reports = []
    for doc in db.collection('reports').stream():
        r = doc.to_dict()
        r['_id'] = doc.id
        reports.append(r)

    return workers, contractors, jobs, reports

workers, contractors, jobs, reports = load_data()


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

# ================================================
# FRAUD REPORTS
# ================================================
st.subheader("🚩 Fraud / Suspicious Job Reports")

if reports:
    pending_reports = [r for r in reports if not r.get('reviewedByAdmin')]
    reviewed_reports = [r for r in reports if r.get('reviewedByAdmin')]

    st.write(f"**{len(pending_reports)} pending** · {len(reviewed_reports)} reviewed")

    if pending_reports:
        for r in pending_reports:
            with st.container(border=True):
                col_a, col_b = st.columns([4, 1])
                with col_a:
                    st.markdown(f"**{r.get('jobTitle', 'Untitled job') or 'Untitled job'}**")
                    st.caption(f"Reason: {r.get('reason', 'No reason given')}")
                    st.caption(f"Reported at: {r.get('reportedAt', '—')}")
                with col_b:
                    if st.button("✅ Mark Reviewed", key=f"review_{r['_id']}"):
                        db.collection('reports').document(r['_id']).update({'reviewedByAdmin': True})
                        st.cache_data.clear()
                        st.rerun()
                    if st.button("🗑️ Remove Job", key=f"remove_{r['_id']}"):
                        job_id = r.get('jobId', '')
                        if job_id:
                            try:
                                response = requests.post(
                                    "http://localhost:5000/actions/remove-job",
                                    json={"jobId": job_id, "reportId": r['_id']},
                                    headers={"X-API-Key": "LC_MangaloreLabour_9x7k2m"},
                                )
                                result = response.json()
                                if result.get("success"):
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(f"Could not remove job: {result.get('error', 'Unknown error')}")
                            except Exception as e:
                                st.error(f"Error calling backend: {e}")
                        else:
                            st.error("This report has no jobId (submitted before the fix) — cannot safely remove the job. Mark it reviewed manually instead.")
    else:
        st.info("No pending reports — all caught up!")

    if reviewed_reports:
        with st.expander(f"View {len(reviewed_reports)} reviewed reports"):
            reviewed_df = pd.DataFrame(reviewed_reports)
            display_cols = [c for c in ['jobTitle', 'reason', 'reportedAt'] if c in reviewed_df.columns]
            st.dataframe(reviewed_df[display_cols], use_container_width=True, hide_index=True)
else:
    st.info("No reports submitted yet.")

st.divider()

# ================================================
# KYC REVIEW
# ================================================
st.subheader("🪪 KYC Review")

kyc_pending = []
for w in workers:
    if w.get('kycStatus') == 'pending_review':
        kyc_pending.append({**w, '_collection': 'workers'})
for c in contractors:
    if c.get('kycStatus') == 'pending_review':
        kyc_pending.append({**c, '_collection': 'contractors'})

if kyc_pending:
    st.write(f"**{len(kyc_pending)} pending review**")
    for p in kyc_pending:
        with st.container(border=True):
            col_a, col_b = st.columns([4, 1])
            with col_a:
                st.markdown(f"**{p.get('name', 'Unknown') or 'Unknown'}** ({p['_collection'][:-1]})")
                st.caption(f"Phone: {p.get('phone', '—')}")
                st.caption(f"Govt ID: {decrypt_govt_id(p.get('govtIdEncrypted', ''))}")
            with col_b:
                if st.button("✅ Verify", key=f"verify_{p['_id']}"):
                    try:
                        response = requests.post(
                            "http://localhost:5000/actions/kyc-decision",
                            json={"collection": p['_collection'], "docId": p['_id'], "decision": "verified"},
                            headers={"X-API-Key": "LC_MangaloreLabour_9x7k2m"},
                        )
                        result = response.json()
                        if result.get("success"):
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(f"Could not verify: {result.get('error', 'Unknown error')}")
                    except Exception as e:
                        st.error(f"Error calling backend: {e}")
                if st.button("🚩 Flag", key=f"flag_{p['_id']}"):
                    try:
                        response = requests.post(
                            "http://localhost:5000/actions/kyc-decision",
                            json={"collection": p['_collection'], "docId": p['_id'], "decision": "flagged"},
                            headers={"X-API-Key": "LC_MangaloreLabour_9x7k2m"},
                        )
                        result = response.json()
                        if result.get("success"):
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(f"Could not flag: {result.get('error', 'Unknown error')}")
                    except Exception as e:
                        st.error(f"Error calling backend: {e}")
else:
    st.info("No KYC submissions pending review.")

st.divider()
st.caption(
    "Note: AI Wage Advisor and Safety Check results are computed live in the "
    "Flutter app and aren't saved to Firestore yet, so they don't appear here. "
    "That can be added later by logging each AI result to a new collection."
)