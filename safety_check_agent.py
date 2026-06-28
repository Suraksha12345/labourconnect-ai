import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# ─── Agent definition ───
SAFETY_AGENT_ROLE = "Safety Check Agent"
SAFETY_AGENT_GOAL = "Detect fraud patterns in job postings and assign a trust score"
SAFETY_AGENT_BACKSTORY = (
    "You are a fraud detection expert specializing in daily wage job "
    "postings in rural Karnataka. You look for warning signs such as: "
    "wages that are unrealistically high for the skill, requests for "
    "upfront payment or fees from workers, vague or missing job "
    "locations, urgent pressure language, and missing contractor "
    "details. You always give a numeric Trust Score from 0 to 100, "
    "where 100 means completely safe and 0 means certainly fraudulent."
)

def check_job_safety(job_title, job_description, wage, location):
    """
    Safety Check Agent — analyzes a job posting and returns a trust score.
    """
    task_description = (
        f"Job Title: {job_title}\n"
        f"Location: {location}\n"
        f"Wage offered: {wage}\n"
        f"Description: {job_description}\n\n"
        f"Analyze this job posting for fraud risk. "
        f"Respond in this exact format:\n"
        f"TRUST SCORE: [number from 0-100]\n"
        f"VERDICT: [SAFE or SUSPICIOUS]\n"
        f"REASON: [1-2 sentence explanation]"
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SAFETY_AGENT_BACKSTORY},
            {"role": "user", "content": task_description}
        ]
    )

    return response.choices[0].message.content

# ─── Test it directly when this file is run ───
if __name__ == "__main__":
    print(f"\n🤖 Agent: {SAFETY_AGENT_ROLE}")
    print(f"Task: Check a normal job posting\n")

    result1 = check_job_safety(
        job_title="5 Masons needed",
        job_description="Need 5 experienced masons for a 2-storey house construction. Daily payment, food provided.",
        wage="₹500/day",
        location="Konaje, Mangalore"
    )
    print("========= TEST 1: Normal Job =========")
    print(result1)

    print(f"\n🤖 Agent: {SAFETY_AGENT_ROLE}")
    print(f"Task: Check a suspicious job posting\n")

    result2 = check_job_safety(
        job_title="Urgent! Masons needed, huge pay!",
        job_description="Pay ₹2000 per day! Send ₹500 registration fee first to confirm your spot. Limited seats, hurry!",
        wage="₹2000/day",
        location="Location will be told after payment"
    )
    print("========= TEST 2: Suspicious Job =========")
    print(result2)