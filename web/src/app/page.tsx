import { WrenchIcon } from "lucide-react";

import { Chat } from "@/components/chat/chat";
import { Badge } from "@/components/ui/badge";
import { CHAT_MODEL_LABEL } from "@/lib/model";

export default function Home() {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-center justify-between gap-3 border-b px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2">
          <WrenchIcon className="size-4 text-muted-foreground" />
          <span className="font-semibold text-sm tracking-tight">Toolbelt</span>
        </div>
        <Badge className="font-mono text-xs" variant="secondary">
          {CHAT_MODEL_LABEL}
        </Badge>
      </header>
      <Chat />
    </div>
  );
}
