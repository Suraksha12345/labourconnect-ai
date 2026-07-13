from flask import Flask, request, jsonify
import re
import os
import json
import hashlib
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, firestore as fb_firestore

from wage_advisor_agent import check_wage
from job_matching_agent import match_jobs
from safety_check_agent import check_job_safety
from chatbot_agent import chat_with_worker
from mcp_persistent import get_client
get_client().start()

app = Flask(__name__)

# ── Firebase connection (for caching) ──
if not firebase_admin._apps:
    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if service_account_json:
        cred = credentials.Certificate(json.loads(service_account_json))
    else:
        cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

db = fb_firestore.client()

# Cache TTL: 24 hours in seconds
CACHE_TTL_SECONDS = 86400


def _cache_key(*parts):
    """Create a short, safe Firestore document ID from cache key parts."""
    raw = "_".join(str(p).strip().lower() for p in parts)
    return hashlib.md5(raw.encode()).hexdigest()


def _get_cache(collection, key):
    """Return cached value if it exists and hasn't expired, else None."""
    try:
        doc = db.collection(collection).document(key).get()
        if doc.exists:
            data = doc.to_dict()
            cached_at = data.get("cached_at")
            if cached_at:
                age = (datetime.now(timezone.utc) - cached_at).total_seconds()
                if age < CACHE_TTL_SECONDS:
                    print(f"[cache HIT] {collection}/{key}")
                    return data.get("value")
    except Exception as e:
        print(f"[cache GET error] {e}")
    return None


def _set_cache(collection, key, value):
    """Save a value to Firestore cache with current timestamp."""
    try:
        db.collection(collection).document(key).set({
            "value": value,
            "cached_at": datetime.now(timezone.utc),
        })
        print(f"[cache SET] {collection}/{key}")
    except Exception as e:
        print(f"[cache SET error] {e}")


# ── Endpoint 1: Wage Advisor (cached) ──
@app.route("/check_wage", methods=["POST"])
def wage_endpoint():
    data = request.get_json()
    skill = data.get("skill") or ""
    location = data.get("location") or ""
    offered_wage = data.get("offered_wage") or 0

    key = _cache_key("wage", skill, location, offered_wage)
    cached = _get_cache("cache_wage", key)
    if cached:
        return jsonify({"result": cached, "cached": True})

    result = check_wage(skill=skill, location=location, offered_wage=offered_wage)
    _set_cache("cache_wage", key, result)
    return jsonify({"result": result, "cached": False})


# ── Endpoint 2: Job Matching (NOT cached — personalized per worker) ──
@app.route("/match_jobs", methods=["POST"])
def job_matching_endpoint():
    data = request.get_json()
    result = match_jobs(
        worker_skill=data.get("worker_skill"),
        worker_location=data.get("worker_location"),
        min_wage=data.get("min_wage", 0) or 0,
        max_wage=data.get("max_wage", 0) or 0,
        worker_experience=data.get("worker_experience", "") or "",
    )
    return jsonify({"result": result})


# ── Endpoint 3: Safety Check (cached) ──
@app.route("/check_safety", methods=["POST"])
def safety_endpoint():
    data = request.get_json()
    job_title = data.get("job_title") or ""
    job_description = data.get("job_description") or ""
    wage = data.get("wage") or ""
    location = data.get("location") or ""
    contractor_phone = data.get("contractor_phone", "") or ""
    contractor_name = data.get("contractor_name", "") or ""

    # Cache key: job title + wage + location (description intentionally excluded
    # since two identical jobs may have slightly different wording but same risk)
    key = _cache_key("safety", job_title, wage, location)
    cached = _get_cache("cache_safety", key)
    if cached:
        return jsonify({**cached, "cached": True})

    raw_result = check_job_safety(
        job_title=job_title,
        job_description=job_description,
        wage=wage,
        location=location,
        contractor_phone=contractor_phone,
        contractor_name=contractor_name,
    )

    score_match = re.search(r'TRUST SCORE:\s*(\d+)', raw_result)
    verdict_match = re.search(r'VERDICT:\s*(SAFE|SUSPICIOUS)', raw_result, re.IGNORECASE)
    reason_match = re.search(r'REASON:\s*(.+)', raw_result, re.DOTALL)

    result = {
        "trust_score": int(score_match.group(1)) if score_match else 70,
        "verdict": verdict_match.group(1).upper() if verdict_match else "SAFE",
        "reason": reason_match.group(1).strip() if reason_match else raw_result.strip()
    }

    _set_cache("cache_safety", key, result)
    return jsonify({**result, "cached": False})


# ── Endpoint 4: Chatbot (NOT cached — personalized per worker/message) ──
@app.route("/chat", methods=["POST"])
def chat_endpoint():
    try:
        data = request.get_json(force=True)
        message = (data.get("message") or "").strip()
        language = data.get("language") or "auto"
        worker_phone = data.get("worker_phone", "") or ""

        if not message:
            return jsonify({"reply": "Please type a message."})

        reply = chat_with_worker(
            worker_message=message,
            language=language,
            worker_phone=worker_phone
        )

        if not reply:
            reply = "Sorry, I didn't quite get that. Could you ask again?"

        return jsonify({"reply": reply})

    except Exception as e:
        print(f"[/chat] ERROR: {e}")
        return jsonify({"reply": "Sorry, I'm having trouble right now. Please try again in a moment."}), 200



# ── Endpoint 5: Job Expiry (called by n8n on a schedule) ──
@app.route("/api/jobs/expire", methods=["POST"])
def expire_jobs():
    from datetime import timedelta

    EXPIRY_DAYS = 7  # jobs older than this and still open get expired
    dry_run = request.args.get("dry_run", "false").lower() == "true"

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=EXPIRY_DAYS)
        jobs_ref = db.collection("jobs")
        jobs = jobs_ref.stream()

        expired_count = 0
        would_expire_titles = []

        for job in jobs:
            job_data = job.to_dict()

            if job_data.get("status") == "expired":
                continue

            posted_at_str = job_data.get("postedAt")
            if not posted_at_str:
                continue

            try:
                posted_at = datetime.fromisoformat(posted_at_str)
                if posted_at.tzinfo is None:
                    posted_at = posted_at.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            if posted_at < cutoff:
                if dry_run:
                    would_expire_titles.append(job_data.get("title", "Untitled"))
                else:
                    job.reference.update({"status": "expired"})
                expired_count += 1

        print(f"[job expiry] dry_run={dry_run} → {expired_count} jobs {'would be' if dry_run else ''} expired")

        return jsonify({
            "success": True,
            "dry_run": dry_run,
            "expired_count": expired_count,
            "would_expire_titles": would_expire_titles if dry_run else None
        })

    except Exception as e:
        print(f"[/api/jobs/expire] ERROR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Endpoint 6: Government Scheme Reminder (called by n8n on a schedule) ──
@app.route("/api/schemes/remind", methods=["POST"])
def scheme_reminder():
    dry_run = request.args.get("dry_run", "false").lower() == "true"

    try:
        workers = db.collection("workers").stream()

        reminder_text = (
            "Reminder: You may be eligible for KBOCWWB welfare schemes "
            "(e.g. education assistance, medical aid). Open AI Help and "
            "ask about government schemes to check your eligibility."
        )

        notified_count = 0
        notified_names = []

        for worker in workers:
            worker_data = worker.to_dict()
            phone = worker_data.get("phone", "")
            name = worker_data.get("name", "Worker")

            if not phone:
                continue

            if not dry_run:
                db.collection("notifications").add({
                    "workerPhone": phone,
                    "type": "scheme_reminder",
                    "message": reminder_text,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "read": False,
                })

            notified_count += 1
            notified_names.append(name)

        print(f"[scheme reminder] dry_run={dry_run} → {notified_count} workers")

        return jsonify({
            "success": True,
            "dry_run": dry_run,
            "notified_count": notified_count,
            "notified_names": notified_names if dry_run else None
        })

    except Exception as e:
        print(f"[/api/schemes/remind] ERROR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ── Endpoint 7: Feedback Collection Trigger (called by n8n on a schedule) ──
@app.route("/api/jobs/request-feedback", methods=["POST"])
def request_feedback():
    dry_run = request.args.get("dry_run", "false").lower() == "true"

    try:
        completed_jobs = db.collection("jobs").where("status", "==", "completed").stream()

        requested_count = 0
        requested_titles = []

        for job in completed_jobs:
            job_data = job.to_dict()
            job_id = job.id
            job_title = job_data.get("title", "Untitled")

            if job_data.get("feedbackRequested"):
                continue

            applications = db.collection("applications").where("jobId", "==", job_id).where("status", "==", "completed").stream()

            for app_doc in applications:
                app_data = app_doc.to_dict()
                worker_phone = app_data.get("workerPhone", "")
                if not worker_phone:
                    continue

                if not dry_run:
                    db.collection("notifications").add({
                        "workerPhone": worker_phone,
                        "type": "feedback_request",
                        "message": f"How was your experience with '{job_title}'? Tap to share feedback.",
                        "jobId": job_id,
                        "createdAt": datetime.now(timezone.utc).isoformat(),
                        "read": False,
                    })

            if not dry_run:
                job.reference.update({"feedbackRequested": True})

            requested_count += 1
            requested_titles.append(job_title)

        print(f"[feedback request] dry_run={dry_run} → {requested_count} jobs")

        return jsonify({
            "success": True,
            "dry_run": dry_run,
            "requested_count": requested_count,
            "requested_titles": requested_titles if dry_run else None
        })

    except Exception as e:
        print(f"[/api/jobs/request-feedback] ERROR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Endpoint 8: Job Notification to Matching Workers (called by n8n on a schedule) ──
@app.route("/api/jobs/notify-matches", methods=["POST"])
def notify_matching_workers():
    dry_run = request.args.get("dry_run", "false").lower() == "true"

    try:
        jobs = db.collection("jobs").stream()
        all_workers = list(db.collection("workers").stream())

        notified_total = 0
        matched_summary = []

        for job in jobs:
            job_data = job.to_dict()

            # Skip jobs already announced, or expired/completed ones
            if job_data.get("notifiedMatches"):
                continue
            if job_data.get("status") in ("expired", "completed"):
                continue

            job_skill = (job_data.get("skill") or "").strip().lower()
            job_title = job_data.get("title", "Untitled")
            if not job_skill:
                continue

            matched_workers = []
            for worker in all_workers:
                worker_data = worker.to_dict()
                worker_skills = worker_data.get("skills", [])
                if not isinstance(worker_skills, list):
                    continue

                normalized_skills = [str(s).strip().lower() for s in worker_skills]
                if job_skill in normalized_skills:
                    matched_workers.append(worker_data.get("phone", ""))

            if matched_workers:
                if not dry_run:
                    for phone in matched_workers:
                        if not phone:
                            continue
                        db.collection("notifications").add({
                            "workerPhone": phone,
                            "type": "job_match",
                            "message": f"New job matching your skills: '{job_title}'. Check it out!",
                            "jobId": job.id,
                            "createdAt": datetime.now(timezone.utc).isoformat(),
                            "read": False,
                        })
                    job.reference.update({"notifiedMatches": True})

                notified_total += len(matched_workers)
                matched_summary.append(f"{job_title} → {len(matched_workers)} workers")

        print(f"[job match notify] dry_run={dry_run} → {notified_total} notifications")

        return jsonify({
            "success": True,
            "dry_run": dry_run,
            "notified_total": notified_total,
            "matched_summary": matched_summary if dry_run else None
        })

    except Exception as e:
        print(f"[/api/jobs/notify-matches] ERROR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    

# ── Endpoint 9: KYC Scan (format validation + duplicate check) ──
@app.route("/api/kyc/scan", methods=["POST"])
def kyc_scan():
    dry_run = request.args.get("dry_run", "false").lower() == "true"

    try:
        aadhaar_pattern = re.compile(r'^\d{4}\s?\d{4}\s?\d{4}$')
        pan_pattern = re.compile(r'^[A-Z]{5}\d{4}[A-Z]$')
        dl_pattern = re.compile(r'^[A-Z]{2}\d{2}\s?\d{4,11}$')

        def id_format_valid(govt_id):
            cleaned = govt_id.strip().upper()
            if aadhaar_pattern.match(cleaned):
                return True
            if pan_pattern.match(cleaned):
                return True
            if dl_pattern.match(cleaned):
                return True
            return False

        workers = list(db.collection("workers").stream())
        contractors = list(db.collection("contractors").stream())

        # Build a map of govtId -> list of (collection, doc_id, phone) to find duplicates
        id_map = {}
        all_people = []

        for doc in workers:
            data = doc.to_dict()
            govt_id = (data.get("govtId") or "").strip()
            all_people.append(("workers", doc.id, data, govt_id))
            if govt_id:
                id_map.setdefault(govt_id, []).append(("workers", doc.id))

        for doc in contractors:
            data = doc.to_dict()
            govt_id = (data.get("govtId") or "").strip()
            all_people.append(("contractors", doc.id, data, govt_id))
            if govt_id:
                id_map.setdefault(govt_id, []).append(("contractors", doc.id))

        flagged_count = 0
        pending_count = 0
        summary = []

        for collection_name, doc_id, data, govt_id in all_people:
            # Skip if already reviewed (verified or already flagged) to avoid re-processing every run
            if data.get("kycStatus") in ("verified", "flagged"):
                continue

            phone = data.get("phone", "")
            name = data.get("name", "Unknown")

            is_duplicate = govt_id and len(id_map.get(govt_id, [])) > 1
            is_valid_format = govt_id and id_format_valid(govt_id)

            if not govt_id:
                new_status = "flagged"
                reason = "No government ID provided"
            elif is_duplicate:
                new_status = "flagged"
                reason = "Duplicate ID detected"
            elif not is_valid_format:
                new_status = "flagged"
                reason = "Invalid ID format"
            else:
                new_status = "pending_review"
                reason = "Format valid, awaiting admin verification"

            if not dry_run:
                db.collection(collection_name).document(doc_id).update({"kycStatus": new_status})
                if phone:
                    db.collection("notifications").add({
                        "workerPhone": phone,
                        "type": "kyc_update",
                        "message": f"KYC status update: {reason}." if new_status == "flagged"
                                   else "Your KYC documents are under review.",
                        "createdAt": datetime.now(timezone.utc).isoformat(),
                        "read": False,
                    })

            if new_status == "flagged":
                flagged_count += 1
            else:
                pending_count += 1

            summary.append(f"{name} ({collection_name}) → {new_status}: {reason}")

        print(f"[kyc scan] dry_run={dry_run} → {pending_count} pending, {flagged_count} flagged")

        return jsonify({
            "success": True,
            "dry_run": dry_run,
            "pending_count": pending_count,
            "flagged_count": flagged_count,
            "summary": summary if dry_run else None
        })

    except Exception as e:
        print(f"[/api/kyc/scan] ERROR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ── Health check ──
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "LabourConnect AI backend is running!"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True, use_reloader=False)