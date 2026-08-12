"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

/**
 * Theme switch.
 *
 * The class is applied by an inline script in `layout.tsx` before first paint —
 * doing it here would mean React hydrates, *then* flips the theme, and the user
 * sees a white flash on every load in dark mode.
 *
 * This component only owns the control. It reads what the script already
 * decided, so the two can never disagree.
 */
export function ThemeToggle() {
  const [dark, setDark] = useState(true);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
    setReady(true);
  }, []);

  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try { localStorage.setItem("aurelix-theme", next ? "dark" : "light"); } catch {}
  };

  return (
    <button
      onClick={toggle}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Light theme" : "Dark theme"}
      className="h-8 w-8 shrink-0 flex items-center justify-center rounded-md text-muted-foreground
                 hover:text-foreground hover:bg-surface-2 transition-colors duration-(--dur-fast)"
    >
      {/* Rendered only once mounted, so server and client markup agree. */}
      {ready && (dark
        ? <Sun className="h-4 w-4" aria-hidden />
        : <Moon className="h-4 w-4" aria-hidden />)}
    </button>
  );
}
