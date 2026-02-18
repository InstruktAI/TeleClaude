import { QueryProvider } from "@/lib/query/QueryProvider";
import { WebSocketProvider } from "@/lib/ws/WebSocketProvider";
import { CacheInvalidation } from "@/lib/ws/CacheInvalidation";
import { SidebarProvider } from "@/components/sidebar/SidebarProvider";

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <QueryProvider>
      <WebSocketProvider>
        <CacheInvalidation />
        <SidebarProvider>
          <div className="flex h-screen">{children}</div>
        </SidebarProvider>
      </WebSocketProvider>
    </QueryProvider>
  );
}
