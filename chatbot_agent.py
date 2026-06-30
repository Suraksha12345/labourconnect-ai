"""
Chatbot Agent — now powered by CrewAI + MCP (Layer 4)
=========================================================
Adds three MCP tools: get_worker_profile, get_government_schemes,
and list_jobs. Tulu pre-written-response logic is UNCHANGED.
"""

from dotenv import load_dotenv
from crewai import Agent, Task, Crew
from crewai_tools import MCPServerAdapter

from mcp_connection import mcp_server_params

load_dotenv()

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


def detect_tulu_intent(message):
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


def chat_with_worker(worker_message, language="auto", worker_phone=""):
    """
    Chatbot Agent — Tulu uses pre-written answers first (unchanged).
    All other languages use a real CrewAI agent with MCP tools.
    """
    if language == "Tulu":
        intent = detect_tulu_intent(worker_message)
        if intent and intent in TULU_RESPONSES:
            return TULU_RESPONSES[intent]

    with MCPServerAdapter(mcp_server_params) as tools:
        agent = Agent(
            role=CHATBOT_ROLE,
            goal="Help daily wage workers with questions about jobs, wages, registration, benefits, or anything else",
            backstory=(
                "You are a friendly, helpful assistant inside "
                "LabourConnect, an app for daily wage workers in rural "
                "Karnataka. You can help with job search (use list_jobs), "
                "questions about the worker's own profile (use "
                "get_worker_profile with their phone number), government "
                "welfare schemes and benefits (use get_government_schemes), "
                "or general questions about anything else. Only call a "
                "tool if the question actually needs that specific data — "
                "for general chit-chat or unrelated questions, answer "
                "directly without calling any tool. Keep answers short, "
                "simple, and practical. Always reply in the SAME language "
                "the worker used to ask the question."
            ),
            tools=tools,
            llm="groq/llama-3.3-70b-versatile",
            verbose=True,
        )

        task = Task(
            description=(
                f"The worker's phone number (for get_worker_profile, if "
                f"needed) is '{worker_phone}'. The worker asked, in "
                f"{language}: \"{worker_message}\"\n\n"
                f"Reply helpfully in the same language they used. Only "
                f"use a tool if the question genuinely requires that "
                f"data. For anything else, just answer directly."
            ),
            agent=agent,
            expected_output="A short, helpful reply in the same language as the question.",
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=True)
        result = crew.kickoff()
        return str(result)


if __name__ == "__main__":
    print(f"\n🤖 Agent: {CHATBOT_ROLE}\n")

    print("========= TEST 1: English job search =========")
    print(chat_with_worker("Are there any mason jobs near Mangalore?", language="English"))

    print("\n========= TEST 2: English profile question =========")
    print(chat_with_worker("What is my registered skill?", language="English", worker_phone="9876543210"))

    print("\n========= TEST 3: English benefits question =========")
    print(chat_with_worker("Is there any insurance scheme for workers like me?", language="English"))

    print("\n========= TEST 4: Tulu (pre-written) =========")
    print(chat_with_worker("ಎಂಕ್ ಕೆಲಸ ಬೋಡು", language="Tulu"))