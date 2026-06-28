import os
from dotenv import load_dotenv
from groq import Groq

# Load your Groq API key from .env
load_dotenv()

# Connect directly to Groq (proven to work from test_groq.py)
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# ─── Agent definition (CrewAI-style structure, kept for documentation) ───
WAGE_ADVISOR_ROLE = "Wage Advisor"
WAGE_ADVISOR_GOAL = "Determine if a daily wage is fair for rural Karnataka daily wage workers"
WAGE_ADVISOR_BACKSTORY = (
    "You are an expert in rural Karnataka labour markets. "
    "You know typical daily wages for masons, painters, farmers, "
    "plumbers, electricians and drivers across different districts "
    "like Dakshina Kannada, Udupi, and surrounding areas. "
    "You always give clear, practical advice that protects workers "
    "from being underpaid, while being fair to contractors too."
)

# ─── The actual task execution function ───
def check_wage(skill, location, offered_wage):
    """
    Wage Advisor Agent — checks if an offered daily wage is fair.
    """
    task_description = (
        f"A contractor is offering ₹{offered_wage} per day for a "
        f"{skill} in {location}, Karnataka. "
        f"Is this a fair wage? Give a clear verdict (FAIR or LOW) "
        f"followed by a 1-2 sentence reason, and suggest a fair "
        f"wage range if the offer is too low."
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": WAGE_ADVISOR_BACKSTORY},
            {"role": "user", "content": task_description}
        ]
    )

    return response.choices[0].message.content

# ─── Test it directly when this file is run ───
if __name__ == "__main__":
    print(f"\n🤖 Agent: {WAGE_ADVISOR_ROLE}")
    print(f"Task: Check wage for Mason in Sullia at ₹350/day\n")

    result = check_wage(skill="Mason", location="Sullia", offered_wage=350)

    print("========= FINAL RESULT =========")
    print(result)