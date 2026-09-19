"use client";

/**
 * The settings popover in the header.
 *
 * It is a client component of its own so the page around it stays a server
 * component. The values live in `@/lib/settings`, which the conversation reads
 * from the same store.
 */

import { MonitorIcon, MoonIcon, SettingsIcon, SunIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Switch } from "@/components/ui/switch";
import { setShowToolCalls, setTheme, useShowToolCalls, useTheme } from "@/lib/settings";
import type { Theme } from "@/lib/theme";

const THEME_OPTIONS: { value: Theme; label: string; icon: typeof SunIcon }[] = [
  { value: "light", label: "Light", icon: SunIcon },
  { value: "dark", label: "Dark", icon: MoonIcon },
  { value: "system", label: "System", icon: MonitorIcon },
];

export function ChatSettings() {
  const showToolCalls = useShowToolCalls();
  const theme = useTheme();

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button aria-label="Settings" size="icon-sm" variant="ghost">
          <SettingsIcon />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="flex w-80 flex-col gap-3">
        <div className="flex items-center justify-between gap-3 p-1">
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="font-medium text-sm" id="theme-label">
              Theme
            </span>
            <span className="text-muted-foreground text-xs">System follows your device.</span>
          </div>
          <ButtonGroup aria-labelledby="theme-label">
            {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
              <Button
                aria-label={label}
                aria-pressed={theme === value}
                key={value}
                onClick={() => setTheme(value)}
                size="icon-sm"
                title={label}
                variant={theme === value ? "default" : "outline"}
              >
                <Icon />
              </Button>
            ))}
          </ButtonGroup>
        </div>
        <div className="flex items-start justify-between gap-3 p-1">
          <label className="flex min-w-0 flex-col gap-0.5" htmlFor="show-tool-calls">
            <span className="font-medium text-sm">Show tool calls</span>
            <span className="text-muted-foreground text-xs">
              Puts the tool name, the arguments it was given and the raw result under every answer.
            </span>
          </label>
          <Switch checked={showToolCalls} id="show-tool-calls" onCheckedChange={setShowToolCalls} />
        </div>
      </PopoverContent>
    </Popover>
  );
}
