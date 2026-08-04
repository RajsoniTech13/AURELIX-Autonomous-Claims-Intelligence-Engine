import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AURELIX — Autonomous Trust Intelligence for Damage Claims",
  description: "Enterprise-grade multimodal AI claims intelligence platform. Upload damage images, run autonomous AI investigation, and get explainable decisions powered by Gemini Vision and LangGraph.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} h-full antialiased dark`}
    >
      <body className="min-h-full w-full flex font-sans bg-background text-foreground">{children}</body>
    </html>
  );
}
