"""
Shared MCP connection setup, used by all CrewAI agent files
(job_matching_agent.py, wage_advisor_agent.py, safety_check_agent.py,
chatbot_agent.py) so this logic only lives in one place.
"""

import os
import sys
from mcp import StdioServerParameters

# ── Workaround for a known CrewAI bug (GitHub issue #5886) ──
# CrewAI injects a "cache_breakpoint" property into messages, but only
# the Anthropic provider knows how to strip it before sending. Groq
# rejects it outright. This disables that injection safely.
try:
    import crewai.llms.cache as _crewai_cache
    _crewai_cache.mark_cache_breakpoint = lambda msg: msg
except (ImportError, AttributeError):
    pass  # module path may differ across CrewAI versions — safe to skip

# ── Where mcp_server.py actually runs ──
# Locally on Windows: a SEPARATE venv (dashboard_venv) that has
# firebase-admin, kept apart from the main venv to dodge a dependency
# conflict. On a deployed host like Render, everything lives in one
# environment, so this falls back to whichever Python is currently
# running — no manual switching needed.
_LOCAL_DASHBOARD_PYTHON = r"C:\labourconnect_ai\dashboard_venv\Scripts\python.exe"
MCP_PYTHON = _LOCAL_DASHBOARD_PYTHON if os.path.exists(_LOCAL_DASHBOARD_PYTHON) else sys.executable
MCP_SERVER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")

mcp_server_params = StdioServerParameters(
    command=MCP_PYTHON,
    args=[MCP_SERVER_SCRIPT],
    env=os.environ.copy(),
)