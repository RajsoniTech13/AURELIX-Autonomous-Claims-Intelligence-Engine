# AURELIX - Autonomous Trust Intelligence for Damage Claims

AURELIX is a production-grade, multi-agent AI verification and trust intelligence platform for physical damage claims. It evaluates claims by analyzing conversation transcripts, metadata, user histories, and evidence image compliance rules.

---

## 🚀 Quick Start Instructions

AURELIX is split into a **FastAPI backend** and a **Next.js 15 frontend**. 

### Prerequisites
- Node.js (v18+)
- Python (3.9+)

---

### 1. Database & Batch Claim Ingestion
First, run the offline batch processing script to process `claims/claims.csv`, write the results to `claims/output.csv`, and pre-populate the local database:

```bash
# Create Python virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
pip install -r backend/requirements.txt

# Run the batch claim processing and database ingestion
python3 scripts/run_batch.py

# Run the metrics evaluation script
python3 scripts/evaluate.py
```

This generates:
- `claims/output.csv`: Complete row-by-row verdicts matching the format of `sample_claims.csv`.
- `aurelix.db`: SQLite database populated with all 44 claims and their multi-agent audit logs.
- `evaluation/evaluation_report.md`: Detailed performance metrics, latency, and cost calculations.

---

### 2. Start the Backend API (FastAPI)
Run the backend web server to expose endpoints for the dashboard, claim details, and the manual review queue:

```bash
# Activate virtual environment
source venv/bin/activate

# Start the FastAPI server (it runs on http://localhost:8000)
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

Interactive API documentation will be available at: [http://localhost:8000/docs](http://localhost:8000/docs)

---

### 3. Start the Frontend Client (Next.js 15)
Start the Next.js web application to inspect the claims visually:

```bash
# Navigate to frontend and install dependencies
cd frontend
npm install

# Start the Next.js dev server (it runs on http://localhost:3000)
npm run dev
```

Open your browser to: [http://localhost:3000](http://localhost:3000)

---

## 🤖 Multi-Agent Architecture (LangGraph)

The core claim verification engine is implemented as a **LangGraph StateGraph** consisting of 9 specialized nodes (agents):

1. **Claim Understanding Agent**: Parses customer chat history to extract the object (`car`, `laptop`, `package`), claimed part, claimed issue type, and conversation summary.
2. **Image Quality Agent**: Scrapes image metadata and paths to flag blurry images, glare, low light, wrong camera angles, cropped-out views, and possible tampering.
3. **Vision Analysis Agent**: Simulates visual inspection, identifying the type of damage shown, matching object parts, and estimating severity.
4. **Evidence Compliance Agent**: Retrieves policy guidelines dynamically from `claims/evidence_requirements.csv` and checks if the claim meets policy conditions (e.g. required image count, covered parts).
5. **User Risk Agent**: Evaluates user history (claim counts, rejections, manual esc) from `claims/user_history.csv` to calculate risk signals.
6. **Fraud Detection Agent**: Checks for contradictions, text injections (prompt injections), pressure tactics, and historical risk correlations to output a 0-100 fraud score.
7. **Confidence Agent**: Blends signals from vision accuracy, image quality, compliance, and fraud to assign a 0-100 confidence score.
8. **Decision Agent**: Produces the final verdict (`supported`, `contradicted`, `not_enough_information`) with an explainable justification.
9. **Human Review Agent**: Escalates high-risk, tampered, or low-confidence (<70) claims to manual reviews.

---

## 📈 Enterprise Features Included
1. **Explainable AI**: Grounded explanations for every claim decision, showing which image was used, what damage was detected, and why the verdict was reached.
2. **Audit Trails**: Complete record of inputs, outputs, timestamps, and step-by-step reasoning for all 9 agents stored in the database.
3. **Human Review Queue**: Specialized queue enabling claims officers to inspect, write notes, and override/confirm verdicts.
4. **Analytics Dashboard**: Interactive charts showing claim volume, verdict trends, confidence distribution, fraud trends, and severity breakdowns.
# AURELIX-Autonomous-Claims-Intelligence-Engine
