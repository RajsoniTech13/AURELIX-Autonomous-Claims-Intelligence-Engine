"use client";

import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { getExplanation } from "@/lib/api";

/**
 * The policy clauses a decision rests on.
 *
 * Read from `/api/v1/claims/{id}/explanation`, which joins the rule that fired to the
 * clauses that justify it. No model is involved, so this is the same every time it is
 * opened — an explanation of a deterministic decision should be as reproducible as the
 * decision itself.
 */
type Clause = { clause_id: string; title: string; section: string; text: string };

export function PolicyBasis({ claimId }: { claimId: number }) {
  const [clauses, setClauses] = useState<Clause[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setClauses(null);
    setFailed(false);
    getExplanation(claimId)
      .then((d) => live && setClauses(d.clauses ?? []))
      .catch(() => live && setFailed(true));
    return () => { live = false; };
  }, [claimId]);

  if (failed) return <p className="text-[12px] text-muted-foreground">Policy basis unavailable.</p>;
  if (!clauses) return <div className="h-12 rounded-md bg-surface-2 animate-pulse" aria-hidden />;
  if (clauses.length === 0) return null;

  return (
    <ul className="divide-y divide-line/60">
      {clauses.map((c) => {
        const expanded = open === c.clause_id;
        return (
          <li key={c.clause_id}>
            <button
              type="button"
              onClick={() => setOpen(expanded ? null : c.clause_id)}
              aria-expanded={expanded}
              className="w-full flex items-center gap-2 py-2 text-left text-[12px] hover:text-foreground
                         text-text-2 transition-colors duration-(--dur-fast)"
            >
              <ChevronRight className={`h-3 w-3 shrink-0 transition-transform ${expanded ? "rotate-90" : ""}`} aria-hidden />
              <span className="font-mono text-[11px] text-(--aurelix-accent) shrink-0">{c.clause_id}</span>
              <span className="truncate">{c.title}</span>
            </button>
            {expanded && (
              <p className="pb-3 pl-5 text-[12px] leading-relaxed text-muted-foreground">{c.text}</p>
            )}
          </li>
        );
      })}
    </ul>
  );
}
