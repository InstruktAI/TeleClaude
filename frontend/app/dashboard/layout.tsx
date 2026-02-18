import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { QueryProvider } from "@/lib/query/QueryProvider";
import { WebSocketProvider } from "@/lib/ws/WebSocketProvider";
import { CacheInvalidation } from "@/lib/ws/CacheInvalidation";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();

  if (!session?.user?.role || session.user.role !== "admin") {
    redirect("/");
  }

  return (
    <QueryProvider>
      <WebSocketProvider>
        <CacheInvalidation />
        {children}
      </WebSocketProvider>
    </QueryProvider>
  );
}
