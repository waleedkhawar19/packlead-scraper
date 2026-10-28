import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ToastProvider } from "@/components/ui/toast";

export const metadata: Metadata = {
  title: { default: "PackLead Scraper", template: "%s · PackLead Scraper" },
  description: "Find publicly listed business emails for packaging prospects, organise the leads and export them to Excel.",
};
export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0f2a4a" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
