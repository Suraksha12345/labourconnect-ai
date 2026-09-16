# LabourConnect — Agentic AI Backend

An 8-layer Agentic AI backend powering **LabourConnect**, a daily-wage job-matching platform connecting workers (masons, painters, farmers, plumbers, electricians, drivers) with contractors in rural Karnataka. Supports Kannada, Hindi, English, and Tulu.

This repository contains the Flask + CrewAI + MCP backend. The Flutter frontend lives in a separate repository: [labourconnect-app](https://github.com/Suraksha12345/labourconnect-app).

## Architecture Overview

The system is built as 8 layers, each approved and reviewed independently:

| Layer | Description |
|-------|-------------|
| 1–4 | Flutter frontend (13+ screens) + 4 AI agents (Wage Advisor, Job Matching, Safety Check, Chatbot) served via Flask, backed by an MCP server + Firestore, with a Streamlit monitoring dashboard |
| 5 | **RAG** — LangChain + ChromaDB + FastEmbed (`BAAI/bge-small-en-v1.5`), 90 knowledge chunks across schemes, laws, safety, registration, FAQs, and policies |
| 6 | **Automation** — 7 n8n workflows (job expiry, scheme reminders, feedback collection, job-match notifications, KYC verification, fraud alerts, payment reminders), each polling a Flask `/api/*` endpoint on a schedule |
| 7 | **Action Layer** — Flask + Firebase Admin SDK, 11 `/actions/*` endpoints, all API-key protected, with authorization checks on sensitive actions (e.g. only the real contractor can accept/reject an application) |
| 8 | **Testing** — pytest + DeepEval suite covering all agents and endpoints |

### AI Agents

- **Job Matching Agent** — true CrewAI agent; the LLM (`qwen/qwen3.8-27b`) decides when to call the `list_jobs` tool via an MCP connection.
- **Wage Advisor, Safety Check, Chatbot** — "fetch-then-ask" pattern using `openai/gpt-oss-120b`: relevant data is fetched deterministically from MCP tools in Python first, then handed to the LLM as context (no tool-calling by the model itself).

## Tech Stack

- **Backend**: Python, Flask
- **AI orchestration**: CrewAI, Groq (LLM inference)
- **Knowledge base**: LangChain, ChromaDB, FastEmbed
- **Automation**: n8n (self-hosted)
- **Database / Auth**: Firebase (Firestore + Admin SDK), Firebase Anonymous Auth
- **Testing**: pytest, DeepEval

## Setup

### 1. Clone the repository
```bash
git clone https://github.com/Suraksha12345/labourconnect-ai.git
cd labourconnect-ai
```

### 2. Create a virtual environment and install dependencies
```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

### 3. Add configuration files
Place the following in the project root (not committed to GitHub — request these separately):
- `.env` — see [Environment Variables](#environment-variables) below
- `serviceAccountKey.json` — Firebase Admin SDK credentials

### 4. Build the RAG knowledge base (one-time step)
```bash
python rag/ingest.py
```
This creates the local `rag/chroma_db` folder. **Do not copy this folder between machines** — always rebuild it fresh with this command on each new environment.

### 5. Run the backend
```bash
python app.py
```
The server starts on `http://localhost:5000` and automatically launches the MCP server as a background subprocess.

## Environment Variables

Set these in a `.env` file (must have a leading dot in the filename):

| Variable | Purpose |
|----------|---------|
| `GROQ_API_KEY` | LLM inference via Groq |
| `API_SECRET_KEY` | Protects `/actions/*` and other secured endpoints |
| `GOVT_ID_ENCRYPTION_KEY` | Encrypts stored government ID fields |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Firebase Admin SDK credentials (as JSON string, if not using a separate file) |

## Connecting the Flutter App

Update `AI_BACKEND_URL` in the Flutter app's `main.dart` to point at wherever this backend is reachable:
- **Same machine as an Android emulator** → `http://10.0.2.2:5000`
- **Physical device or external access** → use a tunnel (e.g. `ngrok http 5000`) or deploy to a hosting platform and use its public URL

## Testing

```bash
python tests/run_all.py
```
Runs the full pytest/DeepEval suite across all agents and endpoints.

## Security Notes

- All `/actions/*` and sensitive endpoints require an API key header.
- Firestore access is scoped via `ownerUid` rules per collection.
- Government ID fields are encrypted before storage.
- **Before any public deployment**: rotate any API keys that may have been exposed in earlier commits, and ensure `.env` / `serviceAccountKey.json` are never committed (already covered by `.gitignore`).

## Deployment

This backend has been deployed both on a cloud platform (Render) and locally (e.g. on a lab desktop with an ngrok tunnel for external access). For a fresh cloud deployment:
1. Connect this repo to the hosting platform.
2. Set the environment variables above in the platform's dashboard.
3. Build command: `pip install -r requirements.txt && python rag/ingest.py`
4. Start command: `python app.py` (or `gunicorn app:app` for production)
5. Update the Flutter app's `AI_BACKEND_URL` to the platform's public URL and rebuild the APK.

## Author

Suraksha — MCA, Mangalore University (Internship Project)
