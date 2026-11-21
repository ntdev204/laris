import { ChatWorkspace } from "@/components/chat-workspace";
import { maxRequestBytes } from "@/lib/config";

export const dynamic = "force-dynamic";

export default function Home() {
  return <ChatWorkspace maxRequestBytes={maxRequestBytes} />;
}
