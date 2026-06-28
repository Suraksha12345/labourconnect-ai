import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# ─── Agent definition ───
CHATBOT_ROLE = "LabourConnect Chatbot Agent"
CHATBOT_BACKSTORY = (
    "You are a friendly, helpful assistant for LabourConnect, an app "
    "that helps daily wage workers in rural Karnataka find jobs. "
    "Workers may ask about finding jobs, checking if a wage is fair, "
    "registration steps, or general help. Keep your answers short, "
    "simple, and practical. Always reply in the SAME language the "
    "worker used to ask the question."
)

# ─── Pre-written Tulu answers for common questions ───
# (Tulu has very little AI training data, so we use verified
#  human-written translations instead of relying on the AI model)
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

def detect_tulu_intent(message):
    """
    Simple keyword check to find what the worker is asking about,
    so we can use a verified Tulu answer instead of risking an
    AI-generated one that may default to Kannada.
    """
    message_lower = message.lower()

    job_keywords = ["ಕೆಲಸ ಬೋಡು", "ಕೆಲಸ", "ಉದ್ಯೋಗ"]
    wage_keywords = ["ವೇತನ", "ಕೂಲಿ", "ಪಗಾರ್"]
    register_keywords = ["ನೋಂದಣಿ", "ರಿಜಿಸ್ಟರ್"]

    if any(word in message for word in wage_keywords):
        return "wage_check"
    if any(word in message for word in register_keywords):
        return "registration"
    if any(word in message for word in job_keywords):
        return "job_search"
    return None

def chat_with_worker(worker_message, language="auto"):
    """
    Chatbot Agent — replies to a worker's question.
    For Tulu, checks pre-written answers first (AI has poor Tulu support).
    For all other languages, uses AI directly.
    """
    if language == "Tulu":
        intent = detect_tulu_intent(worker_message)
        if intent and intent in TULU_RESPONSES:
            return TULU_RESPONSES[intent]
        # If we don't recognize the question, fall back to AI
        # (may reply in Kannada — acceptable as last resort)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": CHATBOT_BACKSTORY},
            {"role": "user", "content": worker_message}
        ]
    )
    return response.choices[0].message.content

# ─── Test it directly when this file is run ───
if __name__ == "__main__":
    print(f"\n🤖 Agent: {CHATBOT_ROLE}\n")

    print("========= TEST 1: English =========")
    print("Worker asks: How do I find a mason job near me?")
    print("Reply:", chat_with_worker("How do I find a mason job near me?", language="English"))

    print("\n========= TEST 2: Kannada =========")
    print("Worker asks: ನನಗೆ ಕೆಲಸ ಬೇಕು")
    print("Reply:", chat_with_worker("ನನಗೆ ಕೆಲಸ ಬೇಕು", language="Kannada"))

    print("\n========= TEST 3: Hindi =========")
    print("Worker asks: मुझे काम चाहिए")
    print("Reply:", chat_with_worker("मुझे काम चाहिए", language="Hindi"))

    tulu_tests = [
        ("Job search — phrasing 1", "ಎಂಕ್ ಕೆಲಸ ಬೋಡು"),
        ("Job search — phrasing 2", "ಕೆಲಸ ಎಲ್ಲಿ ತೂವೊಡು?"),
        ("Wage check — phrasing 1", "ಎಂಕ್ ವೇತನ ಸರಿ ಉಂಡಾ ಪನ್ಪಿನ ಗೊತ್ತಾಪುಜಿ"),
        ("Wage check — phrasing 2", "ಕೂಲಿ ಎಷ್ಟು ಸರಿ?"),
        ("Registration", "ಎಂಕ್ ನೋಂದಣಿ ಮಲ್ಪೊಡು"),
        ("Unmatched / random question", "ಎಂಕ್ ಮಲ್ತಿನ ಆಧಾರ್ ಕಾರ್ಡ್ ಬೋಡು"),
    ]

    for label, phrase in tulu_tests:
        print(f"\n========= TEST: {label} =========")
        print(f"Worker asks: {phrase}")
        print("Reply:", chat_with_worker(phrase, language="Tulu"))