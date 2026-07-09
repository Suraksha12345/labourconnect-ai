"""
Wage Advisor Agent - MCP + Groq (Layer 4 + Layer 5)
Uses MCP tools to fetch real wage data from Firestore, plus RAG-based
retrieval of Karnataka minimum wage law, then passes all of it to
Groq for reasoning.
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

_WAGE_BENCHMARKS = {
    "mason": (450, 600), "painter": (400, 550), "plumber": (450, 650),
    "carpenter": (450, 600), "farmer": (300, 450), "loader": (350, 450),
    "electrician": (500, 700), "welder": (500, 650), "driver": (400, 600),
}


async def _fetch_wage_data_via_mcp(skill, location):
    """Fetch benchmark wages, recent postings, and minimum wage law via MCP tools."""
    server_params = StdioServerParameters(
        command=MCP_PYTHON,
        args=[MCP_SERVER_SCRIPT],
        env=os.environ.copy(),
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            benchmark = await session.call_tool(
                "get_wage_data",
                arguments={"skill": skill, "location": location}
            )
            recent = await session.call_tool(
                "get_recent_wages",
                arguments={"skill": skill, "location": location}
            )
            law = await session.call_tool(
                "get_safety_knowledge",
                arguments={
                    "query": f"minimum wage law {skill} Karnataka zone skill category",
                    "category": "laws",
                }
            )

            benchmark_data = json.loads(benchmark.content[0].text) if benchmark.content else {}
            recent_data = json.loads(recent.content[0].text) if recent.content else {}
            raw_law = json.loads(law.content[0].text) if law.content else []
            law_data = raw_law if isinstance(raw_law, list) else [raw_law] if raw_law else []
            return benchmark_data, recent_data, law_data


def check_wage(skill, location, offered_wage):
    try:
        benchmark_data, recent_data, law_data = asyncio.run(
            _fetch_wage_data_via_mcp(skill, location)
        )
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
        f"Is this wage LOW, FAIR, or HIGH? Give a verdict and 2 short sentences explaining why, "
        f"referencing the legal wage structure where relevant."
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
    print("Wage Advisor Agent (MCP + Groq + RAG)")
    print(check_wage("Mason", "Mangalore", 500))