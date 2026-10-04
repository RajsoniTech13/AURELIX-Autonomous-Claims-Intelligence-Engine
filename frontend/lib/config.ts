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
