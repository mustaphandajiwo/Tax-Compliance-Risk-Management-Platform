import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "@ngsirs/design/tokens.css";
import "@ngsirs/design/components.css";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";

export const metadata: Metadata = {
  title: {
    default: "NGSIRS Compliance Risk Management Platform",
    template: "%s · NGSIRS Compliance Risk Management Platform",
  },
  description: "Niger State Internal Revenue Service compliance risk operations console (synthetic demo data).",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-NG">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
