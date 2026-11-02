import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "@taxrisk/design/tokens.css";
import "@taxrisk/design/components.css";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";

export const metadata: Metadata = {
  title: {
    default: "Tax Compliance Risk Platform",
    template: "%s · Tax Compliance Risk Platform",
  },
  description: "Compliance risk operations console for revenue authorities (synthetic demo data).",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
