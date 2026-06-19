# AURELIX — Autonomous Trust Intelligence for Damage Claims

AURELIX is a production-grade, multi-agent AI claims intelligence engine designed for modern insurance, warranty, and logistics providers. It leverages **LangGraph**, **Gemini 2.5 Flash**, **Gemini Vision**, and **Deterministic Rule Engines** to verify claims, check evidence compliance, calculate fraud risks, and provide explainable decisions.

The architecture is split into a **3-tier modular system** to serve two environments from a single, unified AI reasoning codebase:
1. **HackerRank Orchestrate CLI Mode**: Standalone Python package for batch evaluation without web or DB overhead.
2. **Production SaaS Platform Mode**: High-performance FastAPI backend gateway connected to a Next.js 15 dashboard, PostgreSQL/SQLite, Redis caching, and human-in-the-loop queues.

---

## 🛠️ Technology Stack

* **AI Engine**: LangGraph, Gemini 2.5 Flash, Gemini Vision, LangChain
* **API Gateway**: FastAPI (Python), SQLAlchemy, SQLite / PostgreSQL
* **Caching**: Redis
* **Frontend**: Next.js 15, TypeScript, Tailwind CSS, Shadcn UI
* **Retrieval (RAG)**: Cosine Similarity TF-IDF search index

---

## 📂 Project Structure

```
aurelix/
├── agent_core/             # Main AI reasoning engine package (shared by SaaS & CLI)
│   ├── agents/             # 9 specialized AI agents
│   ├── orchestrator/       # LangGraph graph topology & process_claim API
│   ├── prompts/            # Centralized prompt templates
│   ├── schemas/            # Pydantic serialization models
│   ├── services/           # Decoupled LLM and Vector Store services
│   ├── evaluation/         # System metrics calculation scripts
│   ├── data/               # Local database (claims, rules, ground truth)
│   └── main.py             # CLI runner: CSV -> process_claim() -> output.csv
│
├── submission_package/     # Standalone HackerRank submission package
│   ├── README.md           # Standalone setup and CLI instructions
│   ├── INTERVIEW_PREP.md   # Judge Q&A reference document
│   ├── test_submission_verdict.py # Automated verdict validation script
│   ├── log.txt             # Complete development chat prompt log
│   ├── test_images/        # Test images for verdict verification
│   └── agent_core/         # Standalone snapshot of the claims engine
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

## 🚀 Running the Platform

### Option A: HackerRank CLI Mode (Standalone AI Engine)

To run the batch parser on the `data/claims.csv` dataset and run classification evaluation metrics:

1. **Activate Environment & Install requirements**:
   ```bash
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
   * Verdicts are saved to: `agent_core/output/output.csv`
   * Classification reports are saved to: `agent_core/output/evaluation_report.md` (expect **100% Match Accuracy** on baseline cases).

---

### Option B: Production SaaS Mode (Web App)

To run the complete SaaS stack with the dashboard, analytics, and database tracking:

1. **Configure Environment Variables**:
   Ensure `.env` in the root workspace contains your DB and API keys.
2. **Start FastAPI Gateway**:
   ```bash
   ./venv/bin/python -m uvicorn platform_backend.main:app --host 127.0.0.1 --port 8000
   ```
3. **Start Next.js Frontend**:
   ```bash
   cd frontend
   npm run dev
   ```
4. **Access UI**:
   Open [http://localhost:3000](http://localhost:3000) to submit claims, view real-time agent execution visualizers, manage human review overrides, and inspect analytics.

---

## 🤖 Coordinated AI Claims Pipeline

Each claim undergoes a 9-stage validation:
1. **Intake / Intent Agent**: Extracts objects, parts, and issues.
2. **Quality Check Agent**: Identifies blur, darkness, wrong angles, or obstructions.
3. **Gemini Vision Agent**: Verifies if the damage matches the claim.
4. **Evidence compliance SLA Agent**: Matches image counts and visibility checklists against policy guidebooks.
5. **RAG Retriever Agent**: Retrieves similar cases from the vector index for context.
6. **User History Agent**: Determines historic rejections and claim velocity.
7. **Fraud Intel Agent**: Flags visual/claim mismatches or suspicious behaviors.
8. **Confidence Aggregator**: Computes a confidence rating (0-100).
9. **Final Decision Engine**: Assigns verdicts (`supported`, `contradicted`, `not_enough_information`) with explainable AI logs.
