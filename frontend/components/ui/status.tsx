"use client";

/**
 * Status primitives.
 *
 * Every screen that shows a verdict, a risk level or a pipeline stage renders it
 * through one of these. Before, each screen invented its own colours and
 * wording — the same verdict appeared as an emerald "Approved" pill on one page
 * and a green "Supported" chip on another, and the review queue coloured
 * priority by confidence with thresholds no other screen used.
 *
 * The mapping is the contract:
 *
 *   supported              → verified   (green)
 *   contradicted           → contra     (red)
 *   not_enough_information → unknown    (grey, deliberately not amber —
 *                                        "we could not tell" is not a warning)
 *   escalated / review     → warning    (amber)
 */
import * as React from "react";
import { Check, X, Minus, AlertTriangle } from "lucide-react";

export type Tone = "verified" | "contra" | "warning" | "unknown" | "accent";

const TONE: Record<Tone, { fg: string; bg: string; bd: string; dot: string }> = {
  verified: { fg: "text-(--state-verified)", bg: "bg-(--state-verified-weak)", bd: "border-(--state-verified)/25", dot: "bg-(--state-verified)" },
  contra:   { fg: "text-(--state-contra)",   bg: "bg-(--state-contra-weak)",   bd: "border-(--state-contra)/25",   dot: "bg-(--state-contra)" },
  warning:  { fg: "text-(--state-warning)",  bg: "bg-(--state-warning-weak)",  bd: "border-(--state-warning)/25",  dot: "bg-(--state-warning)" },
  unknown:  { fg: "text-(--state-unknown)",  bg: "bg-(--state-unknown-weak)",  bd: "border-(--state-unknown)/25",  dot: "bg-(--state-unknown)" },
  accent:   { fg: "text-(--aurelix-accent)", bg: "bg-(--aurelix-accent-weak)", bd: "border-(--aurelix-accent-line)", dot: "bg-(--aurelix-accent)" },
};

export function decisionTone(status?: string | null): Tone {
  switch (status) {
    case "supported": return "verified";
    case "contradicted": return "contra";
    case "not_enough_information": return "unknown";
    default: return "unknown";
  }
}

export function decisionLabel(status?: string | null): string {
  switch (status) {
    case "supported": return "Supported";
    case "contradicted": return "Contradicted";
    case "not_enough_information": return "Insufficient evidence";
    default: return "Pending";
  }
}

export function riskTone(level?: string | null): Tone {
  switch ((level ?? "").toUpperCase()) {
    case "HIGH": return "contra";
    case "MEDIUM": return "warning";
    case "LOW": return "verified";
    default: return "unknown";
  }
}

/** A 6px dot. The quietest way to carry state — used in the top bar and lists. */
export function StatusDot({ tone, pulse = false, className = "" }: {
  tone: Tone; pulse?: boolean; className?: string;
}) {
  return (
    <span
      aria-hidden
      className={`inline-block h-1.5 w-1.5 rounded-full shrink-0 ${TONE[tone].dot} ${
        pulse ? "animate-softPulse" : ""
      } ${className}`}
    />
  );
}

/**
 * Compact status badge. Deliberately rectangular with a 4px radius rather than
 * a pill: a table of pills reads as a toy, and these sit in dense rows.
 */
export function StatusBadge({ tone, children, icon = false, className = "" }: {
  tone: Tone; children: React.ReactNode; icon?: boolean; className?: string;
}) {
  const t = TONE[tone];
  const Icon = tone === "verified" ? Check : tone === "contra" ? X : tone === "warning" ? AlertTriangle : Minus;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-xs font-medium
                  whitespace-nowrap ${t.fg} ${t.bg} ${t.bd} ${className}`}
    >
      {icon && <Icon className="h-3 w-3 shrink-0" aria-hidden />}
      {children}
    </span>
  );
}

/** The verdict, rendered the same way everywhere it appears. */
export function DecisionBadge({ status, icon = true, className = "" }: {
  status?: string | null; icon?: boolean; className?: string;
}) {
  return (
    <StatusBadge tone={decisionTone(status)} icon={icon} className={className}>
      {decisionLabel(status)}
    </StatusBadge>
  );
}

/**
 * Confidence as a value plus a hairline meter.
 *
 * The bar is one accent colour at varying width, not a red→amber→green
 * gradient: confidence is a magnitude, and colouring it by threshold implies a
 * judgement the rule engine has already made separately.
 */
export function ConfidenceMeter({ value, className = "", showValue = true }: {
  value?: number | null; className?: string; showValue?: boolean;
}) {
  const v = typeof value === "number" ? Math.max(0, Math.min(100, value)) : null;
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <div
        className="h-1 w-14 rounded-full bg-surface-3 overflow-hidden shrink-0"
        role="meter"
        aria-valuenow={v ?? undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Decision confidence"
      >
        {v !== null && (
          <div
            className="h-full rounded-full bg-(--aurelix-accent) transition-[width] duration-500"
            style={{ width: `${v}%` }}
          />
        )}
      </div>
      {showValue && (
        <span className="tnum text-xs text-text-2 w-8 text-right">
          {v === null ? "—" : `${v}%`}
        </span>
      )}
    </div>
  );
}

/** Section heading used across every screen so hierarchy stays identical. */
export function SectionTitle({ children, action, className = "" }: {
  children: React.ReactNode; action?: React.ReactNode; className?: string;
}) {
  return (
    <div className={`flex items-baseline justify-between gap-4 mb-3 ${className}`}>
      <h2 className="text-[13px] font-semibold text-foreground tracking-tight">{children}</h2>
      {action}
    </div>
  );
}

/**
 * Empty state. Compact, factual, and always offers the next action — never a
 * bare "No data" in a box, and never an illustration.
 */
export function EmptyState({ icon: Icon, title, description, action, className = "" }: {
  icon?: React.ElementType;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex flex-col items-center justify-center text-center px-6 py-14 ${className}`}>
      {Icon && <Icon className="h-5 w-5 text-text-2/50 mb-3" aria-hidden />}
      <p className="text-sm font-medium text-foreground">{title}</p>
      {description && (
        <p className="text-[13px] text-muted-foreground mt-1.5 max-w-sm leading-relaxed">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/** Loading placeholder that matches the shape of what replaces it. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}
