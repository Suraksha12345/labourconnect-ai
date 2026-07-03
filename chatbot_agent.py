"""
Chatbot Agent - MCP + Groq (Layer 4)
Uses MCP tools to fetch worker profile, government schemes, and jobs
from Firestore, then passes that real data to Groq for a helpful reply.
Tulu pre-written responses are unchanged.
"""

import os
import json
from dotenv import load_dotenv
from groq import Groq
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import asyncio

from mcp_connection import MCP_PYTHON, MCP_SERVER_SCRIPT

load_dotenv()
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

CHATBOT_ROLE = "LabourConnect Chatbot Agent"

CHATBOT_BACKSTORY = (
    "You are a friendly, helpful assistant inside LabourConnect, an app "
    "that helps daily wage workers in rural Karnataka find jobs. "
    "You can help with anything the worker asks. Keep answers short, "
    "simple, and practical. Always reply in the SAME language the "
    "worker used to ask the question."
)

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
    if any(w in message for w in ["ವೇತನ", "ಕೂಲಿ", "ಪಗಾರ್"]):
        return "wage_check"
    if any(w in message for w in ["ನೋಂದಣಿ", "ರಿಜಿಸ್ಟರ್"]):
        return "registration"
    if any(w in message for w in ["ಕೆಲಸ ಬೋಡು", "ಕೆಲಸ", "ಉದ್ಯೋಗ"]):
        return "job_search"
    return None


def _detect_intent(message):
    """Quickly detect what kind of data the chatbot might need."""
    msg = message.lower()
    if any(w in msg for w in ["job", "work", "ಕೆಲಸ", "काम", "mason", "painter"]):
        return "jobs"
    if any(w in msg for w in ["scheme", "benefit", "insurance", "pension",
                               "welfare", "government", "ಸರ್ಕಾರ", "योजना"]):
        return "schemes"
    if any(w in msg for w in ["my skill", "my profile", "registered",
                               "my name", "my location", "ನನ್ನ", "मेरा"]):
        return "profile"
    return "general"


async def _fetch_chatbot_data_via_mcp(intent, worker_phone="", skill="", location=""):
    """Fetch relevant data from Firestore via MCP based on what the worker asked."""
    server_params = StdioServerParameters(
        command=MCP_PYTHON,
        args=[MCP_SERVER_SCRIPT],
        env=os.environ.copy(),
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            if intent == "jobs":
                result = await session.call_tool(
                    "list_jobs",
                    arguments={"skill": skill, "location": location}
                )
                return {"jobs": json.loads(result.content[0].text) if result.content else []}

            elif intent == "schemes":
                result = await session.call_tool(
                    "get_government_schemes",
                    arguments={"query": ""}
                )
                return {"schemes": json.loads(result.content[0].text) if result.content else []}

            elif intent == "profile" and worker_phone:
                result = await session.call_tool(
                    "get_worker_profile",
                    arguments={"phone": worker_phone}
                )
                return {"profile": json.loads(result.content[0].text) if result.content else {}}

            return {}


def chat_with_worker(worker_message, language="auto", worker_phone=""):
    """
    Chatbot Agent: detects intent, fetches relevant real data via MCP
    tools, then passes that context to Groq for a helpful reply.
    Tulu pre-written responses are checked first (unchanged).
    """
    if language == "Tulu":
        intent = detect_tulu_intent(worker_message)
        if intent and intent in TULU_RESPONSES:
            return TULU_RESPONSES[intent]

    # Detect what data we need
    intent = _detect_intent(worker_message)

    # Fetch real data from Firestore via MCP
    mcp_context = ""
    try:
        data = asyncio.run(_fetch_chatbot_data_via_mcp(
            intent=intent,
            worker_phone=worker_phone,
        ))

        if "jobs" in data and data["jobs"]:
            jobs = data["jobs"][:3]  # Top 3 most relevant
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
    except Exception:
        pass  # If MCP fetch fails, just answer from general knowledge

    prompt = worker_message
    if mcp_context:
        prompt = f"{mcp_context}\nWorker's question: {worker_message}"

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": CHATBOT_BACKSTORY},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    print(f"Agent: {CHATBOT_ROLE}")

    print("\nTEST 1: English job search")
    print(chat_with_worker("Are there any mason jobs near Mangalore?", language="English"))

    print("\nTEST 2: English schemes question")
    print(chat_with_worker("Is there any insurance scheme for workers?", language="English"))

    print("\nTEST 3: Tulu (pre-written)")
    print(chat_with_worker("ಎಂಕ್ ಕೆಲಸ ಬೋಡು", language="Tulu"))