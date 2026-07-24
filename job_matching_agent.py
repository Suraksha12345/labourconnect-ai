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
                f"Do not call it again.\n\n"
                f"The list_jobs tool already applies skill-equivalence matching "
                f"internally (e.g. it treats 'Mason' and 'Masonry' as the same "
                f"real-world skill). If the tool returns any jobs, treat them as "
                f"genuine skill matches — do NOT reject or second-guess a job just "
                f"because its skill string isn't character-identical to the "
                f"worker's skill string. Trust the tool's filtering.\n\n"
                f"IMPORTANT: Only recommend jobs that the tool actually returned "
                f"AND that genuinely match the worker's skill '{worker_skill}' and "
                f"location '{worker_location}'. Do NOT invent, assume, or suggest "
                f"any job that wasn't in the tool's result, and do NOT recommend jobs "
                f"with a clearly different skill or location just to have something to say.\n\n"
                f"If the tool returns no jobs, or none of the returned jobs genuinely "
                f"match this worker's skill and location, respond with exactly this: "
                f"'No matching jobs are currently available for {worker_skill} in "
                f"{worker_location}. Please check back later.' Do not add fabricated "
                f"job listings in this case.\n\n"
                f"Otherwise, rank the genuinely matching jobs in 2-4 short bullet "
                f"points, briefly explaining why each fits considering the worker's "
                f"skill, location, wage preference, and experience."
            ),
            agent=agent,
            expected_output=(
                "Either a short ranked list (2-4 bullet points) of genuinely matching "
                "jobs with brief reasoning, OR a clear statement that no matching jobs "
                "are currently available — never fabricated job listings."
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