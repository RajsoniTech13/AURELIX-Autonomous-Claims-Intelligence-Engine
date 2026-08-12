import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AURELIX — Autonomous Trust Intelligence for Damage Claims",
  description:
    "Multimodal claim verification. Evidence is read by a single model call; every decision is produced by deterministic rules and recorded with the rule that made it.",
};

/**
 * Resolve the theme before first paint.
 *
 * Applying the class from React would mean the page renders in the default
 * theme, hydrates, and only then flips — a white flash on every load for a
 * dark-mode user. Stored choice wins; otherwise follow the OS. Defaults to dark
 * because that is what the product ships as.
 */
const THEME_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem('aurelix-theme');
    var dark = stored
      ? stored === 'dark'
      : !window.matchMedia('(prefers-color-scheme: light)').matches;
    document.documentElement.classList.toggle('dark', dark);
  } catch (e) {
    document.documentElement.classList.add('dark');
  }
})();
`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-full w-full flex font-sans bg-background text-foreground">
        {children}
      </body>
    </html>
  );
}
