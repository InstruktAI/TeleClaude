import { QueryProvider } from "@/lib/query/QueryProvider";
import { WebSocketProvider } from "@/lib/ws/WebSocketProvider";

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <QueryProvider>
      <WebSocketProvider>{children}</WebSocketProvider>
    </QueryProvider>
  );
}
