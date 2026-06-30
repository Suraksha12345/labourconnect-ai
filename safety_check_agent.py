"""
Safety Check Agent — now powered by CrewAI + MCP (Layer 4)
=============================================================
Previously this agent only analyzed the text of a single job posting.
Now it has two MCP tools: get_contractor_history (have they posted
suspicious wages before?) and get_job_reports (has anyone reported
this job/contractor?) — grounding the trust score in real patterns,
not just this one posting's wording.
"""

from dotenv import load_dotenv
from crewai import Agent, Task, Crew
from crewai_tools import MCPServerAdapter

from mcp_connection import mcp_server_params

load_dotenv()


def check_job_safety(job_title, job_description, wage, location,
                      contractor_phone="", contractor_name=""):
    """
    Safety Check Agent — analyzes a job posting for fraud risk,
    using contractor history and prior reports via MCP tools.
    Returns text in the same TRUST SCORE / VERDICT / REASON format
    as before, so app.py's existing regex parsing keeps working.
    """
    with MCPServerAdapter(mcp_server_params) as tools:
        agent = Agent(
            role="Safety Check Agent",
            goal="Detect fraud patterns in job postings and assign a trust score",
            backstory=(
                "You are a fraud detection expert for daily wage job "
                "postings in rural Karnataka. You look for warning signs "
                "in the posting text itself (unrealistic wages, upfront "
                "payment requests, vague locations, urgency language), "
                "AND you use get_contractor_history to check this "
                "contractor's past postings for patterns, and "
                "get_job_reports to check if this job or contractor has "
                "been reported by other workers. You always give a "
                "numeric Trust Score from 0 to 100."
            ),
            tools=tools,
            llm="groq/llama-3.3-70b-versatile",
            verbose=True,
        )

        task = Task(
            description=(
                f"Analyze this job posting for fraud risk:\n"
                f"Job Title: {job_title}\n"
                f"Location: {location}\n"
                f"Wage offered: {wage}\n"
                f"Description: {job_description}\n\n"
                f"Call get_contractor_history once with "
                f"contractor_phone='{contractor_phone}' and "
                f"contractor_name='{contractor_name}' to check this "
                f"contractor's past postings. Call get_job_reports once "
                f"with job_title='{job_title}' and "
                f"contractor_phone='{contractor_phone}' to check for any "
                f"reports against this job or contractor. Combine these "
                f"with your own analysis of the posting text. Respond in "
                f"this EXACT format:\n"
                f"TRUST SCORE: [number from 0-100]\n"
                f"VERDICT: [SAFE or SUSPICIOUS]\n"
                f"REASON: [1-2 sentence explanation mentioning any "
                f"relevant history or reports found]"
            ),
            agent=agent,
            expected_output=(
                "Exactly three lines: TRUST SCORE, VERDICT, REASON, in "
                "that format."
            ),
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=True)
        result = crew.kickoff()
        return str(result)


if __name__ == "__main__":
    print("\n🤖 Agent: Safety Check Agent (via MCP)\n")

    print("========= TEST 1: Normal Job =========")
    print(check_job_safety(
        job_title="5 Masons needed",
        job_description="Need 5 experienced masons for a 2-storey house construction. Daily payment, food provided.",
        wage="500",
        location="Konaje, Mangalore",
    ))

    print("\n========= TEST 2: Suspicious Job =========")
    print(check_job_safety(
        job_title="Urgent! Masons needed, huge pay!",
        job_description="Pay 2000 per day! Send 500 registration fee first to confirm your spot. Limited seats, hurry!",
        wage="2000",
        location="Location will be told after payment",
    ))