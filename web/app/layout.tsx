import type { Metadata } from "next";
import { IBM_Plex_Mono, Newsreader } from "next/font/google";
import "./globals.css";

/* Two faces, each with one job. Mono carries every machine-produced value: ids, scores,
 * timecodes, years. The serif carries prose a person reads: the answer, the chronology, the
 * caveats. Keeping those apart is what stops a research tool from reading as a dashboard. */

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
  display: "swap",
});

const serif = Newsreader({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-serif",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Mission Control — NASA archive research agent",
  description:
    "Ask a question, get a cited answer and an auto-edited evidence reel stitched from real NASA archival footage.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${mono.variable} ${serif.variable}`}>
      <body>{children}</body>
    </html>
  );
}
