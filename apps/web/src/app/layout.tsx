import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "TaxCRIS", template: "%s · TaxCRIS" },
  description: "Compliance risk management and intelligence for State Internal Revenue Services. Risk signals are indicators for human review.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0b5e3c" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-NG">
      <body>
        <a className="skip-link" href="#main">
          Skip to main content
        </a>
        <div className="demo-banner" role="note">
          <strong>Synthetic demo data</strong> — fictional taxpayers. Risk indicators are prompts for human review, never proof of evasion.
        </div>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
