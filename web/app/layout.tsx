import type { Metadata } from "next";
import "./globals.css";
import "@univerjs/preset-sheets-core/lib/index.css";

export const metadata: Metadata = {
  title: "Submission Builder",
  description: "A thoughtful workspace for your next submission.",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
