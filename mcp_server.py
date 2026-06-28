"""
LabourConnect MCP Server — Layer 4 (Integration)
==================================================
This is a Model Context Protocol (MCP) server. Its job is to expose
LabourConnect's Firestore data as a standardized "tool" that any
MCP-compatible agent can call directly — instead of waiting for the
Flutter app to fetch data and forward it through the Flask API.

This runs as a SEPARATE process from your main CrewAI agent code,
using its own Python environment (the dashboard_venv, which already
has firebase-admin installed). You don't run this file manually —
it's started automatically by job_matching_agent.py via
MCPServerAdapter, which spawns it as a subprocess and talks to it
over stdin/stdout (this is called the "stdio transport").

Setup (one-time, in dashboard_venv):
    dashboard_venv\\Scripts\\activate
    pip install mcp firebase-admin
"""

import firebase_admin
from firebase_admin import credentials, firestore
from mcp.server.fastmcp import FastMCP

# ── Firebase connection ──
# Reuses the same serviceAccountKey.json as dashboard.py
if not firebase_admin._apps:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ── MCP server definition ──
mcp = FastMCP("labourconnect-jobs")


@mcp.tool()
def list_jobs(skill: str = "", location: str = "") -> list[dict]:
    """
    Fetch currently posted jobs from LabourConnect's Firestore database,
    with smart fallback built in — always call this ONCE with both
    skill and location; it handles broadening the search internally
    if there's no exact match, so the agent never needs to call it
    again with different parameters.

    Args:
        skill: The worker's skill (e.g. "Mason"). Empty = all skills.
        location: The worker's location (e.g. "Mangalore"). Empty = all locations.

    Returns:
        A list of job dicts (title, skill, location, wage, startDate).
        Tries an exact skill+location match first; if none exist,
        falls back to location-only matches; if still none, returns
        all posted jobs so there's always something to reason over.
    """
    jobs_ref = db.collection("jobs").stream()
    all_jobs = []

    for doc in jobs_ref:
        data = doc.to_dict()
        all_jobs.append({
            "title": data.get("title", ""),
            "skill": data.get("skill", ""),
            "location": data.get("location", ""),
            "wage": data.get("wage", ""),
            "startDate": data.get("startDate", ""),
        })

    def matches_skill(job):
        return not skill or job["skill"].strip().lower() == skill.strip().lower()

    def matches_location(job):
        return not location or location.strip().lower() in job["location"].strip().lower()

    # 1. Exact skill + location match
    exact = [j for j in all_jobs if matches_skill(j) and matches_location(j)]
    if exact:
        return exact

    # 2. Fallback: location only (skill ignored)
    if location:
        location_only = [j for j in all_jobs if matches_location(j)]
        if location_only:
            return location_only

    # 3. Fallback: everything, so the agent always has something to rank
    return all_jobs


if __name__ == "__main__":
    # stdio transport: communicates over stdin/stdout with whatever
    # process spawned this one (in our case, MCPServerAdapter from
    # job_matching_agent.py running in the main agent venv).
    mcp.run(transport="stdio")