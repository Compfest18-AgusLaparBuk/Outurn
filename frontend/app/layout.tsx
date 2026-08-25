import type { Metadata } from "next";
import "./globals.css";
import "./quality-overrides.css";
import "./assurance-workspace.css";
import "./shipment-assurance.css";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  title: {
    default: "Outurn — Shipment assurance workspace",
    template: "%s | Outurn",
  },
  description: "A controlled workspace for reconciling shipment documents, resolving exceptions, and recording evidence-backed release decisions.",
  applicationName: "Outurn",
  category: "Business operations",
  robots: {
    index: false,
    follow: false,
    googleBot: { index: false, follow: false, noimageindex: true },
  },
  openGraph: {
    title: "Outurn — Shipment assurance workspace",
    description: "Evidence-backed shipment document reconciliation and release decisions.",
    type: "website",
    siteName: "Outurn",
  },
  twitter: {
    card: "summary",
    title: "Outurn — Shipment assurance workspace",
    description: "Evidence-backed shipment document reconciliation and release decisions.",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="id">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
