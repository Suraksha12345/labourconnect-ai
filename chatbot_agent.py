"""
Chatbot Agent - Persistent MCP + Groq (Layer 4 + Layer 5)
Uses a persistent MCP connection (started once at Flask boot) to
fetch jobs/schemes/profile/knowledge — no per-request subprocess
spawn, no reloading the RAG model each call. Tulu pre-written
responses are unchanged.
"""

import os
from dotenv import load_dotenv
from groq import Groq
from mcp_persistent import get_client

load_dotenv()
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

CHATBOT_ROLE = "LabourConnect Chatbot Agent"

TULU_RESPONSES = {
    "job_search": (
        "ಕೆಲಸ ತೂವೆರೆ LabourConnect ಆಪ್‌ದ Home screen ಗ್ ಪೋಲೆ. "
        "ನಿಕುಲೆನ ಕೌಶಲ್ಯೊಗು ಸರಿಯಾಯಿನ ಕೆಲಸೊಲು ಅಲ್ಪ ತೋಜುಂಡು. "
        "ಕೆಲಸೊದ ಮಿತ್ತ್ ಒತ್ತುದು 'Apply' ಮಲ್ಪುಲೆ."
    ),
    "wage_check": (
        "ವೇತನ ಸರಿಯಾಯಿನಾ ಪನ್ಪಿನೆಕ್ ಕೆಲಸೊದ ವಿವರೊಡ್ 'AI Wage Advisor' "
        "ಬಾಕ್ಸ್ ತೂಲೆ. ಅಯಿಡ್ ಸರಿಯಾಯಿನ ವೇತನೊದ ಮಿತೆ ತೋಜುಂಡು."
    ),
    "registration": (
        "ನೋಂದಣಿ ಮಲ್ಪೆರೆ: Worker ಆಯ್ಕೆ ಮಲ್ಪುಲೆ, ನಿಕುಲೆನ ಪೆಸರ್, "
        "ಫೋನ್ ನಂಬರ್, ಊರು ಮತ್ತು ಕೌಶಲ್ಯ ಪಾಡುಲೆ. ಬೊಕ್ಕ 'Register' "
        "ಒತ್ತುಲೆ."
    ),
}


# ════════════════════════════════════════════════════════════
# NAVIGATION INTENT (new — for chatbot-driven page navigation)
# ════════════════════════════════════════════════════════════

NAVIGATION_KEYWORDS = {
    "home": ["home page", "home screen", "go home", "find jobs", "job listings"],
    "my_jobs": ["my jobs", "my applications", "applied jobs", "jobs i applied", "my applied"],
    "ai_help": ["ai help", "chatbot", "assistant page"],
    "profile": ["my profile", "profile page", "my account", "edit profile"],
}

NAVIGATION_TAB_INDEX = {"home": 0, "my_jobs": 1, "ai_help": 2, "profile": 3}


def detect_navigation_intent(message):
    """Returns a tab index (0-3) if the message is asking to navigate
    somewhere in the app, else None."""
    msg = message.lower()
    for target, keywords in NAVIGATION_KEYWORDS.items():
        if any(kw in msg for kw in keywords):
            return NAVIGATION_TAB_INDEX[target]
    return None


def detect_tulu_intent(message):
    if any(w in message for w in ["ವೇತನ", "ಕೂಲಿ", "ಪಗಾರ್"]):
        return "wage_check"
    if any(w in message for w in ["ನೋಂದಣಿ", "ರಿಜಿಸ್ಟರ್"]):
        return "registration"
    if any(w in message for w in ["ಕೆಲಸ ಬೋಡು", "ಕೆಲಸ", "ಉದ್ಯೋಗ"]):
        return "job_search"
    return None


def _detect_intent(message):
    msg = message.lower()
    if any(w in msg for w in ["job", "work", "ಕೆಲಸ", "काम", "mason", "painter"]):
        return "jobs"
    if any(w in msg for w in ["scheme", "benefit", "insurance", "pension",
                               "welfare", "government", "ಸರ್ಕಾರ", "योजना"]):
        return "schemes"
    if any(w in msg for w in ["my skill", "my profile", "registered",
                               "my name", "my location", "ನನ್ನ", "मेरा"]):
        return "profile"
    if any(w in msg for w in ["safety", "safe", "law", "rule", "register",
                               "registration", "policy", "wage law", "minimum wage",
                               "ಸುರಕ್ಷ", "ಕಾನೂನು", "सुरक्षा", "कानून"]):
        return "knowledge"
    return "general"


def _fetch_chatbot_data(intent, worker_phone="", skill="", location="", worker_message=""):
    client = get_client()

    if intent == "jobs":
        jobs = client.call_tool("list_jobs", {"skill": skill, "location": location}) or []
        return {"jobs": jobs}

    elif intent == "schemes":
        schemes = client.call_tool("get_government_schemes", {"query": ""}) or []
        return {"schemes": schemes}

    elif intent == "profile" and worker_phone:
        profile = client.call_tool("get_worker_profile", {"phone": worker_phone}) or {}
        return {"profile": profile}

    elif intent == "knowledge":
        raw_knowledge = client.call_tool("get_safety_knowledge", {
            "query": worker_message, "category": ""
        })
        knowledge_list = raw_knowledge if isinstance(raw_knowledge, list) else [raw_knowledge] if raw_knowledge else []
        return {"knowledge": knowledge_list}

    return {}


def _build_chatbot_backstory(language):
    lang_instruction = (
        f"You MUST reply in {language} — never switch to Kannada, Hindi, or any "
        f"other language, even if the retrieved context or knowledge base content "
        f"is written in a different script. Translate any relevant facts into {language}."
        if language and language.lower() not in ("auto", "")
        else "Reply in the SAME language the worker used to ask the question."
    )
    return (
        "You are a friendly, helpful assistant inside LabourConnect, an app "
        "that helps daily wage workers in rural Karnataka find jobs. "
        "You can help with anything the worker asks. Keep answers short, "
        "simple, and practical. "
        f"{lang_instruction}"
    )


def chat_with_worker(worker_message, language="auto", worker_phone="", return_context=False, return_navigation=False):
    nav_target = detect_navigation_intent(worker_message)

    if language == "Tulu":
        intent = detect_tulu_intent(worker_message)
        if intent and intent in TULU_RESPONSES:
            reply = TULU_RESPONSES[intent]
            if return_navigation:
                return reply, nav_target
            return (reply, "") if return_context else reply

    intent = _detect_intent(worker_message)
    mcp_context = ""

    try:
        data = _fetch_chatbot_data(
            intent=intent, worker_phone=worker_phone, worker_message=worker_message
        )

        if "jobs" in data and data["jobs"]:
            jobs = data["jobs"][:3]
            jobs_text = "\n".join([
                f"- {j['title']} at {j['location']}, ₹{j['wage']}/day"
                for j in jobs
            ])
            mcp_context = f"\nCurrent job postings from LabourConnect:\n{jobs_text}\n"

        elif "schemes" in data and data["schemes"]:
            schemes_text = "\n".join([
                f"- {s['name']}: {s['description'][:100]}..."
                for s in data["schemes"][:3]
            ])
            mcp_context = f"\nGovernment schemes for workers:\n{schemes_text}\n"

        elif "profile" in data and data["profile"].get("found"):
            p = data["profile"]
            mcp_context = (
                f"\nWorker profile: Name={p.get('name')}, "
                f"Skill={p.get('skill')}, Location={p.get('location')}, "
                f"Experience={p.get('experience')} years.\n"
            )

        elif "knowledge" in data and data["knowledge"]:
            knowledge_text = "\n".join([
                f"- [{k['category']}] {k['content'][:150]}..."
                for k in data["knowledge"][:3]
            ])
            mcp_context = f"\nRelevant rules/guidelines:\n{knowledge_text}\n"
    except Exception:
        pass

    prompt = worker_message
    if mcp_context:
        prompt = f"{mcp_context}\nWorker's question: {worker_message}"

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": _build_chatbot_backstory(language)},
            {"role": "user", "content": prompt}
        ]
    )

    reply = response.choices[0].message.content
    if return_navigation:
        return reply, nav_target
    return (reply, mcp_context) if return_context else reply


if __name__ == "__main__":
    get_client().start()
    print(f"Agent: {CHATBOT_ROLE}")

    print("\nTEST 1: English job search")
    print(chat_with_worker("Are there any mason jobs near Mangalore?", language="English"))

    print("\nTEST 2: English schemes question")
    print(chat_with_worker("Is there any insurance scheme for workers?", language="English"))

    print("\nTEST 3: Tulu (pre-written)")
    print(chat_with_worker("ಎಂಕ್ ಕೆಲಸ ಬೋಡು", language="Tulu"))

    print("\nTEST 4: Safety knowledge question")
    print(chat_with_worker("What safety precautions for electrical work?", language="English"))

    print("\nTEST 5: Kannada job search")
    print(chat_with_worker("ಮಂಗಳೂರಿನಲ್ಲಿ ಮೇಸನ್ ಕೆಲಸ ಇದೆಯಾ?", language="Kannada"))

    print("\nTEST 6: Hindi job search")
    print(chat_with_worker("मंगलौर में मिस्त्री का काम है क्या?", language="Hindi"))

    print("\nTEST 7: Navigation intent")
    print(chat_with_worker("take me to my jobs page", language="English", return_navigation=True))