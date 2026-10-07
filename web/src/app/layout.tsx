import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import AppShell from "./AppShell";
import ServiceWorker from "./ServiceWorker";
import "../styles.css";

export const metadata: Metadata = {
  title: "Grocery Price Optimizer",
  description: "Receipts in, cheapest shopping plan out.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
        <ServiceWorker />
      </body>
    </html>
  );
}
