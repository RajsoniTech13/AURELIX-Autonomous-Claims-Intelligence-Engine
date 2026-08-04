# High-Level Architecture (HLD)

## Project Overview
AURELIX is an autonomous, multi-agent AI claims intelligence engine. It completely automates the insurance claims adjudication process by combining multimodal AI (Vision + NLP), vector search (RAG), and a state-machine orchestrator to investigate, verify, and decide on claims with zero human intervention (unless an escalation is required).

## Architecture Diagram (Conceptual)

```mermaid
graph TD
    Client[Next.js Frontend] -->|HTTP POST (Multipart/Form-Data)| API[FastAPI Backend]
    API -->|SSE Stream| Client

    subgraph Backend Core [AURELIX Backend]
        API --> Orchestrator[LangGraph Orchestrator]
        
        subgraph Agents [Multi-Agent Pipeline]
            Orchestrator --> Agent1(Image Validator)
            Agent1 --> Agent2(Claim Ingestion)
            
            Agent2 -->|Parallel Fan-Out| Agent3(Vision Analysis)
            Agent2 -->|Parallel Fan-Out| Agent4(Policy Check)
            Agent2 -->|Parallel Fan-Out| Agent5(User Risk)
            Agent2 -->|Parallel Fan-Out| Agent6(Vector Search/Similar Claims)
            
            Agent3 --> Agent7(Fraud Review)
            Agent4 --> Agent7
            Agent5 --> Agent7
            Agent6 --> Agent7
            
            Agent7 --> Agent8(Decision Engine)
        end
    end

    subgraph External Dependencies
        Agent6 <--> FAISS[FAISS Vector Store]
        Agents <--> Gemini[Google Gemini 2.5 Flash API]
        Agents <--> Redis[In-Memory Cache / Token Bucket]
        API <--> SQLite[(SQLite / PostgreSQL)]
    end
```

## Core System Components

### 1. The Presentation Layer (Next.js & React)
- **Framework:** Next.js (Client-side rendered dashboard).
- **Communication:** Uses Server-Sent Events (SSE) via the Fetch API (`res.body.getReader()`) to stream JSON chunks from the backend. This enables a rich, interactive UI that animates smoothly as agents complete their tasks, without relying on heavy WebSocket connections.
- **Why SSE over WebSockets?** WebSockets are bi-directional and stateful, making load-balancing complex. SSE is unidirectional (server-to-client) over standard HTTP, making it perfect for streaming LLM or agent events behind standard reverse proxies (Nginx/ALB).

### 2. The API Layer (FastAPI)
- **Framework:** FastAPI (Python). Chosen for its native asynchronous capabilities (`async/await`) and blazing-fast performance.
- **Role:** Handles multipart form uploads (images + JSON data), initiates the LangGraph execution, and yields a `StreamingResponse` back to the client.

### 3. The Orchestration Layer (LangGraph)
- **Framework:** LangGraph.
- **Role:** Acts as a Directed Acyclic Graph (DAG) state machine. It maintains a global `ClaimsState` dictionary that is passed sequentially or in parallel between agents.
- **Parallel Fan-Out:** Crucial for latency optimization. Instead of running 7 agents sequentially (which would take ~30 seconds), LangGraph branches out to run Vision, Policy, Risk, and Similar Claims simultaneously on separate threads.

### 4. The Intelligence Layer (Google Gemini)
- **Integration:** Directly integrates with `google-genai` using **Native Structured Outputs** (`response_schema`).
- **Resilience:** Implements an `APIRateLimiter` (Token Bucket) to prevent parallel threads from bursting Google's rate limits. It also features a graceful mock-fallback `try/except` block to ensure the system degrades smoothly during total API outages (e.g., daily quota exhaustion).

### 5. The Retrieval-Augmented Generation (RAG) Layer (FAISS)
- **Component:** FAISS (Facebook AI Similarity Search).
- **Role:** Converts historical claims into text embeddings and indexes them in a highly optimized vector space. When a new claim arrives, the *Similar Claims Agent* performs a K-Nearest Neighbors (KNN) search to retrieve the 3 most identical historical claims. This grounds the AI's final decision in historical precedent to prevent hallucinations.
