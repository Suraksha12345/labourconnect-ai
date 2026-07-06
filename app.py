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


# ── Health check ──
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "LabourConnect AI backend is running!"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True, use_reloader=False)