import type { Metadata } from "next";
import { ThemeProvider } from "next-themes";
import "./globals.css";

export const dynamic = "force-dynamic";

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
    <html lang="en" suppressHydrationWarning>
      <body className="font-sans antialiased">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <div className="flex h-screen flex-col">{children}</div>
        </ThemeProvider>
      </body>
    </html>
  );
}
