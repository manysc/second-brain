import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Second Brain", description: "Evidence-backed work intelligence" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
