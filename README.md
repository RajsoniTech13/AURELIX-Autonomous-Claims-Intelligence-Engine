# AURELIX — Autonomous Trust Intelligence for Damage Claims

AURELIX is a production-grade, multi-agent AI claims intelligence engine designed for modern insurance, warranty, and logistics providers. It leverages **LangGraph**, **Gemini 2.5 Flash**, **Gemini Vision**, and **Deterministic Rule Engines** to verify claims, check evidence compliance, calculate fraud risks, and provide explainable decisions.

The architecture is split into a **3-tier modular system** to serve two environments from a single, unified AI reasoning codebase:
1. **HackerRank Orchestrate CLI Mode**: Standalone Python package for batch evaluation without web or DB overhead.
2. **Production SaaS Platform Mode**: High-performance FastAPI backend gateway connected to a Next.js dashboard, PostgreSQL/SQLite, Redis caching, and human-in-the-loop queues.

---

## 🛠️ Technology Stack

* **AI Engine**: LangGraph, Gemini 2.5 Flash (via `google-genai` SDK)
* **API Gateway**: FastAPI (Python), SQLAlchemy, SQLite / PostgreSQL
* **Caching**: Redis
* **Frontend**: Next.js (App Router), TypeScript, Tailwind CSS v4, Shadcn UI, Recharts
* **Retrieval (RAG)**: Cosine Similarity TF-IDF search index

---

## 📂 Project Structure

```
aurelix/
├── agent_core/             # Main AI reasoning engine package (shared by SaaS & CLI)
│   ├── agents/             # 7 specialized AI agents
│   ├── orchestrator/       # LangGraph graph topology & process_claim API
│   ├── prompts/            # Centralized prompt templates
│   ├── schemas/            # Pydantic serialization models
│   ├── services/           # Decoupled LLM and Vector Store services
│   ├── evaluation/         # System metrics calculation scripts
│   ├── data/               # Local database (claims, rules, ground truth)
│   └── main.py             # CLI runner: CSV -> process_claim() -> output.csv
│
├── platform_backend/       # FastAPI gateway web server (imports from agent_core)
│   ├── api/routes.py       # API routes forwarding requests to agent_core
│   ├── db/                 # DB models and Session manager
│   ├── models/schemas.py   # Request/Response validation schemas
│   ├── services/cache.py   # Redis caching layer
│   └── main.py             # FastAPI gate entrypoint
│
└── frontend/               # Next.js SaaS Web Application
```

---

## 🚀 Running the Platform Locally

### Option A: HackerRank CLI Mode (Standalone AI Engine)

1. **Activate Environment & Install requirements**:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r agent_core/requirements.txt
   ```
2. **Configure Environment Variables**:
   Create a `.env` file in the project root:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   ```
3. **Execute CLI**:
   ```bash
   python agent_core/main.py
   ```

### Option B: Production SaaS Mode (Web App)

1. **Install Dependencies**:
   ```bash
   pip install -r agent_core/requirements.txt -r platform_backend/requirements.txt
   cd frontend && npm install
   ```
2. **Start FastAPI Gateway**:
   ```bash
   ./venv/bin/python -m uvicorn platform_backend.main:app --host 127.0.0.1 --port 8000
   ```
3. **Start Next.js Frontend**:
   ```bash
   cd frontend
   npm run dev
   ```
4. **Access UI**: Open [http://localhost:3000](http://localhost:3000)

---

## 🤖 Coordinated AI Claims Pipeline

Each claim runs through a LangGraph `StateGraph` of **9 nodes** — 7 agents, plus a non-LLM
image pre-flight and a short-circuit path for claims with no usable evidence. Four agents
call Gemini; three are deterministic Python.

> **Note on latency:** the fan-out does run concurrently (measured: four 1-second branches
> complete in 1.01s). The 27s per-claim latency comes from the *serial chain* of four LLM
> round trips — ingest → vision → fraud → decision — not from the fan-out. Collapsing those
> calls is Phase 2 work; see `docs/AUDIT.md` §2.3.

1. **Image Validator** *(deterministic)*: Verifies images exist, decode, and meet minimum
   resolution before any LLM call. A claim with no usable image short-circuits straight to
   `not_enough_information` — this is the single largest cost saving in the pipeline.
2. **Claim Ingestion Agent**: Parses unstructured user descriptions into structured JSON.
3. **Vision Analysis Agent**: Multimodal Gemini reasoning over submitted images to detect physical damage severity.
4. **Policy Verification Agent**: Validates evidence against the SLA guidebook.
5. **Similar Claims Agent**: TF-IDF similarity search to fetch historical repair estimates.
6. **User Risk Agent**: Checks claimant history for fraud flags and velocity limits.
7. **Fraud Review & Decision Agents**: Aggregates all branch signals to compute a final confidence score, justification, and manual review escalation requirement.

---

## 🐳 Deployment (Docker & Render/Vercel)

### 1. Backend (Render / Fly.io / AWS)

> **Not yet implemented.** There is no `Dockerfile` in this repository and no
> `docker-compose.yml`; the commands below will not run today. Containerisation is Phase 5
> work. The snippet is retained as the intended starting point.

```dockerfile
# Dockerfile — PROPOSED, not present in the repo
FROM python:3.11-slim
WORKDIR /app
COPY agent_core/ agent_core/
COPY platform_backend/ platform_backend/
RUN pip install -r agent_core/requirements.txt -r platform_backend/requirements.txt
ENV PYTHONPATH=/app
CMD ["uvicorn", "platform_backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

To build and run locally:
```bash
docker build -t aurelix-backend .
docker run -p 8000:8000 -e GEMINI_API_KEY=your_key aurelix-backend
```

### 2. Frontend (Vercel)
The Next.js frontend is optimized for zero-config Vercel deployment.
1. Connect your GitHub repository to Vercel.
2. Set the Root Directory to `frontend`.
3. Set the build command to `npm run build`.
4. Ensure `NEXT_PUBLIC_API_URL` is set to your deployed backend URL.

### 3. Database
- By default, it uses a local SQLite database (`aurelix.db`).
- For production, set the `DATABASE_URL` environment variable to a PostgreSQL connection string (e.g., Neon Serverless Postgres). SQLAlchemy will automatically map all models.
