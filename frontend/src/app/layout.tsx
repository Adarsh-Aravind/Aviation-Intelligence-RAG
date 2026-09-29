import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Toaster } from "sonner";

import { AppShell } from "@/components/app-shell";
import { SessionProvider } from "@/components/session-provider";

import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const jetbrains = JetBrains_Mono({ variable: "--font-jetbrains", subsets: ["latin"] });

export const metadata: Metadata = {
  title: {
    default: "Aviation Intelligence — Grounded answers from aviation documents",
    template: "%s · Aviation Intelligence",
  },
  description:
    "Ask questions about aviation manuals, handbooks and regulations. Answers are generated only from retrieved documents, with page-level citations.",
};

export const viewport: Viewport = {
  themeColor: "#060a13",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrains.variable} antialiased`}>
      <body className="font-sans">
        <SessionProvider>
          <AppShell>{children}</AppShell>
        </SessionProvider>
        <Toaster
          theme="dark"
          position="top-right"
          toastOptions={{ style: { background: "#101a2d", border: "1px solid #1d2a44", color: "#e6edf7" } }}
        />
      </body>
    </html>
  );
}
