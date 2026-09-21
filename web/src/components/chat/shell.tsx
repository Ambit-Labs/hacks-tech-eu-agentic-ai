"use client";

/**
 * The header and the conversation under it.
 *
 * They share a client component because the logo starts a new chat: the
 * conversation lives in `Chat`'s own state, so a new key remounts it empty.
 */

import { useState } from "react";

import { Chat } from "@/components/chat/chat";
import { SiteHeader } from "@/components/site-header";

export function ChatShell() {
  const [chatKey, setChatKey] = useState(0);
  const [isEmpty, setIsEmpty] = useState(true);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <SiteHeader onNewChat={() => setChatKey((key) => key + 1)} showNewChat={!isEmpty} />
      <Chat key={chatKey} onEmptyChange={setIsEmpty} />
    </div>
  );
}
