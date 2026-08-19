import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Restoran Suriani - Accounts",
  description:
    "Restaurant accounting with a one-tap owner view and a full double-entry ledger underneath.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // The owner may need to zoom. Never lock that away.
  maximumScale: 5,
  themeColor: "#0a0f1c",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
