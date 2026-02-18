import { WebSocketProvider } from "@/lib/ws/WebSocketProvider";

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <WebSocketProvider>{children}</WebSocketProvider>;
}
