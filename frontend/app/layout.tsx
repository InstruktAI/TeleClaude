import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TeleClaude",
  description: "TeleClaude Web Interface",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <div className="flex h-screen flex-col">{children}</div>
      </body>
    </html>
  );
}
