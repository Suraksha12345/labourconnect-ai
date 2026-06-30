"""
Job Matching Agent - CrewAI + MCP (Layer 4)
Fetches its own job data via the list_jobs MCP tool, now including
optional wage range and worker experience context, then ranks the
best matches for this worker.
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

        experience_note = (
            f"This worker has {worker_experience} years of experience - "
            f"factor this in when judging fit."
            if worker_experience else
            "No experience info was given for this worker."
        )

        task = Task(
            description=(
                f"A worker with skill '{worker_skill}' located in "
                f"'{worker_location}' is looking for work. {experience_note} "
                f"Call the list_jobs tool exactly ONCE, passing "
                f"skill='{worker_skill}', location='{worker_location}', "
                f"min_wage={min_wage}, max_wage={max_wage}. The tool "
                f"already handles fallback internally if there's no "
                f"exact match - do not call it again. Then rank the jobs "
                f"it returns in 2-4 short bullet points, briefly "
                f"explaining why each fits. If the returned jobs don't "
                f"match the worker's exact skill or wage range, clearly "
                f"say so and explain why you're still suggesting them."
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