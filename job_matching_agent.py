"""
Job Matching Agent - CrewAI + MCP (Layer 4)
Fetches its own job data via the list_jobs MCP tool (skill + location
only — wage filtering removed from tool params due to Groq tool-call
limitations with 4+ parameters). Wage context passed via task text.
"""

from dotenv import load_dotenv
from crewai import Agent, Task, Crew
from crewai_tools import MCPServerAdapter

from mcp_connection import mcp_server_params

load_dotenv()


def match_jobs(worker_skill, worker_location, min_wage=0, max_wage=0, worker_experience=""):
    with MCPServerAdapter(mcp_server_params) as tools:
        agent = Agent(
            role="Job Matching Agent",
            goal="Find and rank the best job matches for a daily wage worker in rural Karnataka",
            backstory=(
                "You are an expert at matching daily wage workers to jobs "
                "that fit their skill, location, wage expectations, and "
                "experience level. You use the list_jobs tool to look up "
                "current job postings yourself, then rank them by how "
                "well they fit this specific worker."
            ),
            tools=tools,
            llm="groq/llama-3.3-70b-versatile",
            verbose=True,
        )

        wage_note = ""
        if min_wage and max_wage:
            wage_note = f"The worker prefers wages between {min_wage} and {max_wage} rupees/day. "
        elif min_wage:
            wage_note = f"The worker wants at least {min_wage} rupees/day. "
        elif max_wage:
            wage_note = f"The worker wants at most {max_wage} rupees/day. "

        experience_note = (
            f"This worker has {worker_experience} years of experience. "
            if worker_experience else ""
        )

        task = Task(
            description=(
                f"A worker with skill '{worker_skill}' located in "
                f"'{worker_location}' is looking for work. "
                f"{wage_note}{experience_note}"
                f"Call the list_jobs tool exactly ONCE with "
                f"skill='{worker_skill}' and location='{worker_location}'. "
                f"Do not call it again. Rank the jobs it returns in 2-4 "
                f"short bullet points, briefly explaining why each fits "
                f"considering the worker's skill, location, wage preference, "
                f"and experience. If jobs don't match exactly, say so clearly."
            ),
            agent=agent,
            expected_output=(
                "A short ranked list (2-4 bullet points) of the best "
                "job matches with brief reasoning for each."
            ),
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=True)
        result = crew.kickoff()
        return str(result)


if __name__ == "__main__":
    print("Agent: Job Matching Agent (via MCP)")
    print("TEST: Mason in Mangalore, 3 yrs experience")
    print(match_jobs(
        worker_skill="Mason",
        worker_location="Mangalore",
        min_wage=400,
        max_wage=800,
        worker_experience="3",
    ))