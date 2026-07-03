"""
Safety Check Agent - MCP + Groq (Layer 4)
Uses MCP tools to fetch contractor history and job reports from
Firestore, then passes that data to Groq for fraud analysis.
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

SAFETY_BACKSTORY = (
    "You are a fraud detection expert for daily wage job postings in "
    "rural Karnataka. You look for warning signs: unrealistic wages, "
    "upfront payment requests, vague locations, urgency language, "
    "and any history of reports against this contractor. Always give "
    "a numeric Trust Score from 0 to 100, where 100 = completely safe "
    "and 0 = certainly fraudulent. Reply in this EXACT format:\n"
    "TRUST SCORE: [number]\nVERDICT: [SAFE or SUSPICIOUS]\nREASON: [1-2 sentences]"
)


async def _fetch_safety_data_via_mcp(job_title, contractor_phone, contractor_name):
    """Fetch contractor history and reports from Firestore via MCP tools."""
    server_params = StdioServerParameters(
        command=MCP_PYTHON,
        args=[MCP_SERVER_SCRIPT],
        env=os.environ.copy(),
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            history = await session.call_tool(
                "get_contractor_history",
                arguments={
                    "contractor_phone": contractor_phone,
                    "contractor_name": contractor_name,
                }
            )
            reports = await session.call_tool(
                "get_job_reports",
                arguments={
                    "job_title": job_title,
                    "contractor_phone": contractor_phone,
                }
            )

            history_data = json.loads(history.content[0].text) if history.content else {}
            reports_data = json.loads(reports.content[0].text) if reports.content else {}
            return history_data, reports_data


def check_job_safety(job_title, job_description, wage, location,
                     contractor_phone="", contractor_name=""):
    """
    Safety Check Agent: fetches contractor history and reports via MCP,
    then asks Groq to assign a trust score.
    """
    try:
        history_data, reports_data = asyncio.run(
            _fetch_safety_data_via_mcp(job_title, contractor_phone, contractor_name)
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
    except Exception:
        history_context = "Contractor history unavailable."
        reports_context = "Report data unavailable."

    prompt = (
        f"Job Title: {job_title}\n"
        f"Location: {location}\n"
        f"Wage: {wage}\n"
        f"Description: {job_description}\n"
        f"Contractor history: {history_context}\n"
        f"Community reports: {reports_context}\n\n"
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
    print("Safety Check Agent (MCP + Groq)")
    print(check_job_safety(
        job_title="5 Masons needed",
        job_description="Need 5 masons for 2-storey construction. Daily payment.",
        wage="500", location="Konaje, Mangalore",
    ))