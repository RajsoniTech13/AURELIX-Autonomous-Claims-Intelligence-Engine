const API_URL = "http://127.0.0.1:8000";

export async function submitClaimMultimodal(formData: FormData) {
  const res = await fetch(`${API_URL}/claims/submit-multimodal`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err);
  }
  return res.json();
}

export async function submitClaimStream(formData: FormData, onEvent: (event: any) => void) {
  const res = await fetch(`${API_URL}/claims/submit-multimodal-stream`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(err);
  }

  if (!res.body) throw new Error("No response body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    
    buffer += decoder.decode(value, { stream: true });
    
    const lines = buffer.split("\n\n");
    buffer = lines.pop() || ""; 
    
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = JSON.parse(line.slice(6));
        if (data.error) throw new Error(data.error);
        onEvent(data);
      }
    }
  }
}

export async function getClaim(claimId: number) {
  const res = await fetch(`${API_URL}/claims/${claimId}`);
  if (!res.ok) {
    throw new Error("Failed to fetch claim");
  }
  return res.json();
}

export async function getClaims({ limit = 10 } = {}) {
  const res = await fetch(`${API_URL}/claims?limit=${limit}`);
  if (!res.ok) {
    throw new Error("Failed to fetch claims");
  }
  return res.json();
}

export async function getReviewQueue() {
  const res = await fetch(`${API_URL}/queue`);
  if (!res.ok) {
    throw new Error("Failed to fetch queue");
  }
  return res.json();
}

export async function submitVerdict(claimId: number, verdict: string, notes: string) {
  const res = await fetch(`${API_URL}/queue/${claimId}/verdict`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ verdict, notes }),
  });
  if (!res.ok) {
    throw new Error("Failed to submit verdict");
  }
  return res.json();
}

export async function getAnalytics() {
  const res = await fetch(`${API_URL}/analytics`);
  if (!res.ok) {
    throw new Error("Failed to fetch analytics");
  }
  return res.json();
}
