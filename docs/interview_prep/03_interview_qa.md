# Common Interview Questions & Answers

If an interviewer asks you about AURELIX, these are the architectural tradeoffs and decisions you should be prepared to explain:

### Q1: Why did you use LangGraph instead of a standard asynchronous pipeline or a Redis Queue (like Celery)?
**Answer:** "A standard asynchronous pipeline (like a chain of `asyncio.gather` calls) lacks state persistence and cyclic capabilities. LangGraph models the system as a state machine (DAG), allowing us to pass a global `ClaimsState` context seamlessly across multiple agent nodes. 

While a Redis Queue (like Celery) is the industry standard for distributing heavy workloads across multiple physical servers, it introduces significant DevOps overhead and latency (due to polling). Since AURELIX is designed to stream immediate, sub-30-second responses back to a live UI, LangGraph's native in-memory thread pools orchestrate the agents much faster. However, in a true Fortune 500 deployment where claim processing could be batched overnight, I would absolutely detach the LangGraph execution into a Celery background worker."

---

### Q2: How did you handle API Rate Limiting for the AI models?
**Answer:** "When dealing with multi-agent fan-out, 4-7 agents attempt to hit the LLM API simultaneously. This immediately triggers a `429 RESOURCE_EXHAUSTED` burst limit ban from the provider (e.g., Google Gemini). 

To solve this, I built a thread-safe `APIRateLimiter` using the Token Bucket algorithm via Python's `threading.Lock`. By calculating the minimum time interval required between requests (e.g., 15 RPM = 4.0 seconds), the lock forces parallel threads to sleep for the exact millisecond duration required before calling the API. This effectively acts as a local queue, completely eliminating 429 crashes."

---

### Q3: What happens if the AI Provider (Google Gemini) completely goes down, or you hit a hard Daily Quota limit?
**Answer:** "I engineered the system with Graceful Degradation. The core API client (`gemini_client.py`) wraps the SDK in a `try/except` block with exponential backoff. If the API returns a 500 Server Error or a hard Daily Quota block, the client catches the exception, logs a critical error, and seamlessly falls back to a deterministic Mock Data Generator. 

Because the mock data adheres strictly to the same Pydantic schema as the real AI, the orchestrator and the frontend UI are entirely unaware of the outage. The stream completes successfully, preventing the app from crashing in production."

---

### Q4: Why did you choose Server-Sent Events (SSE) instead of WebSockets for the live UI?
**Answer:** "WebSockets are bi-directional and stateful. Maintaining thousands of concurrent stateful WebSocket connections requires complex sticky sessions and specialized load balancing. 

For AURELIX, the communication is strictly unidirectional: the user submits an HTTP POST request, and the server streams updates back as the AI processes the claim. SSE runs over standard HTTP, making it incredibly lightweight, natively supported by all modern browsers (via the Fetch API or EventSource), and trivial to route through standard API Gateways (like Nginx, AWS ALB) without sticky sessions."

---

### Q5: How do you prevent hallucination in the Fraud and Decision agents?
**Answer:** "I implemented a Retrieval-Augmented Generation (RAG) architecture using FAISS. Instead of relying solely on the LLM's pre-trained knowledge, the *Similar Claims Agent* vectorizes the incoming claim and performs a K-Nearest Neighbors (KNN) search against a verified, historical database of past company claims. 

By injecting the top 3 most relevant historical cases directly into the prompt context of the Final Decision Agent, the LLM grounds its logic in established company precedent, drastically reducing hallucination."
