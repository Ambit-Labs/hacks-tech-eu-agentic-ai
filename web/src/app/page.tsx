import Image from "next/image";

import { Chat } from "@/components/chat/chat";
import { ChatSettings } from "@/components/chat/settings";

// The same file Next serves as the tab icon.
import logo from "./icon.svg";

export default function Home() {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-center justify-between gap-3 border-b px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2">
          {/* Decorative: the name is spelled out beside it. */}
          <Image alt="" className="size-7" src={logo} unoptimized />
          <span className="font-semibold text-sm tracking-tight">Scrooge</span>
        </div>
        <ChatSettings />
      </header>
      <Chat />
    </div>
  );
}
