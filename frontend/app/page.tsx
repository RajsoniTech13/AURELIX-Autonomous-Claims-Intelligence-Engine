"use client";

import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity, PlusCircle, FileText, ShieldCheck, BarChart3,
  PanelLeftClose, PanelLeftOpen, Menu, X,
} from "lucide-react";
import { SubmitClaimTab } from "@/components/dashboard/SubmitClaimTab";
import { ClaimReviewTab } from "@/components/dashboard/ClaimReviewTab";
import { ReviewQueueTab } from "@/components/dashboard/ReviewQueueTab";
import { AnalyticsTab } from "@/components/dashboard/AnalyticsTab";
import { HomeDashboard } from "@/components/dashboard/HomeDashboard";
import { SystemHealth } from "@/components/dashboard/SystemHealth";
import { ThemeToggle } from "@/components/dashboard/ThemeToggle";
import { getClaim } from "@/lib/api";

/**
 * Destinations. Only routes that exist — three navigation items used to lead to
 * a "Module coming soon" placeholder, which a first-time user cannot tell apart
 * from a broken link.
 */
const NAV = [
  {
    title: "Claims",
    items: [
      { id: "overview", label: "Overview", icon: Activity },
      { id: "submit", label: "New Investigation", icon: PlusCircle },
      { id: "review", label: "Investigations", icon: FileText },
    ],
  },
  {
    title: "Review",
    items: [
      { id: "queue", label: "Manual Review", icon: ShieldCheck },
      { id: "analytics", label: "Analytics", icon: BarChart3 },
    ],
  },
];

const ALL_ITEMS = NAV.flatMap(g => g.items);

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState("overview");
  const [selectedClaim, setSelectedClaim] = useState<any>(null);
  const [claimError, setClaimError] = useState<string | null>(null);
  const [claimLoading, setClaimLoading] = useState(false);
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const active = ALL_ITEMS.find(i => i.id === activeTab);

  const go = useCallback((tab: string) => {
    setActiveTab(tab);
    setMobileNavOpen(false);
  }, []);

  /**
   * Opening a claim from a list re-fetches it: list endpoints return the
   * verdict but not `audit_logs`, and handing a list row straight to the case
   * file renders an investigation with an empty reasoning trace — the one thing
   * that screen exists to show.
   */
  const openClaim = useCallback(async (claimId: number) => {
    setActiveTab("review");
    setMobileNavOpen(false);
    setSelectedClaim(null);
    setClaimError(null);
    setClaimLoading(true);
    try {
      setSelectedClaim(await getClaim(claimId));
    } catch (e: any) {
      setClaimError(e?.message ?? "That investigation could not be loaded.");
    } finally {
      setClaimLoading(false);
    }
  }, []);

  // Close the mobile drawer on Escape — a drawer with no keyboard exit is a trap.
  useEffect(() => {
    if (!mobileNavOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMobileNavOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileNavOpen]);

  const navList = (collapsed: boolean) => (
    <nav className="flex-1 overflow-y-auto overflow-x-hidden py-3" aria-label="Primary">
      {NAV.map(group => (
        <div key={group.title} className="px-3 mb-5 last:mb-0">
          {!collapsed && <div className="label-meta px-2 mb-1.5">{group.title}</div>}
          <ul className="space-y-0.5">
            {group.items.map(item => {
              const isActive = activeTab === item.id;
              return (
                <li key={item.id}>
                  <button
                    onClick={() => go(item.id)}
                    aria-current={isActive ? "page" : undefined}
                    title={collapsed ? item.label : undefined}
                    className={`group relative w-full flex items-center rounded-md text-[13px] font-medium
                                h-8 transition-colors duration-(--dur-fast)
                                ${collapsed ? "justify-center px-0" : "px-2 gap-2.5"}
                                ${isActive
                                  ? "bg-surface-2 text-foreground"
                                  : "text-muted-foreground hover:text-foreground hover:bg-surface-2/60"}`}
                  >
                    {/* A 2px inset marker rather than a glowing pill — the active
                        row should read as a selected workspace. */}
                    <span
                      aria-hidden
                      className={`absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full transition-opacity
                                  duration-(--dur-fast) bg-(--aurelix-accent)
                                  ${isActive ? "opacity-100" : "opacity-0"}`}
                    />
                    <item.icon
                      className={`h-4 w-4 shrink-0 transition-colors ${
                        isActive ? "text-(--aurelix-accent)" : "text-muted-foreground group-hover:text-foreground"
                      }`}
                      aria-hidden
                    />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );

  const brand = (collapsed: boolean) => (
    <div className={`h-14 flex items-center border-b border-line shrink-0 ${collapsed ? "justify-center px-0" : "px-4"}`}>
      <div className="h-6 w-6 rounded bg-(--aurelix-accent-weak) border border-(--aurelix-accent-line) flex items-center justify-center shrink-0">
        <ShieldCheck className="h-3.5 w-3.5 text-(--aurelix-accent)" aria-hidden />
      </div>
      {!collapsed && (
        <div className="ml-2.5 min-w-0">
          <div className="text-[13px] font-semibold tracking-tight leading-none">AURELIX</div>
          <div className="text-[10px] text-muted-foreground leading-none mt-1 tracking-wide">
            Trust Intelligence
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div className="flex h-dvh w-full overflow-hidden text-foreground">
      {/* ── Desktop rail ─────────────────────────────────────────────────── */}
      <aside
        className={`hidden lg:flex flex-col shrink-0 border-r border-line bg-surface-1
                    transition-[width] duration-(--dur-base) ease-(--ease-out)
                    ${railCollapsed ? "w-[60px]" : "w-[228px]"}`}
      >
        {brand(railCollapsed)}
        {navList(railCollapsed)}
        <div className="border-t border-line p-2">
          <button
            onClick={() => setRailCollapsed(v => !v)}
            aria-label={railCollapsed ? "Expand navigation" : "Collapse navigation"}
            className="w-full h-8 flex items-center justify-center rounded-md text-muted-foreground
                       hover:text-foreground hover:bg-surface-2 transition-colors duration-(--dur-fast)"
          >
            {railCollapsed
              ? <PanelLeftOpen className="h-4 w-4" aria-hidden />
              : <PanelLeftClose className="h-4 w-4" aria-hidden />}
          </button>
        </div>
      </aside>

      {/* ── Mobile drawer ────────────────────────────────────────────────── */}
      <AnimatePresence>
        {mobileNavOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              onClick={() => setMobileNavOpen(false)}
              className="lg:hidden fixed inset-0 z-40 bg-black/60"
              aria-hidden
            />
            <motion.aside
              initial={{ x: -260 }} animate={{ x: 0 }} exit={{ x: -260 }}
              transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
              className="lg:hidden fixed inset-y-0 left-0 z-50 w-[248px] flex flex-col
                         border-r border-line bg-surface-1"
              role="dialog"
              aria-modal="true"
              aria-label="Navigation"
            >
              <div className="flex items-center justify-between border-b border-line pr-2">
                <div className="flex-1">{brand(false)}</div>
                <button
                  onClick={() => setMobileNavOpen(false)}
                  aria-label="Close navigation"
                  className="h-8 w-8 flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground"
                >
                  <X className="h-4 w-4" aria-hidden />
                </button>
              </div>
              {navList(false)}
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      {/* ── Workspace ────────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 shrink-0 border-b border-line bg-surface-1/70 backdrop-blur-xl
                           flex items-center justify-between gap-3 px-3 sm:px-5 z-20">
          <div className="flex items-center gap-2.5 min-w-0">
            <button
              onClick={() => setMobileNavOpen(true)}
              aria-label="Open navigation"
              className="lg:hidden h-8 w-8 flex items-center justify-center rounded-md
                         text-muted-foreground hover:text-foreground hover:bg-surface-2"
            >
              <Menu className="h-4 w-4" aria-hidden />
            </button>
            <h1 className="text-sm font-semibold tracking-tight truncate">{active?.label ?? "AURELIX"}</h1>
          </div>
          <div className="flex items-center gap-2 sm:gap-3 shrink-0">
            <SystemHealth />
            <div className="h-4 w-px bg-line hidden md:block" aria-hidden />
            <ThemeToggle />
          </div>
        </header>

        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1400px] px-4 sm:px-6 py-5 sm:py-7">
            <AnimatePresence mode="wait">
              <motion.div
                key={activeTab}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
              >
                {activeTab === "overview" && (
                  <HomeDashboard onNavigate={go} onSelectClaim={openClaim} />
                )}
                {activeTab === "submit" && (
                  // Re-fetch rather than handing over the streamed claim: the SSE payload
                  // carries the audit trail's reasoning but not each stage's structured
                  // `outputs`, which is what the case file reads to show claimed against
                  // observed. Passing the streamed object straight through renders a case
                  // file with the comparison table missing.
                  <SubmitClaimTab onClaimSubmitted={claim => openClaim(claim.id)} onNavigate={go} />
                )}
                {activeTab === "review" && (
                  <ClaimReviewTab
                    claim={selectedClaim}
                    loading={claimLoading}
                    error={claimError}
                    onNavigate={go}
                    onClaimUpdated={updated => openClaim(updated.id)}
                  />
                )}
                {activeTab === "queue" && <ReviewQueueTab onSelectClaim={openClaim} onNavigate={go} />}
                {activeTab === "analytics" && <AnalyticsTab />}
              </motion.div>
            </AnimatePresence>
          </div>
        </main>
      </div>
    </div>
  );
}
