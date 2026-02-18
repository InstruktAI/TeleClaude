import { QueryProvider } from "@/lib/query/QueryProvider";
import { WebSocketProvider } from "@/lib/ws/WebSocketProvider";
import { CacheInvalidation } from "@/lib/ws/CacheInvalidation";

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <QueryProvider>
      <WebSocketProvider>
        <CacheInvalidation />
        {children}
      </WebSocketProvider>
    </QueryProvider>
  );
}
