from flask import Flask, request, jsonify
import re
import os
import json
import hashlib
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

import hashlib
from cryptography.fernet import Fernet

GOVT_ID_ENCRYPTION_KEY = os.environ.get("GOVT_ID_ENCRYPTION_KEY", "")
_fernet = Fernet(GOVT_ID_ENCRYPTION_KEY.encode()) if GOVT_ID_ENCRYPTION_KEY else None


def _hash_govt_id(plain_id):
    normalized = plain_id.strip().upper().replace(" ", "")
    return hashlib.sha256(normalized.encode()).hexdigest()


def _encrypt_govt_id(plain_id):
    if not _fernet:
        raise RuntimeError("GOVT_ID_ENCRYPTION_KEY is not configured")
    return _fernet.encrypt(plain_id.encode()).decode()


def _decrypt_govt_id(encrypted_id):
    if not _fernet:
        raise RuntimeError("GOVT_ID_ENCRYPTION_KEY is not configured")
    return _fernet.decrypt(encrypted_id.encode()).decode()

import firebase_admin
from firebase_admin import credentials, firestore as fb_firestore

from wage_advisor_agent import check_wage
from job_matching_agent import match_jobs
from safety_check_agent import check_job_safety
from chatbot_agent import chat_with_worker
from mcp_persistent import get_client
get_client().start()

app = Flask(__name__)

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

REDIS_URL = os.environ.get("REDIS_URL", "memory://")

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per hour"],
    storage_uri=REDIS_URL,
)

# ── Firebase connection (for caching) ──
if not firebase_admin._apps:
    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if service_account_json:
        cred = credentials.Certificate(json.loads(service_account_json))
    else:
        cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

db = fb_firestore.client()

from functools import wraps

API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "")

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        provided_key = request.headers.get("X-API-Key", "")
        if not API_SECRET_KEY or provided_key != API_SECRET_KEY:
            print(f"[AUTH FAILED] {request.method} {request.path} from {request.remote_addr} at {datetime.now(timezone.utc).isoformat()}")
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

def _safe_error(e, context=""):
    """Log the real error server-side, return a generic message to the client."""
    print(f"[{context}] ERROR: {e}")
    return jsonify({"success": False, "error": "Something went wrong. Please try again."}), 500


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
    try:
        skill = data.get("skill") or ""
        location = data.get("location") or ""
        offered_wage = data.get("offered_wage") or 0

        key = _cache_key("wage", skill, location, offered_wage)
        cached = _get_cache("cache_wage", key)
        if cached:
            return jsonify(cached)

        raw_result = check_wage(skill=skill, location=location, offered_wage=offered_wage)

        verdict_match = re.search(r'VERDICT:\s*(LOW|FAIR|HIGH)', raw_result, re.IGNORECASE)
        reason_match = re.search(r'REASON:\s*(.+)', raw_result, re.DOTALL)

        result = {
            "result": reason_match.group(1).strip() if reason_match else raw_result.strip(),
            "verdict": verdict_match.group(1).upper() if verdict_match else "FAIR",
            "cached": False,
        }

        _set_cache("cache_wage", key, result)
        return jsonify(result)
    except Exception as e:
        return _safe_error(e, "/check_wage")


# ── Endpoint 2: Job Matching (NOT cached — personalized per worker) ──
@app.route("/match_jobs", methods=["POST"])
def job_matching_endpoint():
    try:
        data = request.get_json()
        result = match_jobs(
            worker_skill=data.get("worker_skill"),
            worker_location=data.get("worker_location"),
            min_wage=data.get("min_wage", 0) or 0,
            max_wage=data.get("max_wage", 0) or 0,
            worker_experience=data.get("worker_experience", "") or "",
        )
        return jsonify({"result": result})
    except Exception as e:
        return _safe_error(e, "/match_jobs")


# ── Endpoint 3: Safety Check (cached) ──
@app.route("/check_safety", methods=["POST"])
def safety_endpoint():
    try:
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
    except Exception as e:
        return _safe_error(e, "/check_safety")


# ── Endpoint 4: Chatbot (semantic-cached for schemes/knowledge intents only) ──
@app.route("/chat", methods=["POST"])
@limiter.limit("20 per minute")
def chat_endpoint():
    try:
        data = request.get_json(force=True)
        message = (data.get("message") or "").strip()
        language = data.get("language") or "auto"
        worker_phone = data.get("worker_phone", "") or ""

        if not message:
            return jsonify({"reply": "Please type a message."})

        reply, nav_target, was_cached = chat_with_worker(
            worker_message=message,
            language=language,
            worker_phone=worker_phone,
            return_navigation=True
        )

        if not reply:
            reply = "Sorry, I didn't quite get that. Could you ask again?"

        return jsonify({
            "reply": reply,
            "navigateToTab": nav_target,
            "cached": was_cached,
        })

    except Exception as e:
        print(f"[/chat] ERROR: {e}")
        return jsonify({"reply": "Sorry, I'm having trouble right now. Please try again in a moment."}), 200


# ── Endpoint 5: Job Expiry (called by n8n on a schedule) ──
@app.route("/api/jobs/expire", methods=["POST"])
@require_api_key
def expire_jobs():
    from datetime import timedelta

    POSTED_FALLBACK_DAYS = 7   # fallback: expire this many days after postedAt if startDate is unusable
    START_GRACE_DAYS = 2       # expire this many days after the job's own startDate has passed
    dry_run = request.args.get("dry_run", "false").lower() == "true"

    try:
        now = datetime.now(timezone.utc)
        jobs_ref = db.collection("jobs")
        jobs = jobs_ref.stream()

        expired_count = 0
        would_expire_titles = []

        for job in jobs:
            job_data = job.to_dict()

            if job_data.get("status") in ("expired", "removed", "completed"):
                continue

            should_expire = False

            # Try startDate-based expiry first (DD-MM-YYYY format)
            start_date_str = job_data.get("startDate", "")
            start_date_parsed = None
            if start_date_str:
                try:
                    start_date_parsed = datetime.strptime(start_date_str.strip(), "%d-%m-%Y").replace(tzinfo=timezone.utc)
                except ValueError:
                    start_date_parsed = None

            if start_date_parsed:
                expiry_point = start_date_parsed + timedelta(days=START_GRACE_DAYS)
                if now > expiry_point:
                    should_expire = True
            else:
                # Fallback: no usable startDate, use postedAt + flat window
                posted_at_str = job_data.get("postedAt")
                if posted_at_str:
                    try:
                        posted_at = datetime.fromisoformat(posted_at_str)
                        if posted_at.tzinfo is None:
                            posted_at = posted_at.replace(tzinfo=timezone.utc)
                        cutoff = now - timedelta(days=POSTED_FALLBACK_DAYS)
                        if posted_at < cutoff:
                            should_expire = True
                    except ValueError:
                        pass

            if should_expire:
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
        return _safe_error(e, "/api/jobs/expire")


# ── Endpoint 6: Government Scheme Reminder (called by n8n on a schedule) ──
@app.route("/api/schemes/remind", methods=["POST"])
@require_api_key
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
        return _safe_error(e, "/api/schemes/remind")

# ── Endpoint 7: Feedback Collection Trigger (called by n8n on a schedule) ──
@app.route("/api/jobs/request-feedback", methods=["POST"])
@require_api_key
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
        return _safe_error(e, "/api/jobs/request-feedback")


# ── Endpoint 8: Job Notification to Matching Workers (called by n8n on a schedule) ──
@app.route("/api/jobs/notify-matches", methods=["POST"])
@require_api_key
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
        return _safe_error(e, "/api/jobs/notify-matches")


# ── Endpoint 9: KYC Scan (format validation + duplicate check) ──
@app.route("/api/kyc/scan", methods=["POST"])
@require_api_key
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

        # Build a map of govtIdHash -> list of (collection, doc_id) to find duplicates
        id_map = {}
        all_people = []

        for doc in workers:
            data = doc.to_dict()
            govt_id_hash = (data.get("govtIdHash") or "").strip()
            all_people.append(("workers", doc.id, data, govt_id_hash))
            if govt_id_hash:
                id_map.setdefault(govt_id_hash, []).append(("workers", doc.id))

        for doc in contractors:
            data = doc.to_dict()
            govt_id_hash = (data.get("govtIdHash") or "").strip()
            all_people.append(("contractors", doc.id, data, govt_id_hash))
            if govt_id_hash:
                id_map.setdefault(govt_id_hash, []).append(("contractors", doc.id))

        flagged_count = 0
        pending_count = 0
        summary = []

        for collection_name, doc_id, data, govt_id_hash in all_people:
            if data.get("kycStatus") in ("verified", "flagged"):
                continue

            phone = data.get("phone", "")
            name = data.get("name", "Unknown")
            govt_id_encrypted = (data.get("govtIdEncrypted") or "").strip()

            is_duplicate = govt_id_hash and len(id_map.get(govt_id_hash, [])) > 1

            decrypted_id = ""
            is_valid_format = False
            if govt_id_encrypted:
                try:
                    decrypted_id = _decrypt_govt_id(govt_id_encrypted)
                    is_valid_format = id_format_valid(decrypted_id)
                except Exception as decrypt_error:
                    print(f"[kyc scan] decrypt error for {collection_name}/{doc_id}: {decrypt_error}")
                    is_valid_format = False

            if not govt_id_encrypted:
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
        return _safe_error(e, "/api/kyc/scan")

    
# ── Endpoint 10: Fraud Alert to Admin (called by n8n on a schedule) ──
ADMIN_PHONE = "1234567890"

@app.route("/api/reports/alert-admin", methods=["POST"])
@require_api_key
def alert_admin_of_reports():
    dry_run = request.args.get("dry_run", "false").lower() == "true"

    try:
        reports = db.collection("reports").stream()

        alerted_count = 0
        alerted_summary = []

        for report in reports:
            report_data = report.to_dict()

            if report_data.get("alertSent"):
                continue

            job_title = report_data.get("jobTitle", "Unknown job")
            reason = report_data.get("reason", "No reason given")

            if not dry_run:
                db.collection("notifications").add({
                    "workerPhone": ADMIN_PHONE,
                    "type": "fraud_alert",
                    "message": f"⚠️ New report on '{job_title}': {reason}",
                    "reportId": report.id,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "read": False,
                })
                report.reference.update({"alertSent": True})

            alerted_count += 1
            alerted_summary.append(f"{job_title} — {reason}")

        print(f"[fraud alert] dry_run={dry_run} → {alerted_count} reports alerted")

        return jsonify({
            "success": True,
            "dry_run": dry_run,
            "alerted_count": alerted_count,
            "alerted_summary": alerted_summary if dry_run else None
        })

    except Exception as e:
        return _safe_error(e, "/api/reports/alert-admin")
    
# ── Endpoint 11: Payment Reminder (called by n8n on a schedule) ──
@app.route("/api/payments/remind", methods=["POST"])
@require_api_key
def payment_reminder():
    from datetime import timedelta

    dry_run = request.args.get("dry_run", "false").lower() == "true"
    GRACE_DAYS = 2

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=GRACE_DAYS)
        applications = db.collection("applications").where("status", "==", "completed").stream()

        reminded_count = 0
        reminded_summary = []

        for app_doc in applications:
            app_data = app_doc.to_dict()

            if app_data.get("paid"):
                continue
            if app_data.get("paymentReminderSent"):
                continue

            completed_at_str = app_data.get("completedAt")
            if not completed_at_str:
                continue

            try:
                completed_at = datetime.fromisoformat(completed_at_str)
                if completed_at.tzinfo is None:
                    completed_at = completed_at.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            if completed_at >= cutoff:
                continue  # still within grace period

            job_id = app_data.get("jobId", "")
            job_title = app_data.get("jobTitle", "Untitled job")

            contractor_phone = ""
            if job_id:
                job_doc = db.collection("jobs").document(job_id).get()
                if job_doc.exists:
                    contractor_phone = job_doc.to_dict().get("contractorPhone", "")

            if not contractor_phone:
                continue

            if not dry_run:
                db.collection("notifications").add({
                    "workerPhone": contractor_phone,
                    "type": "payment_reminder",
                    "message": f"Reminder: Payment is pending for '{job_title}'. Please pay the worker if not already done.",
                    "jobId": job_id,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "read": False,
                })
                app_doc.reference.update({"paymentReminderSent": True})

            reminded_count += 1
            reminded_summary.append(f"{job_title} → contractor {contractor_phone}")

        print(f"[payment reminder] dry_run={dry_run} → {reminded_count} reminders")

        return jsonify({
            "success": True,
            "dry_run": dry_run,
            "reminded_count": reminded_count,
            "reminded_summary": reminded_summary if dry_run else None
        })

    except Exception as e:
        return _safe_error(e, "/api/payments/remind")

# ── Endpoint 12: Job Posted Confirmation (Action Layer — called instantly by Flutter after job creation) ──
@app.route("/actions/job-posted", methods=["POST"])
@require_api_key
def job_posted_action():
    try:
        data = request.get_json(force=True)
        job_id = data.get("jobId", "")

        if not job_id:
            return jsonify({"success": False, "error": "jobId is required"}), 400

        job_doc = db.collection("jobs").document(job_id).get()
        if not job_doc.exists:
            return jsonify({"success": False, "error": "Job not found"}), 404

        job_data = job_doc.to_dict()
        contractor_phone = job_data.get("contractorPhone", "")
        job_title = job_data.get("title", "Untitled")

        if not contractor_phone:
            return jsonify({"success": False, "error": "Job has no contractorPhone"}), 400

        db.collection("notifications").add({
            "workerPhone": contractor_phone,
            "type": "job_posted_confirmation",
            "message": f"Your job '{job_title}' is now live and visible to workers.",
            "jobId": job_id,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "read": False,
        })

        print(f"[job posted] confirmation sent to {contractor_phone} for job {job_id}")

        return jsonify({"success": True, "message": "Confirmation notification sent"})

    except Exception as e:
        return _safe_error(e, "/actions/job-posted")

@app.route("/actions/encrypt-govt-id", methods=["POST"])
@require_api_key
def encrypt_govt_id_action():
    try:
        data = request.get_json(force=True)
        plain_id = data.get("govtId", "")

        if not plain_id:
            return jsonify({"success": False, "error": "govtId is required"}), 400

        return jsonify({
            "success": True,
            "govtIdHash": _hash_govt_id(plain_id),
            "govtIdEncrypted": _encrypt_govt_id(plain_id),
        })

    except Exception as e:
        return _safe_error(e, "/actions/encrypt-govt-id")

# ── Endpoint 13: Payment Received (Action Layer — replaces direct client write) ──
def _last10(phone):
    digits = re.sub(r'\D', '', phone or '')
    return digits[-10:] if len(digits) >= 10 else digits


@app.route("/actions/payment-received", methods=["POST"])
@require_api_key
def payment_received_action():
    try:
        data = request.get_json(force=True)
        application_id = data.get("applicationId", "")
        contractor_phone = data.get("contractorPhone", "")

        if not application_id or not contractor_phone:
            return jsonify({"success": False, "error": "applicationId and contractorPhone are required"}), 400

        app_ref = db.collection("applications").document(application_id)
        app_doc = app_ref.get()
        if not app_doc.exists:
            return jsonify({"success": False, "error": "Application not found"}), 404

        app_data = app_doc.to_dict()

        if app_data.get("status") != "completed":
            return jsonify({"success": False, "error": "Application is not marked completed yet"}), 400

        if app_data.get("paid"):
            return jsonify({"success": False, "error": "Payment already marked as received"}), 400

        job_id = app_data.get("jobId", "")
        if not job_id:
            return jsonify({"success": False, "error": "Application has no linked jobId"}), 400

        job_doc = db.collection("jobs").document(job_id).get()
        if not job_doc.exists:
            return jsonify({"success": False, "error": "Linked job not found"}), 404

        job_contractor_phone = job_doc.to_dict().get("contractorPhone", "")

        if _last10(contractor_phone) != _last10(job_contractor_phone):
            return jsonify({"success": False, "error": "You are not the contractor for this job"}), 403

        app_ref.update({
            "paid": True,
            "paidAt": datetime.now(timezone.utc).isoformat(),
        })

        worker_phone = app_data.get("workerPhone", "")
        job_title = app_data.get("jobTitle", "Untitled")
        if worker_phone:
            db.collection("notifications").add({
                "workerPhone": worker_phone,
                "type": "payment_received",
                "message": f"Payment for '{job_title}' has been marked as received.",
                "jobId": job_id,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "read": False,
            })

        print(f"[payment received] application {application_id} marked paid by {contractor_phone}")

        return jsonify({"success": True, "message": "Payment marked as received"})

    except Exception as e:
        return _safe_error(e, "/actions/payment-received")
    
    # ── Endpoint 14: Remove Job (Action Layer — replaces title-matching in dashboard) ──
@app.route("/actions/remove-job", methods=["POST"])
@require_api_key
def remove_job_action():
    try:
        data = request.get_json(force=True)
        job_id = data.get("jobId", "")
        report_id = data.get("reportId", "")

        if not job_id:
            return jsonify({"success": False, "error": "jobId is required"}), 400

        job_ref = db.collection("jobs").document(job_id)
        job_doc = job_ref.get()
        if not job_doc.exists:
            return jsonify({"success": False, "error": "Job not found"}), 404

        job_title = job_doc.to_dict().get("title", "Untitled")

        job_ref.update({"status": "removed"})

        affected_applications = db.collection("applications") \
            .where("jobId", "==", job_id) \
            .stream()

        notified_count = 0
        for app_doc in affected_applications:
            app_data = app_doc.to_dict()
            if app_data.get("status") == "completed":
                continue
            worker_phone = app_data.get("workerPhone", "")
            if not worker_phone:
                continue
            db.collection("notifications").add({
                "workerPhone": worker_phone,
                "type": "job_removed",
                "message": f"The job '{job_title}' has been removed and is no longer active.",
                "jobId": job_id,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "read": False,
            })
            notified_count += 1

        if report_id:
            db.collection("reports").document(report_id).update({"reviewedByAdmin": True})

        print(f"[remove job] job {job_id} removed, {notified_count} workers notified")

        return jsonify({
            "success": True,
            "message": "Job removed",
            "notified_count": notified_count
        })

    except Exception as e:
        return _safe_error(e, "/actions/remove-job")
    

# ── Endpoint 15: Report Submitted (Action Layer — instant admin alert) ──
@app.route("/actions/report-submitted", methods=["POST"])
@require_api_key
def report_submitted_action():
    try:
        data = request.get_json(force=True)
        report_id = data.get("reportId", "")

        if not report_id:
            return jsonify({"success": False, "error": "reportId is required"}), 400

        report_doc = db.collection("reports").document(report_id).get()
        if not report_doc.exists:
            return jsonify({"success": False, "error": "Report not found"}), 404

        report_data = report_doc.to_dict()

        if report_data.get("alertSent"):
            return jsonify({"success": True, "message": "Alert already sent for this report"})

        job_title = report_data.get("jobTitle", "Unknown job")
        reason = report_data.get("reason", "No reason given")

        db.collection("notifications").add({
            "workerPhone": ADMIN_PHONE,
            "type": "fraud_alert",
            "message": f"⚠️ New report on '{job_title}': {reason}",
            "reportId": report_id,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "read": False,
        })
        report_doc.reference.update({"alertSent": True})

        print(f"[report submitted] instant admin alert sent for report {report_id}")

        return jsonify({"success": True, "message": "Admin alerted instantly"})

    except Exception as e:
        return _safe_error(e, "/actions/report-submitted")


# ── Endpoint 16: Registration Complete (Action Layer — instant welcome notification) ──
@app.route("/actions/register-complete", methods=["POST"])
@require_api_key
def register_complete_action():
    try:
        data = request.get_json(force=True)
        phone = data.get("phone", "")
        name = data.get("name", "")
        role = data.get("role", "")  # "worker" or "contractor"

        if not phone or not role:
            return jsonify({"success": False, "error": "phone and role are required"}), 400

        if role == "worker":
            message = f"Welcome to LabourConnect, {name}! Browse jobs matching your skills and apply anytime."
        elif role == "contractor":
            message = f"Welcome to LabourConnect, {name}! Post your first job and AI will help verify it for safety."
        else:
            return jsonify({"success": False, "error": "role must be 'worker' or 'contractor'"}), 400

        db.collection("notifications").add({
            "workerPhone": phone,
            "type": "welcome",
            "message": message,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "read": False,
        })

        print(f"[register complete] welcome notification sent to {phone} ({role})")

        return jsonify({"success": True, "message": "Welcome notification sent"})

    except Exception as e:
        return _safe_error(e, "/actions/register-complete")


# ── Endpoint 17: Application Decision (Action Layer — accept/reject + instant notification) ──
@app.route("/actions/application-decision", methods=["POST"])
@require_api_key
def application_decision_action():
    try:
        data = request.get_json(force=True)
        application_id = data.get("applicationId", "")
        decision = data.get("decision", "")  # "accepted" or "rejected"
        contractor_phone = data.get("contractorPhone", "")

        if not application_id or decision not in ("accepted", "rejected"):
            return jsonify({"success": False, "error": "applicationId and decision ('accepted' or 'rejected') are required"}), 400

        app_ref = db.collection("applications").document(application_id)
        app_doc = app_ref.get()
        if not app_doc.exists:
            return jsonify({"success": False, "error": "Application not found"}), 404

        app_data = app_doc.to_dict()
        job_id = app_data.get("jobId", "")

        if job_id:
            job_doc = db.collection("jobs").document(job_id).get()
            if job_doc.exists:
                job_contractor_phone = job_doc.to_dict().get("contractorPhone", "")
                if _last10(contractor_phone) != _last10(job_contractor_phone):
                    return jsonify({"success": False, "error": "You are not the contractor for this job"}), 403

        app_ref.update({
            "status": decision,
            "decidedAt": datetime.now(timezone.utc).isoformat(),
        })

        worker_phone = app_data.get("workerPhone", "")
        job_title = app_data.get("jobTitle", "Untitled")
        if worker_phone:
            message = (
                f"Good news! Your application for '{job_title}' was accepted."
                if decision == "accepted"
                else f"Your application for '{job_title}' was not selected this time."
            )
            db.collection("notifications").add({
                "workerPhone": worker_phone,
                "type": "application_decision",
                "message": message,
                "jobId": job_id,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "read": False,
            })

        print(f"[application decision] {application_id} → {decision}")

        return jsonify({"success": True, "message": f"Application {decision}"})

    except Exception as e:
        return _safe_error(e, "/actions/application-decision")



@app.route("/actions/application-submitted", methods=["POST"])
@require_api_key
def application_submitted_action():
    try:
        data = request.get_json(force=True)
        application_id = data.get("applicationId", "")

        if not application_id:
            return jsonify({"success": False, "error": "applicationId is required"}), 400

        app_doc = db.collection("applications").document(application_id).get()
        if not app_doc.exists:
            return jsonify({"success": False, "error": "Application not found"}), 404

        app_data = app_doc.to_dict()
        job_id = app_data.get("jobId", "")
        job_title = app_data.get("jobTitle", "Untitled")

        job_doc = db.collection("jobs").document(job_id).get()
        if not job_doc.exists:
            return jsonify({"success": False, "error": "Linked job not found"}), 404

        contractor_phone = job_doc.to_dict().get("contractorPhone", "")
        if not contractor_phone:
            return jsonify({"success": False, "error": "Job has no contractorPhone"}), 400

        db.collection("notifications").add({
            "workerPhone": contractor_phone,
            "type": "new_applicant",
            "message": f"A new worker applied for '{job_title}'. Tap to review applicants.",
            "jobId": job_id,
            "jobTitle": job_title,  
            "applicationId": application_id,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "read": False,
        })

        return jsonify({"success": True, "message": "Contractor notified"})

    except Exception as e:
        return _safe_error(e, "/actions/application-submitted")

@app.route("/actions/mark-notification-read", methods=["POST"])
@require_api_key
def mark_notification_read_action():
    try:
        data = request.get_json(force=True)
        notification_id = data.get("notificationId", "")

        if not notification_id:
            return jsonify({"success": False, "error": "notificationId is required"}), 400

        db.collection("notifications").document(notification_id).update({"read": True})

        return jsonify({"success": True, "message": "Notification marked as read"})

    except Exception as e:
        return _safe_error(e, "/actions/mark-notification-read")

# ── Endpoint 18: KYC Decision (Action Layer — admin approve/reject with instant notification) ──
@app.route("/actions/kyc-decision", methods=["POST"])
@require_api_key
def kyc_decision_action():
    try:
        data = request.get_json(force=True)
        collection_name = data.get("collection", "")  # "workers" or "contractors"
        doc_id = data.get("docId", "")
        decision = data.get("decision", "")  # "verified" or "flagged"

        if collection_name not in ("workers", "contractors") or not doc_id or decision not in ("verified", "flagged"):
            return jsonify({"success": False, "error": "collection ('workers'/'contractors'), docId, and decision ('verified'/'flagged') are required"}), 400

        person_ref = db.collection(collection_name).document(doc_id)
        person_doc = person_ref.get()
        if not person_doc.exists:
            return jsonify({"success": False, "error": "Person not found"}), 404

        person_data = person_doc.to_dict()
        phone = person_data.get("phone", "")

        person_ref.update({"kycStatus": decision})

        if phone:
            message = (
                "Your KYC has been verified by an admin. You now have full access."
                if decision == "verified"
                else "Your KYC was reviewed and flagged. Please check your submitted ID and try again."
            )
            db.collection("notifications").add({
                "workerPhone": phone,
                "type": "kyc_update",
                "message": message,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "read": False,
            })

        print(f"[kyc decision] {collection_name}/{doc_id} → {decision}")

        return jsonify({"success": True, "message": f"KYC marked {decision}"})

    except Exception as e:
        return _safe_error(e, "/actions/kyc-decision")
    

# ── Endpoint 19: Register Device Token (Action Layer — for FCM push notifications) ──
@app.route("/actions/register-device-token", methods=["POST"])
@require_api_key
def register_device_token_action():
    try:
        data = request.get_json(force=True)
        phone = data.get("phone", "")
        fcm_token = data.get("fcmToken", "")

        if not phone or not fcm_token:
            return jsonify({"success": False, "error": "phone and fcmToken are required"}), 400

        digits = re.sub(r'\D', '', phone)
        phone10 = digits[-10:] if len(digits) >= 10 else digits

        updated = False
        for collection_name in ("workers", "contractors"):
            docs = db.collection(collection_name).stream()
            for doc in docs:
                doc_phone = re.sub(r'\D', '', doc.to_dict().get("phone", ""))
                doc_phone10 = doc_phone[-10:] if len(doc_phone) >= 10 else doc_phone
                if doc_phone10 == phone10:
                    doc.reference.update({"fcmToken": fcm_token})
                    updated = True
                    break
            if updated:
                break

        if not updated:
            return jsonify({"success": False, "error": "No worker/contractor found with that phone"}), 404

        print(f"[register device token] token saved for {phone}")

        return jsonify({"success": True, "message": "Device token registered"})

    except Exception as e:
        return _safe_error(e, "/actions/register-device-token")    


# ── Health check ──
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "LabourConnect AI backend is running!"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True, use_reloader=False)