"""
Job Matching Agent — now powered by real CrewAI + MCP (Layer 4)
==================================================================
Previously, this agent just received a pre-fetched job list from
Flutter and asked Groq to rank it. Now, it's a real CrewAI Agent that
decides for itself to call the `list_jobs` MCP tool (served by
mcp_server.py) to fetch live job data from Firestore — Flutter no
longer needs to fetch or forward jobs at all.

Setup (one-time, in THIS venv — the main agent venv):
    pip install crewai 'crewai-tools[mcp]'

The MCP server itself runs in a separate venv (dashboard_venv) to
avoid dependency conflicts between firebase-admin and litellm.
"""

import os
import sys
from dotenv import load_dotenv
from crewai import Agent, Task, Crew
from crewai_tools import MCPServerAdapter
from mcp import StdioServerParameters

load_dotenv()

# ── Workaround for a known CrewAI bug (GitHub issue #5886) ──
# CrewAI injects a "cache_breakpoint" property into messages, but only
# the Anthropic provider knows how to strip it before sending. Groq
# (and other OpenAI-compatible providers) reject it outright, causing
# every LLM call to fail with a BadRequestError. This disables that
# injection entirely until CrewAI ships an official fix.
import crewai.llms.cache as _crewai_cache
_crewai_cache.mark_cache_breakpoint = lambda msg: msg

# ── Where mcp_server.py actually runs ──
# Locally on Windows: a SEPARATE venv (dashboard_venv) that has
# firebase-admin, kept apart from this venv to dodge a dependency
# conflict. On a deployed host like Render, everything lives in one
# environment, so this just falls back to whichever Python is
# currently running this script — no manual switching needed.
_LOCAL_DASHBOARD_PYTHON = r"C:\labourconnect_ai\dashboard_venv\Scripts\python.exe"
MCP_PYTHON = _LOCAL_DASHBOARD_PYTHON if os.path.exists(_LOCAL_DASHBOARD_PYTHON) else sys.executable
MCP_SERVER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")

server_params = StdioServerParameters(
    command=MCP_PYTHON,
    args=[MCP_SERVER_SCRIPT],
    env=os.environ.copy(),
)


def match_jobs(worker_skill, worker_location):
    """
    Job Matching Agent — fetches its own job data via the list_jobs
    MCP tool, then ranks the best matches for this worker.
    """
    with MCPServerAdapter(server_params) as tools:
        agent = Agent(
            role="Job Matching Agent",
            goal="Find and rank the best job matches for a daily wage worker in rural Karnataka",
            backstory=(
                "You are an expert at matching daily wage workers to jobs "
                "that fit their skill and location. You use the list_jobs "
                "tool to look up current job postings yourself, then rank "
                "them by how well they fit this specific worker."
            ),
            tools=tools,
            llm="groq/llama-3.3-70b-versatile",
            verbose=True,
        )

        task = Task(
            description=(
                f"A worker with skill '{worker_skill}' located in "
                f"'{worker_location}' is looking for work. Call the "
                f"list_jobs tool exactly ONCE, passing skill='{worker_skill}' "
                f"and location='{worker_location}'. The tool already "
                f"handles fallback internally if there's no exact match "
                f"— do not call it again. Then rank the jobs it returns "
                f"in 2-4 short bullet points, briefly explaining why "
                f"each fits. If the returned jobs don't match the "
                f"worker's exact skill (meaning the tool had to fall "
                f"back), clearly say so and explain why you're still "
                f"suggesting them (e.g. closest location or fair wage)."
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


# ─── Test it directly when this file is run ───
if __name__ == "__main__":
    print("\n🤖 Agent: Job Matching Agent (via MCP)\n")
    print("========= TEST: Mason in Mangalore =========")
    print(match_jobs(worker_skill="Mason", worker_location="Mangalore"))