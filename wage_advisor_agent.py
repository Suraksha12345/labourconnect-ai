"""
Wage Advisor Agent — now powered by CrewAI + MCP (Layer 4)
=============================================================
Previously this agent relied entirely on the LLM's general knowledge
of "typical wages." Now it has two MCP tools that pull real data:
get_wage_data (a static benchmark range) and get_recent_wages (actual
wages from currently posted jobs in Firestore) — so its advice is
grounded in real, current postings, not just a guess.
"""

from dotenv import load_dotenv
from crewai import Agent, Task, Crew
from crewai_tools import MCPServerAdapter

from mcp_connection import mcp_server_params

load_dotenv()


def check_wage(skill, location, offered_wage):
    """
    Wage Advisor Agent — checks if an offered wage is fair, using
    both a static benchmark and real recent postings via MCP tools.
    """
    with MCPServerAdapter(mcp_server_params) as tools:
        agent = Agent(
            role="Wage Advisor Agent",
            goal="Tell daily wage workers whether an offered wage is fair for their skill and location",
            backstory=(
                "You are a fair-wage expert for daily labour markets in "
                "rural Karnataka. You use the get_wage_data tool for a "
                "standard benchmark range, and get_recent_wages to check "
                "what real jobs are currently paying for this skill. You "
                "combine both to give grounded, practical advice."
            ),
            tools=tools,
            llm="groq/llama-3.3-70b-versatile",
            verbose=True,
        )

        task = Task(
            description=(
                f"A worker with skill '{skill}' in '{location}' has been "
                f"offered a wage of {offered_wage} rupees per day. Call "
                f"get_wage_data once with this skill and location to get "
                f"the standard benchmark range. Also call get_recent_wages "
                f"once with this skill and location to see what real jobs "
                f"are currently paying. Then judge whether {offered_wage} "
                f"is LOW, FAIR, or HIGH, briefly explaining why using both "
                f"data points. Keep it to 2-3 short sentences."
            ),
            agent=agent,
            expected_output=(
                "A short verdict (LOW/FAIR/HIGH) with 2-3 sentences of "
                "reasoning grounded in the benchmark and recent wage data."
            ),
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=True)
        result = crew.kickoff()
        return str(result)


if __name__ == "__main__":
    print("\n🤖 Agent: Wage Advisor Agent (via MCP)\n")
    print("========= TEST: Mason offered 500/day in Mangalore =========")
    print(check_wage(skill="Mason", location="Mangalore", offered_wage=500))