# Low-Level Design (LLD)

## 1. Database Schema (SQLite / SQLAlchemy)

The system is designed with an append-only audit trail and a mutable `claims` table.

### `claims` Table
- `id` (Primary Key, Auto-increment)
- `user_id` (String, Indexed for fast lookups)
- `claim_status` (Enum: `supported`, `contradicted`, `not_enough_information`)
- `confidence_score` (Integer 0-100)
- `fraud_score`, `user_risk_score` (Integers)
- `risk_level` (Enum: `LOW`, `MEDIUM`, `HIGH`)
- `claim_object` (String, e.g., "car", "phone")
- `created_at` (Timestamp)

### `audit_logs` Table
- `id` (Primary Key, Auto-increment)
- `claim_id` (Foreign Key -> claims.id)
- `agent_name` (String, e.g., "Vision Analysis")
- `reasoning` (Text, stores the LLM's step-by-step logic)
- `timestamp` (Timestamp)

**LLD Insight:** Storing the `audit_logs` as a separate table with a `claim_id` foreign key instead of a JSON blob in the `claims` table allows for scalable relational queries (e.g., "Find all claims where the Vision Agent raised a red flag").

---

## 2. Server-Sent Events (SSE) Streaming Protocol

Instead of returning a single monolithic JSON response, the backend yields a continuous stream of events formatted using the standard HTTP SSE protocol (`text/event-stream`).

**Backend Generator (Python):**
```python
yield f'data: {json.dumps({"stage": "vision_analysis", "status": "running"})}\n\n'
```
**Frontend Parser (TypeScript):**
```typescript
const lines = buffer.split("\n\n");
buffer = lines.pop() || ""; 
for (const line of lines) {
  if (line.startsWith("data: ")) {
    const data = JSON.parse(line.slice(6));
    onEvent(data); // Dispatches to React State
  }
}
```
**LLD Insight:** The strict `\n\n` chunking is critical. If a chunk is split prematurely by TCP routing, the `buffer += decoder.decode(value)` logic securely queues incomplete chunks until a full `\n\n` boundary is reached, preventing `JSON.parse` failures.

---

## 3. Distributed Rate Limiting (The Token Bucket)

Google's Gemini Free Tier has a strict burst limit of 15 Requests Per Minute (RPM). Because LangGraph utilizes a parallel fan-out architecture (spawning up to 7 concurrent threads for one claim), it instantly triggers a `429 RESOURCE_EXHAUSTED` ban.

**Implementation (Thread-Safe Token Bucket):**
```python
class APIRateLimiter:
    def __init__(self, rpm: int = 15):
        self.interval = 60.0 / rpm
        self.lock = threading.Lock()
        self.last_call_time = 0.0

    def wait(self):
        with self.lock:
            elapsed = time.time() - self.last_call_time
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            self.last_call_time = time.time()
```
**LLD Insight:** By instantiating a global `global_rate_limiter = APIRateLimiter(15)`, we create a local synchronization primitive. When 4 threads hit this simultaneously, the `lock` forces them to queue linearly. Thread 1 executes immediately. Thread 2 sleeps for 4 seconds. Thread 3 sleeps for 8 seconds. This entirely decouples LangGraph's parallel thread execution from the strict upstream API limits.

---

## 4. Idempotency & Caching

To prevent massive billing overhead and redundant API calls when a user rapidly refreshes the UI or submits the identical claim multiple times, an Idempotency Cache is built directly into the Gemini client.

**Cache Key Generation:**
```python
key = hashlib.sha256(f"{agent_name}_{user_id}_{claim_text}_{image_bytes_hash}".encode()).hexdigest()
```
**LLD Insight:** By hashing the **actual byte content** of the uploaded images alongside the user's text, we ensure that if the user modifies even a single pixel of the image, or changes one word in their claim, it bypasses the cache and re-runs the investigation. If the data is truly identical, it returns the cached JSON in `0.02s` without hitting the LLM.
