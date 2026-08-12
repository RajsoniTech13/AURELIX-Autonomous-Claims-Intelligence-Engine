"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle, Check, ChevronRight, FileSearch, Loader2, Plus, X, ImageOff,
} from "lucide-react";
import { assetUrl, submitVerdict } from "@/lib/api";
import {
  ConfidenceMeter, DecisionBadge, EmptyState, SectionTitle, Skeleton,
  StatusBadge, StatusDot, decisionLabel, decisionTone, riskTone,
} from "@/components/ui/status";

/* ── Stage vocabulary ──────────────────────────────────────────────────────
   The pipeline's own stage ids, given reader-facing names. The order is the
   order `agent_core.service.PIPELINE_STAGES` actually runs in. */
const STAGE_META: Record<string, { label: string; blurb: string }> = {
  preflight:           { label: "Preflight",           blurb: "Decode, resolution and deterministic blur/exposure measurement" },
  duplicate_check:     { label: "Duplicate check",     blurb: "Perceptual fingerprint against every photograph previously submitted" },
  perception:          { label: "Perception",          blurb: "Single multimodal request — observations only, no judgement" },
  policy_verification: { label: "Policy verification", blurb: "Evidence requirements for this object class" },
  user_risk:           { label: "Risk profile",        blurb: "Claim history and velocity signals" },
  alignment:           { label: "Alignment",           blurb: "Claimed part and severity against what was observed" },
  decision:            { label: "Decision",            blurb: "Fraud score, confidence, and the first matching rule" },
  "Human Review (Manual Action)": { label: "Human review", blurb: "Recorded analyst decision" },
};

function stageLabel(name: string) { return STAGE_META[name]?.label ?? name; }

/** Rule ids read as identifiers, so they are rendered as such. */
function RuleChip({ id }: { id: string }) {
  const fraud = id.startsWith("FRAUD:");
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[11px]
                  ${fraud
                    ? "border-(--state-warning)/25 bg-(--state-warning-weak) text-(--state-warning)"
                    : "border-(--aurelix-accent-line) bg-(--aurelix-accent-weak) text-(--aurelix-accent)"}`}
    >
      {id}
    </span>
  );
}

/** Definition row used by the case summary and the findings tables. */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="label-meta mb-1.5">{label}</dt>
      <dd className="text-[13px] text-foreground break-words">{children}</dd>
    </div>
  );
}

/* ── Evidence lightbox ─────────────────────────────────────────────────── */
function Lightbox({ src, index, total, onClose }: {
  src: string; index: number; total: number; onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Evidence ${index} of ${total}`}
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-sm p-4 animate-fadeIn"
    >
      <button
        onClick={onClose}
        aria-label="Close"
        className="absolute top-4 right-4 h-9 w-9 rounded-md flex items-center justify-center
                   text-white/70 hover:text-white hover:bg-white/10 transition-colors"
      >
        <X className="h-5 w-5" aria-hidden />
      </button>
      <figure onClick={e => e.stopPropagation()} className="max-w-5xl w-full">
        <img src={src} alt={`Claim evidence ${index}`} className="w-full max-h-[80vh] object-contain rounded-lg" />
        <figcaption className="label-meta text-center mt-3">Evidence {index} of {total}</figcaption>
      </figure>
    </div>
  );
}

export function ClaimReviewTab({
  claim, loading, error, onClaimUpdated, onNavigate,
}: {
  claim: any;
  loading?: boolean;
  error?: string | null;
  onClaimUpdated?: (claim: any) => void;
  onNavigate?: (tab: string) => void;
}) {
  const [deciding, setDeciding] = useState<string | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [openStage, setOpenStage] = useState<string | null>("decision");
  const [lightbox, setLightbox] = useState<number | null>(null);

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-7 w-56" />
        <div className="grid sm:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-16" />)}
        </div>
        <Skeleton className="h-48" />
      </div>
    );
  }

  if (error) {
    return (
      <EmptyState
        icon={AlertTriangle}
        title="Investigation could not be loaded"
        description={error}
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
    );
  }

  if (!claim) {
    return (
      <EmptyState
        icon={FileSearch}
        title="No investigation open"
        description="Select a claim from the overview or the review queue, or start a new investigation."
        action={
          <div className="flex flex-wrap items-center justify-center gap-2">
            <button
              onClick={() => onNavigate?.("submit")}
              className="inline-flex items-center gap-2 h-8 px-3 rounded-md bg-(--aurelix-accent)
                         hover:bg-(--aurelix-accent-hover) text-(--primary-foreground) text-[13px] font-medium
                         transition-colors duration-(--dur-fast)"
            >
              <Plus className="h-3.5 w-3.5" aria-hidden /> New investigation
            </button>
            <button
              onClick={() => onNavigate?.("queue")}
              className="h-8 px-3 rounded-md border border-line hover:bg-surface-2 text-[13px] font-medium
                         transition-colors duration-(--dur-fast)"
            >
              Open review queue
            </button>
          </div>
        }
      />
    );
  }

  const logs: any[] = claim.audit_logs ?? [];
  const byAgent = Object.fromEntries(logs.map(l => [l.agent_name, l]));
  const perception = byAgent.perception?.outputs ?? null;
  const alignment = byAgent.alignment?.outputs ?? null;
  const verdict = byAgent.decision?.outputs ?? null;
  const quality = byAgent.preflight?.outputs ?? null;

  const images: string[] =
    claim.image_paths && claim.image_paths !== "none" ? claim.image_paths.split(";").filter(Boolean) : [];

  const humanVerdict: string | null = claim.manual_verdict ?? null;
  const awaitingHuman = claim.manual_review_required && !humanVerdict;
  const ruleIds: string[] = verdict?.rule_ids ?? [];

  const decide = async (v: "approved" | "rejected") => {
    setDeciding(v);
    setDecisionError(null);
    try {
      const updated = await submitVerdict(claim.id, v, notes.trim());
      onClaimUpdated?.(updated);
      setNotes("");
    } catch (e: any) {
      setDecisionError(e?.message ?? "That decision could not be recorded.");
    } finally {
      setDeciding(null);
    }
  };

  return (
    <div className="space-y-7 pb-10">
      {lightbox !== null && images[lightbox] && (
        <Lightbox
          src={assetUrl(images[lightbox])}
          index={lightbox + 1}
          total={images.length}
          onClose={() => setLightbox(null)}
        />
      )}

      {/* ── Case header ────────────────────────────────────────────────── */}
      <header className="border-b border-line pb-5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 mb-3">
          <span className="tnum text-lg font-semibold tracking-tight">
            INV-{String(claim.id).padStart(4, "0")}
          </span>
          <DecisionBadge status={claim.claim_status} />
          {humanVerdict && (
            <StatusBadge tone={humanVerdict === "approved" ? "verified" : "contra"}>
              Human decision · {humanVerdict}
            </StatusBadge>
          )}
          {awaitingHuman && <StatusBadge tone="warning">Awaiting review</StatusBadge>}
        </div>
        <p className="text-[13px] text-muted-foreground">
          {claim.claim_object ? claim.claim_object.charAt(0).toUpperCase() + claim.claim_object.slice(1) : "Claim"}
          {" · "}filed by <span className="text-text-2">{claim.user_id}</span>
          {claim.created_at && <> · {new Date(claim.created_at).toLocaleString()}</>}
        </p>
      </header>

      {/* ── Signal strip ───────────────────────────────────────────────── */}
      <div className="rounded-lg border border-line bg-surface-1">
        <div className="grid grid-cols-2 lg:grid-cols-4 divide-x divide-y lg:divide-y-0 divide-line">
          <div className="px-4 sm:px-5 py-3.5">
            <div className="label-meta mb-2">Confidence</div>
            <div className="tnum text-2xl font-semibold leading-none">{claim.confidence_score ?? 0}%</div>
            <ConfidenceMeter value={claim.confidence_score} showValue={false} className="mt-2.5" />
          </div>
          <div className="px-4 sm:px-5 py-3.5">
            <div className="label-meta mb-2">Fraud score</div>
            <div className="tnum text-2xl font-semibold leading-none">{claim.fraud_score ?? 0}<span className="text-sm text-muted-foreground font-normal">/100</span></div>
          </div>
          <div className="px-4 sm:px-5 py-3.5">
            <div className="label-meta mb-2">Claimant risk</div>
            <div className="flex items-center gap-2 mt-1">
              <StatusDot tone={riskTone(claim.risk_level)} />
              <span className="text-[15px] font-medium">{claim.risk_level ?? "—"}</span>
            </div>
          </div>
          <div className="px-4 sm:px-5 py-3.5">
            <div className="label-meta mb-2">Policy</div>
            <div className="flex items-center gap-2 mt-1">
              <StatusDot tone={claim.policy_status === "PASS" ? "verified" : claim.policy_status === "FAIL" ? "contra" : "warning"} />
              <span className="text-[15px] font-medium">{claim.policy_status ?? "—"}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="grid lg:grid-cols-3 gap-7">
        <div className="lg:col-span-2 space-y-7 min-w-0">
          {/* ── Statement ───────────────────────────────────────────────── */}
          <section>
            <SectionTitle>Claimant statement</SectionTitle>
            <blockquote className="rounded-lg border border-line bg-surface-1 p-4 text-[13px] leading-relaxed
                                   text-text-2 border-l-2 border-l-(--aurelix-accent-line)">
              {claim.user_claim || "No statement was provided."}
            </blockquote>
          </section>

          {/* ── Evidence ────────────────────────────────────────────────── */}
          <section>
            <SectionTitle
              action={
                quality?.overall && (
                  <StatusBadge tone={quality.overall === "good" || quality.overall === "fair" ? "verified" : "warning"}>
                    Measured quality: {quality.overall}
                    {typeof quality.score === "number" && ` · ${quality.score}`}
                  </StatusBadge>
                )
              }
            >
              Evidence {images.length > 0 && <span className="text-muted-foreground font-normal">({images.length})</span>}
            </SectionTitle>

            {images.length === 0 ? (
              <div className="rounded-lg border border-line bg-surface-1">
                <EmptyState icon={ImageOff} title="No photographs submitted"
                  description="This claim was filed without visual evidence, so perception was skipped." />
              </div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {images.map((path, i) => (
                  <button
                    key={i}
                    onClick={() => setLightbox(i)}
                    className="group relative rounded-lg overflow-hidden border border-line bg-surface-2
                               aspect-[4/3] focus-visible:ring-2 focus-visible:ring-(--aurelix-accent)"
                    aria-label={`Open evidence ${i + 1}`}
                  >
                    <img
                      src={assetUrl(path)}
                      alt={`Claim evidence ${i + 1}`}
                      loading="lazy"
                      className="h-full w-full object-cover transition-transform duration-(--dur-slow)
                                 group-hover:scale-[1.03]"
                    />
                    <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 to-transparent
                                    px-2.5 py-2 flex items-center justify-between">
                      <span className="font-mono text-[11px] text-white/85">img_{i + 1}</span>
                      {claim.supporting_image_ids?.includes(`img_${i + 1}`) && (
                        <span className="text-[10px] text-(--state-verified)">cited</span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>

          {/* ── Claimed vs observed ─────────────────────────────────────── */}
          {perception && (
            <section>
              <SectionTitle>Claimed against observed</SectionTitle>
              <div className="rounded-lg border border-line bg-surface-1 overflow-hidden">
                <div className="grid grid-cols-2 divide-x divide-line">
                  <div className="px-4 py-2.5 label-meta">Claimant asserts</div>
                  <div className="px-4 py-2.5 label-meta">Model observed</div>
                </div>
                <div className="border-t border-line divide-y divide-line">
                  {[
                    {
                      k: "Object",
                      c: perception.claim_understanding?.object_category,
                      o: perception.observed_object,
                      match: alignment?.object_match,
                    },
                    {
                      k: "Part",
                      c: perception.claim_understanding?.claimed_part,
                      o: (perception.damage_analysis?.damaged_parts ?? []).map((d: any) => d.part).join(", ") || "none reported",
                      match: alignment?.part_match,
                    },
                    {
                      k: "Damage type",
                      c: perception.claim_understanding?.claimed_issue,
                      o: (perception.damage_analysis?.damaged_parts ?? []).map((d: any) => d.issue_type).join(", ") || "none",
                    },
                    {
                      k: "Severity",
                      c: perception.claim_understanding?.claimed_severity,
                      o: (perception.damage_analysis?.damaged_parts ?? []).map((d: any) => d.severity).join(", ") || "unknown",
                      match: alignment?.severity_delta != null
                        ? (alignment.severity_delta === 0 ? "exact" : `Δ${alignment.severity_delta}`)
                        : undefined,
                    },
                  ].map(row => (
                    <div key={row.k} className="grid grid-cols-2 divide-x divide-line">
                      <div className="px-4 py-3 min-w-0">
                        <div className="label-meta mb-1">{row.k}</div>
                        <div className="text-[13px] break-words">{row.c || "—"}</div>
                      </div>
                      <div className="px-4 py-3 min-w-0">
                        <div className="flex items-center justify-between gap-2 mb-1">
                          <span className="label-meta">{row.k}</span>
                          {row.match && (
                            <span className={`font-mono text-[10px] ${
                              row.match === "exact" || row.match === "match"
                                ? "text-(--state-verified)"
                                : row.match === "mismatch"
                                  ? "text-(--state-contra)"
                                  : "text-(--state-warning)"
                            }`}>
                              {row.match}
                            </span>
                          )}
                        </div>
                        <div className="text-[13px] break-words">{row.o || "—"}</div>
                      </div>
                    </div>
                  ))}
                </div>
                {perception.claimed_part_visible === false && (
                  <div className="border-t border-line px-4 py-2.5 text-[12px] text-(--state-warning)
                                  bg-(--state-warning-weak) flex items-center gap-2">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    The part named in the claim is not visible in any submitted photograph.
                  </div>
                )}
              </div>
            </section>
          )}

          {/* ── Reasoning trace ─────────────────────────────────────────── */}
          <section>
            <SectionTitle>
              Reasoning trace <span className="text-muted-foreground font-normal">({logs.length} stages)</span>
            </SectionTitle>
            {logs.length === 0 ? (
              <div className="rounded-lg border border-line bg-surface-1">
                <EmptyState title="No audit trail recorded" description="This claim predates per-stage logging." />
              </div>
            ) : (
              <ol className="rounded-lg border border-line bg-surface-1 divide-y divide-line overflow-hidden">
                {logs.map((log, i) => {
                  const open = openStage === log.agent_name;
                  const meta = STAGE_META[log.agent_name];
                  return (
                    <li key={i}>
                      <button
                        onClick={() => setOpenStage(open ? null : log.agent_name)}
                        aria-expanded={open}
                        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-surface-2/60
                                   transition-colors duration-(--dur-fast)"
                      >
                        <span className="tnum text-[11px] text-muted-foreground w-4 shrink-0">{i + 1}</span>
                        <Check className="h-3.5 w-3.5 text-(--state-verified) shrink-0" aria-hidden />
                        <span className="text-[13px] font-medium shrink-0">{stageLabel(log.agent_name)}</span>
                        <span className="text-[12px] text-muted-foreground truncate hidden sm:block flex-1">
                          {meta?.blurb}
                        </span>
                        <span className="tnum text-[11px] text-muted-foreground ml-auto shrink-0 hidden sm:block">
                          {log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : ""}
                        </span>
                        <ChevronRight
                          className={`h-3.5 w-3.5 text-muted-foreground shrink-0 transition-transform
                                      duration-(--dur-fast) ${open ? "rotate-90" : ""}`}
                          aria-hidden
                        />
                      </button>
                      {open && (
                        <div className="px-4 pb-4 pl-11 animate-fadeIn">
                          <p className="text-[13px] leading-relaxed text-text-2">{log.reasoning}</p>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ol>
            )}
          </section>
        </div>

        {/* ── Decision column ─────────────────────────────────────────── */}
        <aside className="space-y-6 min-w-0">
          <section>
            <SectionTitle>Decision</SectionTitle>
            <div className={`rounded-lg border p-4 ${
              decisionTone(claim.claim_status) === "verified" ? "border-(--state-verified)/25 bg-(--state-verified-weak)"
              : decisionTone(claim.claim_status) === "contra" ? "border-(--state-contra)/25 bg-(--state-contra-weak)"
              : "border-line bg-surface-1"
            }`}>
              <div className={`text-base font-semibold tracking-tight ${
                decisionTone(claim.claim_status) === "verified" ? "text-(--state-verified)"
                : decisionTone(claim.claim_status) === "contra" ? "text-(--state-contra)"
                : "text-foreground"
              }`}>
                {decisionLabel(claim.claim_status)}
              </div>
              <p className="text-[13px] leading-relaxed text-text-2 mt-2">
                {claim.claim_status_justification || "No justification recorded."}
              </p>
              {ruleIds.length > 0 && (
                <div className="mt-3 pt-3 border-t border-line/60">
                  <div className="label-meta mb-2">Rules applied</div>
                  <div className="flex flex-wrap gap-1.5">
                    {ruleIds.map(id => <RuleChip key={id} id={id} />)}
                  </div>
                </div>
              )}
            </div>
          </section>

          {claim.escalation_reason && (
            <section>
              <SectionTitle>Escalation</SectionTitle>
              <p className="text-[13px] leading-relaxed text-(--state-warning)">{claim.escalation_reason}</p>
            </section>
          )}

          {awaitingHuman && (
            <section>
              <SectionTitle>Your decision</SectionTitle>
              <textarea
                value={notes}
                onChange={e => setNotes(e.target.value)}
                placeholder="Notes for the audit trail (optional)"
                aria-label="Reviewer notes"
                className="w-full h-20 text-[13px] resize-none rounded-md bg-surface-2 border border-line p-2.5
                           placeholder:text-muted-foreground/60 transition-colors duration-(--dur-fast)
                           focus:border-(--aurelix-accent-line)"
              />
              {decisionError && (
                <p className="text-[12px] text-(--state-contra) mt-2 leading-relaxed">{decisionError}</p>
              )}
              <div className="grid grid-cols-2 gap-2 mt-2.5">
                <button
                  disabled={deciding !== null}
                  onClick={() => decide("approved")}
                  className="h-9 inline-flex items-center justify-center gap-2 rounded-md text-[13px] font-medium
                             bg-(--state-verified) text-(--on-verified) hover:opacity-90 disabled:opacity-50
                             transition-opacity duration-(--dur-fast)"
                >
                  {deciding === "approved" ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Check className="h-3.5 w-3.5" aria-hidden />}
                  Approve
                </button>
                <button
                  disabled={deciding !== null}
                  onClick={() => decide("rejected")}
                  className="h-9 inline-flex items-center justify-center gap-2 rounded-md text-[13px] font-medium
                             border border-(--state-contra)/40 text-(--state-contra) hover:bg-(--state-contra-weak)
                             disabled:opacity-50 transition-colors duration-(--dur-fast)"
                >
                  {deciding === "rejected" ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <X className="h-3.5 w-3.5" aria-hidden />}
                  Reject
                </button>
              </div>
            </section>
          )}

          {humanVerdict && claim.manual_reviewer_notes && (
            <section>
              <SectionTitle>Reviewer notes</SectionTitle>
              <p className="text-[13px] leading-relaxed text-text-2 whitespace-pre-wrap">
                {claim.manual_reviewer_notes}
              </p>
            </section>
          )}

          <section>
            <SectionTitle>Case record</SectionTitle>
            <dl className="space-y-3.5">
              <Field label="Policyholder">{claim.user_id}</Field>
              <Field label="Object">{claim.claim_object}</Field>
              <Field label="Damage recorded">
                {[claim.issue_type, claim.object_part, claim.severity].filter(Boolean).join(" · ") || "—"}
              </Field>
              <Field label="Risk flags">
                {claim.risk_flags && claim.risk_flags !== "none" ? (
                  <span className="flex flex-wrap gap-1.5">
                    {claim.risk_flags.split(";").filter(Boolean).map((f: string) => (
                      <span key={f} className="font-mono text-[11px] rounded border border-line bg-surface-2 px-1.5 py-0.5">
                        {f}
                      </span>
                    ))}
                  </span>
                ) : "none"}
              </Field>
              {claim.policy_reason && <Field label="Policy note">{claim.policy_reason}</Field>}
            </dl>
          </section>
        </aside>
      </div>
    </div>
  );
}
