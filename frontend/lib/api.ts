/**
 * The one place that knows where the backend lives.
 *
 * This was a hardcoded `http://127.0.0.1:8000`, which means the deployed frontend called
 * the reviewer's own laptop — a build that compiles, deploys, and is broken for everyone
 * but the person who built it.
 *
 * `NEXT_PUBLIC_` is required: the fetches below run in the browser, and anything without
 * that prefix is stripped from the client bundle at build time. It is also **baked in at
 * build time**, not read at runtime, so changing it on Vercel requires a redeploy.
 */
export const API_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"
).replace(/\/+$/, "");

/** Absolute URL for a stored claim photograph (`image_paths` holds `uploads/<id>.jpg`). */
export function assetUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `${API_URL}/${path.replace(/^\/+/, "")}`;
}

/**
 * Turn a failed response into something a person can act on.
 *
 * FastAPI puts the useful part in `detail` — "at most 6 images per claim", "not a readable
 * image". Surfacing the raw JSON envelope instead shows the user a stack of braces and
 * hides the sentence that tells them what to fix.
 */
async function errorFrom(res: Response, fallback: string): Promise<Error> {
  const body = await res.text();
  try {
    const parsed = JSON.parse(body);
    const detail = parsed?.detail ?? parsed?.error;
    if (typeof detail === "string") return new Error(detail);
    if (detail) return new Error(JSON.stringify(detail));
  } catch {
    /* not JSON — fall through to the raw body */
  }
  return new Error(body?.slice(0, 300) || `${fallback} (HTTP ${res.status})`);
}

/**
 * A fetch that fails with a diagnosis instead of "Failed to fetch".
 *
 * A cross-origin rejection, a backend that is down, and a free-tier container cold-starting
 * are indistinguishable to `fetch` — all three throw the same opaque TypeError. Naming the
 * likely causes turns a dead-end error message into a next step.
 */
async function call(path: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new Error(
      `Cannot reach the analysis API at ${API_URL}. It may be starting up ` +
        `(free-tier instances sleep after inactivity and take ~50s to wake), offline, ` +
        `or rejecting this origin via CORS.`,
    );
  }
  return res;
}

export async function submitClaimMultimodal(formData: FormData) {
  const res = await call(`/claims/submit-multimodal`, { method: "POST", body: formData });
  if (!res.ok) throw await errorFrom(res, "Submission failed");
  return res.json();
}

export async function submitClaimStream(
  formData: FormData,
  onEvent: (event: any) => void,
) {
  const res = await call(`/claims/submit-multimodal-stream`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) throw await errorFrom(res, "Submission failed");
  if (!res.body) throw new Error("The server returned no event stream.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sawTerminal = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";

    for (const frame of frames) {
      // A frame can carry comment lines and multiple fields; take the data lines only.
      const data = frame
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trim())
        .join("\n");
      if (!data) continue;

      const event = JSON.parse(data);
      if (event.error) throw new Error(event.error);
      if (event.stage === "done") sawTerminal = true;
      onEvent(event);
    }
  }

  // A stream that ends without a verdict is a failure, not a success with nothing in it.
  // Silently returning here is how a truncated response became a blank result screen.
  if (!sawTerminal) {
    throw new Error(
      "The analysis stream ended before a verdict was produced. The claim was not saved.",
    );
  }
}

export async function getClaim(claimId: number) {
  const res = await call(`/claims/${claimId}`);
  if (!res.ok) throw await errorFrom(res, "Failed to fetch claim");
  return res.json();
}

export async function getClaims({ limit = 10 } = {}) {
  const res = await call(`/claims?limit=${limit}`);
  if (!res.ok) throw await errorFrom(res, "Failed to fetch claims");
  return res.json();
}

export async function getReviewQueue() {
  const res = await call(`/queue`);
  if (!res.ok) throw await errorFrom(res, "Failed to fetch queue");
  return res.json();
}

export async function submitVerdict(claimId: number, verdict: string, notes: string) {
  const res = await call(`/queue/${claimId}/verdict`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ verdict, notes }),
  });
  if (!res.ok) throw await errorFrom(res, "Failed to submit verdict");
  return res.json();
}

export async function getAnalytics() {
  const res = await call(`/analytics`);
  if (!res.ok) throw await errorFrom(res, "Failed to fetch analytics");
  return res.json();
}

/** Backend liveness — used by the header indicator so "is it up?" is answered, not guessed. */
export async function getHealth() {
  const res = await call(`/ready`);
  if (!res.ok) throw await errorFrom(res, "Health check failed");
  return res.json();
}
