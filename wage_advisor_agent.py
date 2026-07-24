"""
Wage Advisor Agent - Persistent MCP + Groq (Layer 4 + Layer 5)
Uses a persistent MCP connection (started once at Flask boot) to
fetch wage data and minimum wage law — no per-request subprocess
spawn, no reloading the RAG model each call.
"""
import os
from dotenv import load_dotenv
from groq import Groq
from mcp_persistent import get_client

load_dotenv()
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

_WAGE_BENCHMARKS = {
    "mason": (450, 600), "painter": (400, 550), "plumber": (450, 650),
    "carpenter": (450, 600), "farmer": (300, 450), "loader": (350, 450),
    "electrician": (500, 700), "welder": (500, 650), "driver": (400, 600),
}


def _fetch_wage_data(skill, location):
    """Fetch benchmark wages, recent postings, and minimum wage law via persistent MCP."""
    client = get_client()
    benchmark_data = client.call_tool("get_wage_data", {
        "skill": skill, "location": location
    }) or {}
    recent_data = client.call_tool("get_recent_wages", {
        "skill": skill, "location": location
    }) or {}
    raw_law = client.call_tool("get_safety_knowledge", {
        "query": f"minimum wage law {skill} Karnataka zone skill category",
        "category": "laws",
    })
    law_data = raw_law if isinstance(raw_law, list) else [raw_law] if raw_law else []
    return benchmark_data, recent_data, law_data


def check_wage(skill, location, offered_wage):
    try:
        benchmark_data, recent_data, law_data = _fetch_wage_data(skill, location)
    except Exception:
        key = skill.strip().lower()
        low, high = _WAGE_BENCHMARKS.get(key, (350, 550))
        benchmark_data = {"benchmark_low": low, "benchmark_high": high}
        recent_data = {"count": 0}
        law_data = []

    recent_context = ""
    if recent_data.get("count", 0) > 0:
        recent_context = (
            f"Recent job postings on LabourConnect show: "
            f"average ₹{recent_data['average_wage']}/day, "
            f"range ₹{recent_data['min_wage']}–₹{recent_data['max_wage']}/day "
            f"across {recent_data['count']} postings."
        )
    else:
        recent_context = "No recent postings found on LabourConnect for this skill/location."

    if law_data:
        law_context = "Relevant Karnataka minimum wage law:\n" + "\n".join(
            f"- {l['content'][:200]}" for l in law_data
        )
    else:
        law_context = "No specific minimum wage law reference matched."

    prompt = (
        f"A {skill} worker in {location} has been offered ₹{offered_wage}/day.\n"
        f"Standard benchmark range: ₹{benchmark_data.get('benchmark_low', 350)}–"
        f"₹{benchmark_data.get('benchmark_high', 550)}/day.\n"
        f"{recent_context}\n"
        f"{law_context}\n\n"
        f"Respond in EXACTLY this format:\n"
        f"VERDICT: LOW, FAIR, or HIGH\n"
        f"REASON: 2 short sentences explaining why, referencing the legal wage "
        f"structure where relevant."
    )

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are a fair-wage advisor for daily labour markets in rural Karnataka."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    get_client().start()
    print("Wage Advisor Agent (Persistent MCP + Groq + RAG)")
    print(check_wage("Mason", "Mangalore", 500))