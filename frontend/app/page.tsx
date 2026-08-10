"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ShieldCheck, PlusCircle, FileText, Activity,
  Zap, ChevronLeft, ChevronRight
} from "lucide-react";
import { SubmitClaimTab } from "@/components/dashboard/SubmitClaimTab";
import { ClaimReviewTab } from "@/components/dashboard/ClaimReviewTab";
import { ReviewQueueTab } from "@/components/dashboard/ReviewQueueTab";
import { AnalyticsTab } from "@/components/dashboard/AnalyticsTab";
import { HomeDashboard } from "@/components/dashboard/HomeDashboard";
import { SystemHealth } from "@/components/dashboard/SystemHealth";
import { getClaim } from "@/lib/api";

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState("overview");
  const [selectedClaim, setSelectedClaim] = useState<any>(null);
  const [claimError, setClaimError] = useState<string | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  // Collapse the sidebar to an icon rail on small screens. At 240px wide it left a phone
  // with about 135px of content, so every table and the investigation trace overflowed
  // horizontally. The toggle still works — this only picks a sane default per viewport.
  useEffect(() => {
    const narrow = window.matchMedia("(max-width: 1023px)");
    const apply = (e: MediaQueryList | MediaQueryListEvent) => setIsSidebarOpen(!e.matches);
    apply(narrow);
    narrow.addEventListener("change", apply);
    return () => narrow.removeEventListener("change", apply);
  }, []);

  const handleClaimSubmitted = (claim: any) => {
    setSelectedClaim(claim);
    setActiveTab("review");
  };

  // Opening a claim from a list has to re-fetch it: list endpoints return `ClaimSchema`,
  // which carries the verdict but not `audit_logs`. Handing the list row straight to the
  // review tab renders an investigation with an empty agent timeline — the one thing that
  // screen exists to show.
  const handleSelectClaim = async (claimId: number) => {
    setActiveTab("review");
    setSelectedClaim(null);
    try {
      setSelectedClaim(await getClaim(claimId));
    } catch (e: any) {
      setClaimError(e?.message ?? "Could not load that investigation.");
    }
  };

  // Only destinations that exist. "Pinned Claims", "Recent Activity" and "Settings" were
  // navigation items that led to a "Module coming soon" placeholder — three of the eight
  // entries in the primary navigation went nowhere. A first-time user cannot tell a
  // not-yet-built section from a broken one, so they are gone rather than stubbed.
  const navGroups = [
    {
      title: "Claims",
      items: [
        { id: "overview", label: "Overview", icon: Activity },
        { id: "submit", label: "New Investigation", icon: PlusCircle },
        { id: "review", label: "Investigations", icon: FileText },
      ]
    },
    {
      title: "Review",
      items: [
        { id: "queue", label: "Manual Review", icon: ShieldCheck },
        { id: "analytics", label: "Analytics", icon: Zap },
      ]
    },
  ];

  const activeLabel =
    navGroups.flatMap(g => g.items).find(i => i.id === activeTab)?.label ?? "AURELIX";

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground selection:bg-primary/30 font-sans">
      {/* Sidebar */}
      <motion.aside 
        initial={false}
        animate={{ width: isSidebarOpen ? 240 : 64 }}
        className="border-r border-border/50 bg-sidebar flex flex-col shrink-0 relative z-20"
      >
        <div className="h-12 flex items-center px-4 border-b border-border/50 overflow-hidden shrink-0">
          <ShieldCheck className="h-5 w-5 text-primary shrink-0 mr-3" />
          <AnimatePresence>
            {isSidebarOpen && (
              <motion.span 
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -10 }}
                className="font-semibold tracking-tight text-sm text-foreground whitespace-nowrap"
              >
                AURELIX
              </motion.span>
            )}
          </AnimatePresence>
        </div>
        
        <button 
          onClick={() => setIsSidebarOpen(!isSidebarOpen)}
          className="absolute -right-3 top-16 bg-border/80 text-muted-foreground hover:text-foreground rounded-full p-1 border border-border z-30"
        >
          {isSidebarOpen ? <ChevronLeft className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </button>

        <nav className="flex-1 px-2 py-4 overflow-y-auto overflow-x-hidden space-y-6">
          {navGroups.map((group, i) => (
            <div key={i} className="space-y-1">
              <AnimatePresence>
                {isSidebarOpen && (
                  <motion.div 
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="px-2 text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70 mb-2 whitespace-nowrap"
                  >
                    {group.title}
                  </motion.div>
                )}
              </AnimatePresence>
              {group.items.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setActiveTab(item.id)}
                  className={`w-full flex items-center px-2 py-1.5 rounded-md text-xs font-medium transition-colors group ${
                    activeTab === item.id 
                      ? "bg-primary/10 text-primary" 
                      : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                  }`}
                  title={!isSidebarOpen ? item.label : undefined}
                >
                  <item.icon className={`h-4 w-4 shrink-0 ${isSidebarOpen ? "mr-3" : "mx-auto"} ${activeTab === item.id ? "text-primary" : "text-muted-foreground group-hover:text-foreground"}`} />
                  <AnimatePresence>
                    {isSidebarOpen && (
                      <motion.span 
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="whitespace-nowrap"
                      >
                        {item.label}
                      </motion.span>
                    )}
                  </AnimatePresence>
                </button>
              ))}
            </div>
          ))}
        </nav>
      </motion.aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col h-full overflow-hidden relative bg-[#0a0a0c]">
        {/* Topbar */}
        {/*
          The topbar carried a search field that searched nothing, a notification bell with
          a permanent unread dot and no notifications behind it, and an avatar for a product
          with no accounts. All three were removed rather than stubbed: a control that looks
          live and does nothing costs a first-time user more than an absent one.

          What remains is the one thing here that reports real state.
        */}
        <header className="h-12 border-b border-border/50 bg-background/95 backdrop-blur flex items-center justify-between gap-4 px-4 shrink-0 z-10">
          <div className="flex items-center gap-2 min-w-0">
            <ShieldCheck className="h-4 w-4 text-primary shrink-0 lg:hidden" />
            <span className="text-sm font-medium text-foreground truncate">{activeLabel}</span>
          </div>

          {/* System health — measured, not decorative. This read "Gemini: 100%",
              "Redis: 2ms", "API: 14ms" as hardcoded strings; an indicator that reports
              health it never checked says "green" while the backend is down. */}
          <SystemHealth />
        </header>

        {/* Scrollable Page Content */}
        <main className="flex-1 overflow-y-auto relative custom-scrollbar">
          <AnimatePresence mode="wait">
            <motion.div 
              key={activeTab}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.2 }}
              className="min-h-full p-4 lg:p-6"
            >
              <div className="max-w-[1400px] mx-auto">
                {activeTab === "overview" && (
                  <HomeDashboard onNavigate={setActiveTab} onSelectClaim={handleSelectClaim} />
                )}
                {activeTab === "submit" && <SubmitClaimTab onClaimSubmitted={handleClaimSubmitted} />}
                {activeTab === "review" && (
                  <>
                    {claimError && (
                      <div className="mb-4 p-4 rounded-lg bg-destructive/10 text-destructive border border-destructive/20 text-sm">
                        {claimError}
                      </div>
                    )}
                    <ClaimReviewTab
                      claim={selectedClaim}
                      onNavigate={setActiveTab}
                      // The verdict endpoint returns the updated row but not its audit
                      // trail, so re-fetch the detail rather than rendering a claim whose
                      // agent timeline has silently vanished.
                      onClaimUpdated={updated => handleSelectClaim(updated.id)}
                    />
                  </>
                )}
                {activeTab === "queue" && <ReviewQueueTab onSelectClaim={handleSelectClaim} />}
                {activeTab === "analytics" && <AnalyticsTab />}
              </div>
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}
