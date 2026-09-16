import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, IBM_Plex_Sans_Arabic } from "next/font/google";
import { AppShell } from "@/components/layout/AppShell";
import { SimulationProvider } from "@/components/providers/SimulationProvider";
import { TooltipProvider } from "@/components/common/Tooltip";
import "./globals.css";

const geist = Geist({ variable: "--font-geist", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const plexArabic = IBM_Plex_Sans_Arabic({ variable: "--font-plex-arabic", subsets: ["arabic"], weight: ["500", "600", "700"] });

export const metadata: Metadata = {
  title: { default: "Dallal · دلّال — Disrupted shipment intelligence", template: "%s · Dallal" },
  description: "Operations prototype for predicting, diagnosing and recovering disrupted last-mile shipments in the Eastern Province. Simulated scenario data.",
};

export const viewport: Viewport = { themeColor: "#ffffff", colorScheme: "light" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geist.variable} ${geistMono.variable} ${plexArabic.variable} h-full antialiased`}>
      <body className="min-h-full">
        <TooltipProvider>
          <SimulationProvider>
            <AppShell>{children}</AppShell>
          </SimulationProvider>
        </TooltipProvider>
      </body>
    </html>
  );
}
