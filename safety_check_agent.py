"""
Safety Check Agent - Persistent MCP + Groq (Layer 4 + Layer 5)
Uses a persistent MCP connection (started once at Flask boot) to
fetch contractor history, reports, and safety knowledge — no
per-request subprocess spawn, no reloading the RAG model each call.
"""
import os
from dotenv import load_dotenv
from groq import Groq
from mcp_persistent import get_client

load_dotenv()
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

SAFETY_BACKSTORY = (
    "You are a fraud detection expert for daily wage job postings in "
    "rural Karnataka. You look for warning signs: unrealistic wages, "
    "upfront payment requests, vague locations, urgency language, "
    "and any history of reports against this contractor. Always give "
    "a numeric Trust Score from 0 to 100, where 100 = completely safe "
    "and 0 = certainly fraudulent. Reply in this EXACT format:\n"
    "TRUST SCORE: [number]\nVERDICT: [SAFE or SUSPICIOUS]\nREASON: [1-2 sentences]"
)


def _fetch_safety_data(job_title, contractor_phone, contractor_name, job_description=""):
    client = get_client()
    history_data = client.call_tool("get_contractor_history", {
        "contractor_phone": contractor_phone, "contractor_name": contractor_name
    }) or {}
    reports_data = client.call_tool("get_job_reports", {
        "job_title": job_title, "contractor_phone": contractor_phone
    }) or {}
    raw_knowledge = client.call_tool("get_safety_knowledge", {
        "query": f"{job_title} {job_description} safety requirements", "category": "safety"
    })
    knowledge_data = raw_knowledge if isinstance(raw_knowledge, list) else [raw_knowledge] if raw_knowledge else []
    return history_data, reports_data, knowledge_data


def check_job_safety(job_title, job_description, wage, location,
                     contractor_phone="", contractor_name=""):
    try:
        history_data, reports_data, knowledge_data = _fetch_safety_data(
            job_title, contractor_phone, contractor_name, job_description
        )
        history_context = (
            f"Contractor has posted {history_data.get('jobs_posted_count', 0)} "
            f"jobs before on LabourConnect."
        )
        report_count = reports_data.get("report_count", 0)
        reports_context = (
            f"{report_count} suspicious job report(s) filed against this job/contractor."
            if report_count > 0 else
            "No reports filed against this job or contractor."
        )
        if knowledge_data:
            safety_context = "Relevant safety guidelines:\n" + "\n".join(
                f"- {k['content'][:200]}" for k in knowledge_data
            )
        else:
            safety_context = "No specific safety guideline matched this job type."
    except Exception:
        history_context = "Contractor history unavailable."
        reports_context = "Report data unavailable."
        safety_context = "Safety knowledge base unavailable."

    prompt = (
        f"Job Title: {job_title}\n"
        f"Location: {location}\n"
        f"Wage: {wage}\n"
        f"Description: {job_description}\n"
        f"Contractor history: {history_context}\n"
        f"Community reports: {reports_context}\n"
        f"{safety_context}\n\n"
        f"Analyze this job posting for fraud risk."
    )

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SAFETY_BACKSTORY},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    get_client().start()
    print("Safety Check Agent (Persistent MCP + Groq + RAG)")
    print(check_job_safety(
        job_title="5 Masons needed",
        job_description="Need 5 masons for 2-storey construction. Daily payment.",
        wage="500", location="Konaje, Mangalore",
    ))