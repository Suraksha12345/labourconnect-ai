"""
LabourConnect MCP Server — Layer 4 (Integration)
==================================================
Exposes LabourConnect's Firestore data as standardized tools that any
MCP-compatible CrewAI agent can call directly, instead of waiting for
Flutter to fetch and forward data through the Flask API.

Tools, grouped by which agent uses them:
  Job Matching   -> list_jobs
  Wage Advisor   -> get_wage_data, get_recent_wages
  Safety Check   -> get_contractor_history, get_job_reports
  Chatbot        -> get_worker_profile, get_government_schemes, list_jobs

Runs as a SEPARATE process from the main CrewAI agent code. Locally on
Windows it runs via dashboard_venv's Python (kept apart from the main
venv to dodge a firebase-admin/litellm dependency conflict). On Render
(or any single-environment host) it just runs via whichever Python
spawned it — see each agent file for the auto-detection logic.
"""

import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from mcp.server.fastmcp import FastMCP
from rag.retriever import search_knowledge_base

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from rag.retriever import search_knowledge_base, _get_db

if not firebase_admin._apps:
    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if service_account_json:
        cred = credentials.Certificate(json.loads(service_account_json))
    else:
        cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()
mcp = FastMCP("labourconnect-tools")


def _last10(raw):
    digits = "".join(c for c in str(raw) if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


# ════════════════════════════════════════════════════════════
# JOB MATCHING AGENT
# ════════════════════════════════════════════════════════════

# Groups of skill terms that should be treated as the same real-world skill,
# since WorkerRegistrationScreen and PostJobScreen use two different vocabularies
# (role names vs. work-category names)
SKILL_GROUPS = [
    {"mason", "masonry", "construction laborer", "construction"},
    {"painter", "painting"},
    {"plumber", "plumbing"},
    {"carpenter", "carpentry"},
    {"farmer", "farming"},
    {"loader", "loading"},
    {"electrician", "electrical"},
    {"welder", "welding"},
    {"driver", "driving"},
    {"cook", "cooking"},
    {"cleaner", "cleaning"},
    {"security guard", "security"},
    {"gardener", "gardening"},
    {"mechanic", "mechanical work"},
    {"tailor", "tailoring"},
    {"housekeeping"},
    {"factory worker", "factory work"},
    {"warehouse worker", "warehouse work"},
    {"helper"},
]


def _skill_group(s: str) -> set:
    """Return the group of equivalent skill terms this string belongs to."""
    s = s.strip().lower()
    for group in SKILL_GROUPS:
        if s in group:
            return group
    return {s}  # unknown skill — only matches itself

@mcp.tool()
def list_jobs(
    skill: str = "",
    location: str = "",
) -> list[dict]:
    """
    Fetch currently posted jobs from Firestore with smart fallback.
    Call this ONCE with skill and location — it handles broadening
    the search internally if there's no exact match, so the agent
    never needs to call it again with different parameters.

    Args:
        skill: The worker's skill (e.g. "Mason"). Empty = all skills.
        location: The worker's location (e.g. "Mangalore"). Empty = all locations.

    Returns:
        A list of job dicts (title, skill, location, wage, startDate).
        Tries exact skill+location match first; falls back to location
        only, then all jobs, so there's always something to reason over.
    """
    jobs_ref = db.collection("jobs").stream()
    all_jobs = []

    for doc in jobs_ref:
        data = doc.to_dict()
        if data.get("status") in ("expired", "removed", "completed"):
            continue
        all_jobs.append({
            "title": data.get("title", ""),
            "skill": data.get("skill", ""),
            "location": data.get("location", ""),
            "wage": data.get("wage", ""),
            "startDate": data.get("startDate", ""),
        })

    def matches_skill(job):
        if not skill:
            return True
        worker_group = _skill_group(skill)
        job_skill = job["skill"].strip().lower()
        return job_skill in worker_group

    def matches_location(job):
        return not location or location.strip().lower() in job["location"].strip().lower()

    exact = [j for j in all_jobs if matches_skill(j) and matches_location(j)]
    if exact:
        return exact

    if location:
        location_only = [j for j in all_jobs if matches_location(j)]
        if location_only:
            return location_only

    return all_jobs


# ════════════════════════════════════════════════════════════
# WAGE ADVISOR AGENT
# ════════════════════════════════════════════════════════════

_WAGE_BENCHMARKS = {
    "mason": (450, 600),
    "painter": (400, 550),
    "plumber": (450, 650),
    "carpenter": (450, 600),
    "farmer": (300, 450),
    "loader": (350, 450),
    "electrician": (500, 700),
    "welder": (500, 650),
    "driver": (400, 600),
}


@mcp.tool()
def get_wage_data(skill: str, location: str = "") -> dict:
    """
    Get the standard/benchmark daily wage range for a skill in this
    region, independent of any specific job posting. Use for a
    general "is this wage fair" baseline.

    Args:
        skill: The skill to look up (e.g. "Mason").
        location: Optional location for context.

    Returns:
        A dict with benchmark_low, benchmark_high (rupees/day).
        Unrecognized skills get a generic fallback range.
    """
    key = skill.strip().lower()
    low, high = _WAGE_BENCHMARKS.get(key, (350, 550))
    return {
        "skill": skill,
        "location": location,
        "benchmark_low": low,
        "benchmark_high": high,
    }


@mcp.tool()
def get_recent_wages(skill: str, location: str = "") -> dict:
    """
    Look up real wages from recently posted jobs in Firestore matching
    this skill (and location, if given). Use alongside get_wage_data
    to ground advice in actual current postings, not just a static
    benchmark.

    Args:
        skill: The skill to look up (e.g. "Mason").
        location: Optional location filter.

    Returns:
        A dict with count, average_wage, min_wage, max_wage (rupees/day).
        count is 0 and wage fields are None if nothing matches.
    """
    jobs_ref = db.collection("jobs").stream()
    wages = []

    for doc in jobs_ref:
        data = doc.to_dict()
        job_skill = (data.get("skill", "") or "").strip().lower()
        job_location = (data.get("location", "") or "").strip().lower()

        if skill and job_skill != skill.strip().lower():
            continue
        if location and location.strip().lower() not in job_location:
            continue

        try:
            wages.append(int(str(data.get("wage", "")).strip()))
        except (ValueError, TypeError):
            continue

    if not wages:
        return {"count": 0, "average_wage": None, "min_wage": None, "max_wage": None}

    return {
        "count": len(wages),
        "average_wage": sum(wages) // len(wages),
        "min_wage": min(wages),
        "max_wage": max(wages),
    }


# ════════════════════════════════════════════════════════════
# SAFETY CHECK AGENT
# ════════════════════════════════════════════════════════════

@mcp.tool()
def get_contractor_history(contractor_phone: str = "", contractor_name: str = "") -> dict:
    """
    Look up a contractor's past job postings, to spot patterns like
    repeated suspiciously high wages or vague locations. Pass
    whichever identifier is available — phone is more reliable.

    Args:
        contractor_phone: The contractor's phone number, if known.
        contractor_name: The contractor's name, if phone isn't available.

    Returns:
        A dict with jobs_posted_count and a list of past job
        titles/wages/locations. jobs_posted_count is 0 if neither
        identifier is given or no match is found.
    """
    if not contractor_phone and not contractor_name:
        return {"jobs_posted_count": 0, "past_jobs": []}

    target_phone = _last10(contractor_phone) if contractor_phone else None
    target_name = contractor_name.strip().lower() if contractor_name else None

    jobs_ref = db.collection("jobs").stream()
    past_jobs = []

    for doc in jobs_ref:
        data = doc.to_dict()
        job_phone = _last10(data.get("contractorPhone", ""))
        job_name = (data.get("contractorName", "") or "").strip().lower()

        matched = (target_phone and job_phone == target_phone) or \
                  (target_name and job_name == target_name)

        if matched:
            past_jobs.append({
                "title": data.get("title", ""),
                "wage": data.get("wage", ""),
                "location": data.get("location", ""),
            })

    return {"jobs_posted_count": len(past_jobs), "past_jobs": past_jobs}


@mcp.tool()
def get_job_reports(job_title: str = "", contractor_phone: str = "") -> dict:
    """
    Check if a job or contractor has been reported as suspicious by
    other workers via the "Report Suspicious Job" button in the app.

    Args:
        job_title: The job title to check reports for, if known.
        contractor_phone: The contractor's phone, if known (broader match).

    Returns:
        A dict with report_count and a list of report reasons.
        report_count is 0 if nothing matches or no reports exist yet.
    """
    reports_ref = db.collection("reports").stream()
    matches = []
    target_phone = _last10(contractor_phone) if contractor_phone else None

    for doc in reports_ref:
        data = doc.to_dict()
        report_title = (data.get("jobTitle", "") or "").strip().lower()
        report_phone = _last10(data.get("contractorPhone", ""))

        title_match = job_title and report_title == job_title.strip().lower()
        phone_match = target_phone and report_phone == target_phone

        if title_match or phone_match:
            matches.append({
                "reason": data.get("reason", ""),
                "reportedAt": data.get("reportedAt", ""),
            })

    return {"report_count": len(matches), "reports": matches}


# ════════════════════════════════════════════════════════════
# CHATBOT AGENT
# ════════════════════════════════════════════════════════════

@mcp.tool()
def get_worker_profile(phone: str) -> dict:
    """
    Look up a worker's own registered profile, so the chatbot can
    answer personalized questions like "what's my skill?" with real
    data instead of generic advice.

    Args:
        phone: The worker's phone number.

    Returns:
        A dict with found, name, skill, location, experience.
        found is False if no matching worker exists.
    """
    target = _last10(phone)
    workers_ref = db.collection("workers").stream()

    for doc in workers_ref:
        data = doc.to_dict()
        if _last10(data.get("phone", "")) == target:
            return {
                "found": True,
                "name": data.get("name", ""),
                "skill": data.get("skill", ""),
                "location": data.get("location", ""),
                "experience": data.get("experience", ""),
            }

    return {"found": False}


_GOVERNMENT_SCHEMES = [
    {
        "name": "Karnataka Building & Other Construction Workers Welfare Board",
        "description": (
            "Registration gives construction workers access to accident "
            "insurance, pension, maternity benefits, and education "
            "assistance for children. Registration is done at the local "
            "Labour Department office with proof of 90 days of "
            "construction work in the past year."
        ),
    },
    {
        "name": "Ayushman Bharat - PM-JAY",
        "description": (
            "Free health insurance coverage up to 5 lakh rupees per "
            "family per year for hospital treatment, available to "
            "eligible low-income households including daily wage workers."
        ),
    },
    {
        "name": "PM Shram Yogi Maandhan",
        "description": (
            "A pension scheme for unorganised sector workers earning up "
            "to 15,000 rupees a month, providing 3,000 rupees monthly "
            "pension after age 60 with small monthly contributions "
            "starting from age 18."
        ),
    },
    {
        "name": "e-Shram Card",
        "description": (
            "A national database registration for unorganised workers, "
            "giving access to various government welfare schemes and "
            "accident insurance coverage of 2 lakh rupees."
        ),
    },
]


@mcp.tool()
def get_government_schemes(query: str = "") -> list[dict]:
    """
    Look up government welfare schemes relevant to daily wage workers
    in Karnataka, for chatbot questions about benefits/insurance/pension.

    Args:
        query: Optional keyword to filter schemes (e.g. "insurance").
               Empty = return all schemes.

    Returns:
        A list of scheme dicts with name and description. If query
        doesn't match anything specific, returns all schemes.
    """
    if not query:
        return _GOVERNMENT_SCHEMES

    q = query.strip().lower()
    matches = [
        s for s in _GOVERNMENT_SCHEMES
        if q in s["name"].lower() or q in s["description"].lower()
    ]
    return matches if matches else _GOVERNMENT_SCHEMES

# ════════════════════════════════════════════════════════════
# KNOWLEDGE BASE / RAG  (used by Safety Check + Chatbot)
# ════════════════════════════════════════════════════════════

@mcp.tool()
def get_safety_knowledge(query: str, category: str = "") -> list[dict]:
    """
    Search LabourConnect's knowledge base (government schemes, labour
    laws, safety guidelines, registration rules, FAQs, and platform
    policies) for content relevant to a question. Use this whenever a
    worker asks something that depends on real rules or facts rather
    than general advice — e.g. wage law, scheme eligibility, safety
    requirements, or registration steps.

    Args:
        query: The worker's question or topic, in plain language
               (e.g. "hospitalisation assistance amount", "electrical
               safety rules").
        category: Optional filter to narrow the search. One of:
                  "schemes", "laws", "safety", "registration", "faqs",
                  "policies". Leave empty to search everything.

    Returns:
        A list of up to 3 dicts, each with category, source, and
        content (the relevant text chunk). Empty list if nothing
        relevant is found.
    """
    raw = search_knowledge_base(query, k=3, category=category or None)

    if raw.startswith("No relevant information"):
        return []

    results = []
    for block in raw.split("\n\n---\n\n"):
        if block.startswith("[") and "]" in block:
            header, content = block.split("]", 1)
            cat_source = header.strip("[").split(" - ", 1)
            results.append({
                "category": cat_source[0].strip() if cat_source else "",
                "source": cat_source[1].strip() if len(cat_source) > 1 else "",
                "content": content.strip(),
            })
    return results


# Pre-load the embedding model now, while stdout is still "ours" —
# doing this on the first real tool call instead can print stray
# output that corrupts the MCP stdio JSON-RPC stream and hangs the client.
print("Warming up RAG embedding model...", file=__import__("sys").stderr)
_get_db()
print("RAG embedding model ready.", file=__import__("sys").stderr)

if __name__ == "__main__":
    mcp.run(transport="stdio")