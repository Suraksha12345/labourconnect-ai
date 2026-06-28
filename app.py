from flask import Flask, request, jsonify
import re
from wage_advisor_agent import check_wage
from job_matching_agent import match_jobs
from safety_check_agent import check_job_safety
from chatbot_agent import chat_with_worker

app = Flask(__name__)

# ─── Endpoint 1: Wage Advisor ───
@app.route("/check_wage", methods=["POST"])
def wage_endpoint():
    data = request.get_json()
    result = check_wage(
        skill=data.get("skill"),
        location=data.get("location"),
        offered_wage=data.get("offered_wage")
    )
    return jsonify({"result": result})

# ─── Endpoint 2: Job Matching ───
@app.route("/match_jobs", methods=["POST"])
def job_matching_endpoint():
    data = request.get_json()
    result = match_jobs(
        worker_skill=data.get("worker_skill"),
        worker_location=data.get("worker_location"),
        
    )
    return jsonify({"result": result})

# ─── Endpoint 3: Safety Check ───
@app.route("/check_safety", methods=["POST"])
def safety_endpoint():
    data = request.get_json()
    raw_result = check_job_safety(
        job_title=data.get("job_title"),
        job_description=data.get("job_description"),
        wage=data.get("wage"),
        location=data.get("location")
    )

    score_match = re.search(r'TRUST SCORE:\s*(\d+)', raw_result)
    verdict_match = re.search(r'VERDICT:\s*(SAFE|SUSPICIOUS)', raw_result, re.IGNORECASE)
    reason_match = re.search(r'REASON:\s*(.+)', raw_result, re.DOTALL)

    return jsonify({
        "trust_score": int(score_match.group(1)) if score_match else 70,
        "verdict": verdict_match.group(1).upper() if verdict_match else "SAFE",
        "reason": reason_match.group(1).strip() if reason_match else raw_result.strip()
    })

# ─── Endpoint 4: Chatbot ───
@app.route("/chat", methods=["POST"])
def chat_endpoint():
    try:
        data = request.get_json(force=True)
        message = (data.get("message") or "").strip()
        language = data.get("language") or "auto"

        if not message:
            return jsonify({"reply": "Please type a message."})

        reply = chat_with_worker(worker_message=message, language=language)

        if not reply:
            reply = "Sorry, I didn't quite get that. Could you ask again?"

        return jsonify({"reply": reply})

    except Exception as e:
        print(f"[/chat] ERROR: {e}")
        return jsonify({"reply": "Sorry, I'm having trouble right now. Please try again in a moment."}), 200

# ─── Health check ───
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "LabourConnect AI backend is running!"})

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True, use_reloader=False)