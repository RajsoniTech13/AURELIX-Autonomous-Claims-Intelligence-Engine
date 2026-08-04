"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { 
  ShieldCheck, PlusCircle, Search, 
  FileText, Activity, Settings, Bell, User, 
  Database, Zap, Clock, ChevronLeft, ChevronRight, Pin, History
} from "lucide-react";
import { SubmitClaimTab } from "@/components/dashboard/SubmitClaimTab";
import { ClaimReviewTab } from "@/components/dashboard/ClaimReviewTab";
import { ReviewQueueTab } from "@/components/dashboard/ReviewQueueTab";
import { AnalyticsTab } from "@/components/dashboard/AnalyticsTab";
import { HomeDashboard } from "@/components/dashboard/HomeDashboard";

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState("overview");
  const [selectedClaim, setSelectedClaim] = useState<any>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  const handleClaimSubmitted = (claim: any) => {
    setSelectedClaim(claim);
    setActiveTab("review");
  };

  const navGroups = [
    {
      title: "Main",
      items: [
        { id: "overview", label: "Overview", icon: Activity },
        { id: "submit", label: "New Investigation", icon: PlusCircle },
        { id: "review", label: "Investigations", icon: FileText },
        { id: "analytics", label: "Analytics", icon: Zap },
      ]
    },
    {
      title: "Queue",
      items: [
        { id: "queue", label: "Manual Review", icon: ShieldCheck },
        { id: "pinned", label: "Pinned Claims", icon: Pin },
        { id: "recent", label: "Recent Activity", icon: History },
      ]
    },
    {
      title: "System",
      items: [
        { id: "settings", label: "Settings", icon: Settings },
      ]
    }
  ];

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
        <header className="h-12 border-b border-border/50 bg-background/95 backdrop-blur flex items-center justify-between px-4 shrink-0 z-10">
          <div className="flex items-center space-x-4">
            <div className="relative group">
              <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground group-focus-within:text-primary transition-colors" />
              <input 
                type="text" 
                placeholder="Search claims, rules, agents..." 
                className="h-8 w-[300px] bg-muted/20 border border-border/40 rounded-md pl-8 pr-3 text-xs focus:outline-none focus:ring-1 focus:ring-primary/50 transition-all placeholder:text-muted-foreground/50 focus:bg-background"
              />
              <div className="absolute right-2 top-1/2 -translate-y-1/2 flex gap-1">
                <span className="text-[9px] font-mono bg-muted/40 px-1.5 py-0.5 rounded text-muted-foreground">⌘</span>
                <span className="text-[9px] font-mono bg-muted/40 px-1.5 py-0.5 rounded text-muted-foreground">K</span>
              </div>
            </div>
          </div>
          
          <div className="flex items-center space-x-4">
            {/* System Health Indicators */}
            <div className="hidden lg:flex items-center space-x-3 border-r border-border/50 pr-4">
              <div className="flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground">
                <Activity className="h-3 w-3 text-emerald-500" />
                Gemini: <span className="text-emerald-500 font-mono">100%</span>
              </div>
              <div className="flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground">
                <Database className="h-3 w-3 text-emerald-500" />
                Redis: <span className="text-foreground font-mono">2ms</span>
              </div>
              <div className="flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground">
                <Clock className="h-3 w-3 text-emerald-500" />
                API: <span className="text-foreground font-mono">14ms</span>
              </div>
            </div>
            
            <button className="relative text-muted-foreground hover:text-foreground transition-colors">
              <Bell className="h-4 w-4" />
              <span className="absolute -top-0.5 -right-0.5 h-1.5 w-1.5 rounded-full bg-primary" />
            </button>
            <div className="h-6 w-6 rounded-full bg-primary/20 border border-primary/30 flex items-center justify-center cursor-pointer">
              <User className="h-3 w-3 text-primary" />
            </div>
          </div>
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
                {activeTab === "overview" && <HomeDashboard onNavigate={setActiveTab} />}
                {activeTab === "submit" && <SubmitClaimTab onClaimSubmitted={handleClaimSubmitted} />}
                {activeTab === "review" && <ClaimReviewTab claim={selectedClaim} />}
                {activeTab === "queue" && <ReviewQueueTab />}
                {activeTab === "analytics" && <AnalyticsTab />}
                
                {["pinned", "recent", "settings"].includes(activeTab) && (
                  <div className="flex flex-col items-center justify-center h-[60vh] text-muted-foreground">
                    <Activity className="h-8 w-8 mb-4 opacity-20" />
                    <p className="text-sm">Module coming soon.</p>
                  </div>
                )}
              </div>
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}
