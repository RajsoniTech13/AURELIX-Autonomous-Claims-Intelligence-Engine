"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight, Check, ChevronRight, Loader2, Minus, RotateCcw, X, AlertTriangle,
} from "lucide-react";
import { ConfidenceMeter, StatusDot, decisionLabel, decisionTone, riskTone } from "@/components/ui/status";

/**
 * `skipped` is a real outcome, not an error: when preflight finds no usable
 * image the perception request is never made, because a claim with nothing to
 * look at cannot produce a grounded finding. Showing it as skipped rather than
 * complete keeps the trace honest about which claims cost a model call.
 */
type StageStatus = "pending" | "running" | "complete" | "failed" | "skipped";
type PipelineStages = Record<string, StageStatus>;

interface Props {
  stages: PipelineStages;
  files: File[];
  completedTime?: number;
  claimResult?: any;
  onOpenFullReport?: () => void;
  onRestart?: () => void;
}

/**
 * The stage list, in execution order, with what each one actually does.
 *
 * `network: true` marks the single stage that leaves the machine — the whole
 * architecture is built around there being exactly one, and the trace should
 * make that visible rather than implying seven model calls.
 */
const STAGES: { id: string; label: string; detail: string; network?: boolean }[] = [
  { id: "preflight",           label: "Preflight",           detail: "Decoding evidence, measuring blur and exposure" },
  { id: "duplicate_check",     label: "Duplicate check",     detail: "Fingerprinting against previously submitted photographs" },
  { id: "perception",          label: "Perception",          detail: "Reading the photographs and the statement", network: true },
  { id: "policy_verification", label: "Policy verification", detail: "Checking evidence requirements for this object" },
  { id: "user_risk",           label: "Risk profile",        detail: "Evaluating claim history and velocity" },
  { id: "alignment",           label: "Alignment",           detail: "Comparing what was claimed with what was observed" },
  { id: "document_check",      label: "Document check",      detail: "Cross-checking paperwork against the photographs" },
  { id: "decision",            label: "Decision",            detail: "Scoring fraud and confidence, applying ordered rules" },
];

function StageIcon({ status }: { status: StageStatus }) {
  if (status === "running") return <Loader2 className="h-3.5 w-3.5 animate-spin text-(--aurelix-accent)" aria-hidden />;
  if (status === "complete") return <Check className="h-3.5 w-3.5 text-(--state-verified)" aria-hidden />;
  if (status === "failed") return <X className="h-3.5 w-3.5 text-(--state-contra)" aria-hidden />;
  if (status === "skipped") return <Minus className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />;
  return <span className="h-1.5 w-1.5 rounded-full bg-(--aurelix-line-strong)" aria-hidden />;
}

function statusWord(status: StageStatus) {
  return status === "running" ? "Running"
    : status === "complete" ? "Complete"
    : status === "failed" ? "Failed"
    : status === "skipped" ? "Skipped"
    : "Queued";
}

export function LiveInvestigationViewer({
  stages, files, completedTime, claimResult, onOpenFullReport, onRestart,
}: Props) {
  // Object URLs were minted on every render and never revoked, leaking a blob
  // per photograph per re-render during a live run.
  const previews = useMemo(() => files.map(f => URL.createObjectURL(f)), [files]);
  useEffect(() => () => previews.forEach(URL.revokeObjectURL), [previews]);

  const done = !!claimResult;
  const activeIndex = STAGES.findIndex(s => stages[s.id] === "running");
  const completedCount = STAGES.filter(s => ["complete", "skipped"].includes(stages[s.id])).length;
  const progress = Math.round((completedCount / STAGES.length) * 100);

  return (
    <div className="max-w-3xl mx-auto space-y-5">
      {/* ── Run header ─────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <StatusDot tone={done ? "verified" : "accent"} pulse={!done} />
          <h2 className="text-[15px] font-semibold tracking-tight">
            {done ? "Investigation complete" : "Investigation running"}
          </h2>
        </div>
        <div className="flex items-center gap-3 text-[12px] text-muted-foreground">
          <span className="tnum">{completedCount}/{STAGES.length} stages</span>
          {completedTime !== undefined && (
            <span className="tnum text-(--state-verified)">{completedTime.toFixed(2)}s</span>
          )}
        </div>
      </div>

      {/* A hairline progress bar. No glow, no shimmer. */}
      <div className="h-0.5 w-full rounded-full bg-surface-2 overflow-hidden" role="progressbar"
           aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} aria-label="Investigation progress">
        <div
          className="h-full bg-(--aurelix-accent) transition-[width] duration-500 ease-(--ease-out)"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* ── Evidence strip ─────────────────────────────────────────────── */}
      {previews.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {previews.map((src, i) => (
            <div
              key={i}
              className="relative h-16 w-24 shrink-0 rounded-md overflow-hidden border border-line bg-surface-2"
            >
              <img src={src} alt={`Evidence ${i + 1}`} className="h-full w-full object-cover" />
              <span className="absolute bottom-0 inset-x-0 bg-black/60 text-white/85 font-mono text-[10px]
                               px-1.5 py-0.5">
                img_{i + 1}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* ── Execution trace ────────────────────────────────────────────── */}
      <ol className="rounded-lg border border-line bg-surface-1 divide-y divide-line overflow-hidden">
        {STAGES.map((stage, i) => {
          const status = stages[stage.id] ?? "pending";
          const isActive = status === "running";
          const isPending = status === "pending";
          return (
            <li
              key={stage.id}
              className={`flex items-center gap-3 px-4 py-3 transition-colors duration-(--dur-base)
                          ${isActive ? "bg-(--aurelix-accent-weak)" : ""} ${isPending ? "opacity-45" : ""}`}
            >
              <span className="tnum text-[11px] text-muted-foreground w-4 shrink-0">{i + 1}</span>
              <span className="h-4 w-4 flex items-center justify-center shrink-0"><StageIcon status={status} /></span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className={`text-[13px] font-medium ${isActive ? "text-(--aurelix-accent)" : ""}`}>
                    {stage.label}
                  </span>
                  {stage.network && (
                    <span className="font-mono text-[10px] text-muted-foreground border border-line rounded px-1
                                     py-px hidden sm:inline">
                      1 model request
                    </span>
                  )}
                </div>
                <p className="text-[12px] text-muted-foreground truncate mt-0.5">
                  {status === "skipped" ? "Skipped — no usable photograph to analyse" : stage.detail}
                </p>
              </div>
              <span className="label-meta shrink-0 hidden sm:block">{statusWord(status)}</span>
            </li>
          );
        })}
      </ol>

      {/* ── Outcome ────────────────────────────────────────────────────── */}
      <AnimatePresence>
        {claimResult && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
            className="space-y-4"
          >
            <div className={`rounded-lg border p-5 ${
              decisionTone(claimResult.claim_status) === "verified" ? "border-(--state-verified)/25 bg-(--state-verified-weak)"
              : decisionTone(claimResult.claim_status) === "contra" ? "border-(--state-contra)/25 bg-(--state-contra-weak)"
              : "border-line bg-surface-1"
            }`}>
              <div className="label-meta mb-2">Decision</div>
              <div className={`text-lg font-semibold tracking-tight ${
                decisionTone(claimResult.claim_status) === "verified" ? "text-(--state-verified)"
                : decisionTone(claimResult.claim_status) === "contra" ? "text-(--state-contra)"
                : "text-foreground"
              }`}>
                {decisionLabel(claimResult.claim_status)}
              </div>
              <p className="text-[13px] leading-relaxed text-text-2 mt-2">
                {claimResult.claim_status_justification}
              </p>

              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mt-4 pt-4 border-t border-line/60">
                <div>
                  <div className="label-meta mb-1.5">Confidence</div>
                  <ConfidenceMeter value={claimResult.confidence_score} />
                </div>
                <div>
                  <div className="label-meta mb-1.5">Fraud score</div>
                  <div className="tnum text-[13px]">{claimResult.fraud_score}/100</div>
                </div>
                <div>
                  <div className="label-meta mb-1.5">Claimant risk</div>
                  <div className="flex items-center gap-1.5">
                    <StatusDot tone={riskTone(claimResult.risk_level)} />
                    <span className="text-[13px]">{claimResult.risk_level}</span>
                  </div>
                </div>
              </div>

              {claimResult.manual_review_required && (
                <div className="mt-4 pt-4 border-t border-line/60 flex items-start gap-2">
                  <AlertTriangle className="h-3.5 w-3.5 text-(--state-warning) shrink-0 mt-0.5" aria-hidden />
                  <div className="min-w-0">
                    <div className="text-[12px] font-medium text-(--state-warning)">Escalated for human review</div>
                    <p className="text-[12px] text-text-2 leading-relaxed mt-0.5">
                      {claimResult.escalation_reason}
                    </p>
                  </div>
                </div>
              )}
            </div>

            <div className="flex flex-col sm:flex-row gap-2">
              <button
                onClick={onOpenFullReport}
                className="h-9 px-4 inline-flex items-center justify-center gap-2 rounded-md bg-(--aurelix-accent)
                           hover:bg-(--aurelix-accent-hover) text-(--primary-foreground) text-[13px] font-medium
                           transition-colors duration-(--dur-fast)"
              >
                Open case file <ArrowRight className="h-3.5 w-3.5" aria-hidden />
              </button>
              <button
                onClick={onRestart}
                className="h-9 px-4 inline-flex items-center justify-center gap-2 rounded-md border border-line
                           hover:bg-surface-2 text-[13px] font-medium transition-colors duration-(--dur-fast)"
              >
                <RotateCcw className="h-3.5 w-3.5" aria-hidden /> New investigation
              </button>
              <span className="tnum text-[12px] text-muted-foreground self-center sm:ml-auto">
                INV-{String(claimResult.id).padStart(4, "0")}
              </span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
