import type { Metadata } from "next";
import { SessionProvider } from "next-auth/react";
import { ThemeProvider } from "@/components/providers/ThemeProvider";
import { AgentThemingProvider } from "@/hooks/useAgentTheming";
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
      <head>
        <link rel="stylesheet" href="/theme.local.css" />
      </head>
      <body className="font-sans antialiased">
        <SessionProvider>
          <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
            <AgentThemingProvider>
              <div className="flex h-screen flex-col">{children}</div>
            </AgentThemingProvider>
          </ThemeProvider>
        </SessionProvider>
      </body>
    </html>
  );
}
