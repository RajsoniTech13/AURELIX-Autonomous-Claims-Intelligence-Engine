"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle, ArrowRight, Check, CheckCircle2, Loader2, Search, X,
} from "lucide-react";
import { getReviewQueue, submitVerdict } from "@/lib/api";
import {
  ConfidenceMeter, DecisionBadge, EmptyState, SectionTitle, Skeleton,
  StatusDot, decisionLabel, riskTone,
} from "@/components/ui/status";

/** Queue age. The column previously read a hardcoded "2h" for every row. */
function age(iso?: string | null): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "—";
  const minutes = Math.max(0, Math.round(ms / 60000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours}h` : `${Math.round(hours / 24)}d`;
}

/**
 * Manual Review — a split-pane analyst workspace.
 *
 * It was a single accordion list: to judge a claim you expanded a row, read a
 * truncated reason, and decided. The queue and the evidence for a decision were
 * never on screen together. Now the queue stays fixed on the left and the
 * selected claim fills the right, so an analyst can move down the list without
 * losing their place — and ↑/↓/Enter work, because a queue worked for hours is
 * a keyboard surface.
 */
export function ReviewQueueTab({
  onSelectClaim, onNavigate,
}: {
  onSelectClaim?: (claimId: number) => void;
  onNavigate?: (tab: string) => void;
}) {
  const [queue, setQueue] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [processing, setProcessing] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  const fetchQueue = async () => {
    setLoading(true);
    try {
      const data = await getReviewQueue();
      setQueue(data);
      setError(null);
      setSelectedId(prev => (prev && data.some((c: any) => c.id === prev) ? prev : data[0]?.id ?? null));
    } catch (err: any) {
      setError(err?.message ?? "Could not load the review queue.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchQueue(); }, []);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return queue;
    return queue.filter(c =>
      [String(c.id).padStart(4, "0"), c.user_id, c.claim_object, c.escalation_reason,
       c.claim_status, c.claim_status_justification]
        .some(f => (f ?? "").toString().toLowerCase().includes(q)),
    );
  }, [queue, query]);

  const selected = visible.find(c => c.id === selectedId) ?? visible[0] ?? null;

  // ↑/↓ move through the queue. Skipped while typing in the search box.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      e.preventDefault();
      const i = visible.findIndex(c => c.id === selected?.id);
      const next = e.key === "ArrowDown"
        ? Math.min(i + 1, visible.length - 1)
        : Math.max(i - 1, 0);
      if (visible[next]) setSelectedId(visible[next].id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, selected]);

  const decide = async (verdict: "approved" | "rejected") => {
    if (!selected) return;
    setProcessing(verdict);
    setActionError(null);
    try {
      await submitVerdict(selected.id, verdict, notes.trim());
      setNotes("");
      await fetchQueue();
    } catch (e: any) {
      setActionError(e?.message ?? `Could not record that decision.`);
    } finally {
      setProcessing(null);
    }
  };

  return (
    <div className="space-y-5">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Manual Review</h1>
          <p className="text-[13px] text-muted-foreground mt-1">
            {loading ? "Loading queue…"
              : query.trim()
                ? `${visible.length} of ${queue.length} escalated claims match “${query.trim()}”.`
                : queue.length === 0
                  ? "No claims are currently awaiting a human decision."
                  : `${queue.length} claim${queue.length === 1 ? "" : "s"} escalated for human review.`}
          </p>
        </div>
        <div className="relative group w-full md:w-[300px] shrink-0">
          <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground
                             group-focus-within:text-(--aurelix-accent) transition-colors" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Filter by ID, claimant, object, reason…"
            aria-label="Filter the review queue"
            className="h-9 w-full rounded-md bg-surface-1 border border-line pl-9 pr-3 text-[13px]
                       placeholder:text-muted-foreground/60 transition-colors duration-(--dur-fast)
                       focus:border-(--aurelix-accent-line)"
          />
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-(--state-contra)/25 bg-(--state-contra-weak) p-3.5
                        flex items-start gap-2.5 text-[13px] text-(--state-contra)">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" aria-hidden />
          <div>
            <p className="font-medium">The review queue could not be loaded</p>
            <p className="opacity-90 mt-0.5 leading-relaxed">{error}</p>
          </div>
        </div>
      )}

      {loading ? (
        <div className="rounded-lg border border-line bg-surface-1 divide-y divide-line">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="px-4 py-3 flex items-center gap-3">
              <Skeleton className="h-3 w-12" />
              <Skeleton className="h-3 flex-1 max-w-[260px]" />
              <Skeleton className="h-3 w-10 ml-auto" />
            </div>
          ))}
        </div>
      ) : queue.length === 0 ? (
        <div className="rounded-lg border border-line bg-surface-1">
          <EmptyState
            icon={CheckCircle2}
            title="Nothing awaiting review"
            description="Every escalated claim has been resolved. New escalations appear here automatically."
            action={
              <button
                onClick={() => onNavigate?.("overview")}
                className="h-8 px-3 rounded-md border border-line hover:bg-surface-2 text-[13px] font-medium
                           transition-colors duration-(--dur-fast)"
              >
                Back to overview
              </button>
            }
          />
        </div>
      ) : (
        <div className="grid lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)] gap-5 items-start">
          {/* ── Queue ──────────────────────────────────────────────────── */}
          <div className="rounded-lg border border-line bg-surface-1 overflow-hidden lg:sticky lg:top-4">
            <div className="px-4 py-2.5 border-b border-line flex items-center justify-between">
              <span className="label-meta">Queue</span>
              <span className="label-meta tnum">{visible.length}</span>
            </div>
            {visible.length === 0 ? (
              <EmptyState
                icon={Search}
                title="No matching claims"
                description={`Nothing in the queue matches “${query.trim()}”.`}
                action={
                  <button onClick={() => setQuery("")} className="text-[13px] text-(--aurelix-accent) hover:underline">
                    Clear filter
                  </button>
                }
              />
            ) : (
              <ul className="divide-y divide-line max-h-[calc(100dvh-16rem)] overflow-y-auto" role="listbox">
                {visible.map(c => {
                  const active = selected?.id === c.id;
                  return (
                    <li key={c.id}>
                      <button
                        role="option"
                        aria-selected={active}
                        onClick={() => { setSelectedId(c.id); setNotes(""); setActionError(null); }}
                        className={`relative w-full text-left px-4 py-3 transition-colors duration-(--dur-fast)
                                    ${active ? "bg-surface-2" : "hover:bg-surface-2/60"}`}
                      >
                        <span
                          aria-hidden
                          className={`absolute left-0 inset-y-0 w-0.5 bg-(--aurelix-accent) transition-opacity
                                      ${active ? "opacity-100" : "opacity-0"}`}
                        />
                        <div className="flex items-center justify-between gap-2 mb-1.5">
                          <span className="tnum text-[13px] font-medium">
                            INV-{String(c.id).padStart(4, "0")}
                          </span>
                          <span className="tnum text-[11px] text-muted-foreground">{age(c.created_at)}</span>
                        </div>
                        <div className="flex items-center gap-2 mb-1.5">
                          <DecisionBadge status={c.claim_status} icon={false} />
                          <StatusDot tone={riskTone(c.risk_level)} />
                          <span className="text-[11px] text-muted-foreground truncate">{c.user_id}</span>
                        </div>
                        <p className="text-[12px] text-muted-foreground line-clamp-2 leading-relaxed">
                          {c.escalation_reason}
                        </p>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {/* ── Selected claim ─────────────────────────────────────────── */}
          {selected && (
            <div className="rounded-lg border border-line bg-surface-1 min-w-0">
              <div className="px-5 py-4 border-b border-line flex flex-wrap items-center gap-x-3 gap-y-2">
                <span className="tnum text-[15px] font-semibold">
                  INV-{String(selected.id).padStart(4, "0")}
                </span>
                <DecisionBadge status={selected.claim_status} />
                <button
                  onClick={() => onSelectClaim?.(selected.id)}
                  className="ml-auto inline-flex items-center gap-1.5 text-[12px] text-muted-foreground
                             hover:text-foreground transition-colors duration-(--dur-fast)"
                >
                  Full case file <ArrowRight className="h-3 w-3" aria-hidden />
                </button>
              </div>

              <div className="p-5 space-y-5">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  <div>
                    <div className="label-meta mb-1.5">Confidence</div>
                    <ConfidenceMeter value={selected.confidence_score} />
                  </div>
                  <div>
                    <div className="label-meta mb-1.5">Fraud</div>
                    <div className="tnum text-[13px]">{selected.fraud_score ?? 0}/100</div>
                  </div>
                  <div>
                    <div className="label-meta mb-1.5">Risk</div>
                    <div className="flex items-center gap-1.5">
                      <StatusDot tone={riskTone(selected.risk_level)} />
                      <span className="text-[13px]">{selected.risk_level ?? "—"}</span>
                    </div>
                  </div>
                  <div>
                    <div className="label-meta mb-1.5">Object</div>
                    <div className="text-[13px] capitalize">{selected.claim_object}</div>
                  </div>
                </div>

                <div>
                  <div className="label-meta mb-2">Claimant statement</div>
                  <blockquote className="text-[13px] leading-relaxed text-text-2 border-l-2 border-line pl-3">
                    {selected.user_claim || "No statement provided."}
                  </blockquote>
                </div>

                <div>
                  <div className="label-meta mb-2">Why this was escalated</div>
                  <p className="text-[13px] leading-relaxed text-(--state-warning)">
                    {selected.escalation_reason}
                  </p>
                </div>

                <div>
                  <div className="label-meta mb-2">System reasoning</div>
                  <p className="text-[13px] leading-relaxed text-text-2">
                    {selected.claim_status_justification || "No justification recorded."}
                  </p>
                </div>

                <div className="pt-1 border-t border-line">
                  <div className="label-meta mb-2 mt-4">Record your decision</div>
                  <textarea
                    value={notes}
                    onChange={e => setNotes(e.target.value)}
                    placeholder="Notes for the audit trail (optional)"
                    aria-label="Reviewer notes"
                    className="w-full h-20 text-[13px] resize-none rounded-md bg-surface-2 border border-line p-2.5
                               placeholder:text-muted-foreground/60 transition-colors duration-(--dur-fast)
                               focus:border-(--aurelix-accent-line)"
                  />
                  {actionError && (
                    <p className="text-[12px] text-(--state-contra) mt-2 leading-relaxed">{actionError}</p>
                  )}
                  <div className="flex flex-col sm:flex-row gap-2 mt-2.5">
                    <button
                      disabled={processing !== null}
                      onClick={() => decide("approved")}
                      className="h-9 flex-1 inline-flex items-center justify-center gap-2 rounded-md text-[13px]
                                 font-medium bg-(--state-verified) text-(--on-verified) hover:opacity-90
                                 disabled:opacity-50 transition-opacity duration-(--dur-fast)"
                    >
                      {processing === "approved"
                        ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                        : <Check className="h-3.5 w-3.5" aria-hidden />}
                      Approve claim
                    </button>
                    <button
                      disabled={processing !== null}
                      onClick={() => decide("rejected")}
                      className="h-9 flex-1 inline-flex items-center justify-center gap-2 rounded-md text-[13px]
                                 font-medium border border-(--state-contra)/40 text-(--state-contra)
                                 hover:bg-(--state-contra-weak) disabled:opacity-50
                                 transition-colors duration-(--dur-fast)"
                    >
                      {processing === "rejected"
                        ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                        : <X className="h-3.5 w-3.5" aria-hidden />}
                      Reject claim
                    </button>
                  </div>
                  <p className="text-[11px] text-muted-foreground mt-2.5">
                    Recorded against the claim and appended to its audit trail. Use ↑ ↓ to move through the queue.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
