"use client";

import { useState } from "react";
import { BookOpen, Loader2 } from "lucide-react";
import { askCopilot } from "@/lib/api";

/**
 * Ask the policy a question.
 *
 * Three honest outcomes, each shown differently: an answer with the clauses it cites, an
 * explicit "not in the policy", and "no model available" with the closest clauses still
 * listed. Model text is rendered as plain text — React escapes it — never as HTML, so an
 * answer cannot inject markup into the reviewer's page.
 */
type Citation = { clause_id: string; title: string; section: string; text: string };
type Result = {
  status: "answered" | "not_found" | "model_unavailable";
  answer: string | null;
  citations: Citation[];
  retrieved: { clause_id: string; title: string }[];
  detail: string | null;
  model_called: boolean;
  provider: string | null;
  cache_hit: boolean;
};

const STARTERS = ["Is wear and tear covered?", "When is a claim sent for human review?",
                  "What if the damaged part isn't visible?"];

export function PolicyCopilot() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  const submit = async (q: string) => {
    const text = q.trim();
    if (!text || busy) return;
    setQuestion(text);
    setBusy(true);
    setError(null);
    setResult(null);
    setOpen(null);
    try {
      setResult(await askCopilot(text));
    } catch (e: any) {
      setError(e?.message ?? "The copilot could not answer.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-line bg-surface-1 p-4">
      <form onSubmit={(e) => { e.preventDefault(); submit(question); }} className="flex gap-2">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={500}
          placeholder="Ask about the policy…"
          aria-label="Question about the policy"
          className="flex-1 min-w-0 h-8 rounded-md bg-surface-2 border border-line px-2.5 text-[13px]
                     placeholder:text-muted-foreground/60 focus:border-(--aurelix-accent-line)"
        />
        <button
          type="submit"
          disabled={busy || !question.trim()}
          className="h-8 px-3 rounded-md bg-(--aurelix-accent) hover:bg-(--aurelix-accent-hover)
                     text-(--primary-foreground) text-[12px] font-medium disabled:opacity-50
                     inline-flex items-center gap-1.5 shrink-0"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : "Ask"}
        </button>
      </form>

      {!result && !error && !busy && (
        <div className="flex flex-wrap gap-1.5 mt-3">
          {STARTERS.map((s) => (
            <button key={s} type="button" onClick={() => submit(s)}
                    className="text-[11px] rounded-full border border-line px-2 py-0.5 text-muted-foreground
                               hover:text-foreground hover:bg-surface-2 transition-colors duration-(--dur-fast)">
              {s}
            </button>
          ))}
        </div>
      )}

      {error && <p className="text-[12px] text-(--state-contra) mt-3 leading-relaxed">{error}</p>}

      {result?.status === "answered" && (
        <div className="mt-3 space-y-3" aria-live="polite">
          <p className="text-[13px] leading-relaxed whitespace-pre-line">{result.answer}</p>
          <ul className="space-y-1">
            {result.citations.map((c) => {
              const expanded = open === c.clause_id;
              return (
                <li key={c.clause_id}>
                  <button type="button" onClick={() => setOpen(expanded ? null : c.clause_id)}
                          aria-expanded={expanded}
                          className="inline-flex items-center gap-1.5 text-[12px] text-text-2 hover:text-foreground">
                    <BookOpen className="h-3 w-3 text-(--aurelix-accent)" aria-hidden />
                    <span className="font-mono text-[11px] text-(--aurelix-accent)">{c.clause_id}</span>
                    <span>{c.title}</span>
                  </button>
                  {expanded && (
                    <p className="mt-1 mb-2 pl-4.5 text-[12px] leading-relaxed text-muted-foreground border-l border-line ml-1.5">
                      {c.text}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
          <p className="text-[11px] text-muted-foreground">
            {result.cache_hit ? "Answered from cache" : `Answered by ${result.provider}`} · cites only retrieved clauses
          </p>
        </div>
      )}

      {result?.status === "not_found" && (
        <div className="mt-3 rounded-md border border-line bg-surface-2 p-3" aria-live="polite">
          <div className="text-[13px] font-medium">Not in the policy</div>
          <p className="text-[12px] text-muted-foreground mt-1 leading-relaxed">
            {result.detail ?? "The policy does not address this question."}
            {!result.model_called && " No model was called."}
          </p>
        </div>
      )}

      {result?.status === "model_unavailable" && (
        <div className="mt-3 rounded-md border border-(--state-warning)/30 bg-(--state-warning-weak) p-3" aria-live="polite">
          <div className="text-[13px] font-medium text-(--state-warning)">No answer model available right now</div>
          <p className="text-[12px] text-muted-foreground mt-1">Closest clauses:</p>
          <ul className="mt-1 space-y-0.5">
            {result.retrieved.slice(0, 3).map((r) => (
              <li key={r.clause_id} className="text-[12px]">
                <span className="font-mono text-[11px] text-(--aurelix-accent)">{r.clause_id}</span> {r.title}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
