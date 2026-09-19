"use client";

/**
 * The settings behind the header popover, kept in `localStorage`.
 *
 * `useSyncExternalStore` reads each one, with the default as the server
 * snapshot: the first client render matches the HTML and the stored value is
 * applied right after, so there is no hydration mismatch. The subscription is
 * what keeps the header control and the rest of the page on the same value, in
 * this tab and in another one.
 */

import { useSyncExternalStore } from "react";

import { applyTheme, DEFAULT_THEME, parseTheme, type Theme, THEME_STORAGE_KEY } from "@/lib/theme";

type StoredSetting<T> = {
  use: () => T;
  set: (value: T) => void;
};

function createStoredSetting<T extends string | boolean>(options: {
  key: string;
  fallback: T;
  parse: (raw: string | null) => T;
  /** Runs after a write here and after a write in another tab. */
  onChange?: (value: T) => void;
}): StoredSetting<T> {
  const { key, fallback, parse, onChange } = options;
  const listeners = new Set<() => void>();

  // Reading localStorage on every render would be wasteful and, in a private
  // window with storage blocked, would throw. The cache is filled once and then
  // only by a write or by another tab's.
  let cached: T | undefined;

  function read(): T {
    try {
      return parse(window.localStorage.getItem(key));
    } catch {
      return fallback;
    }
  }

  function subscribe(notify: () => void): () => void {
    const onStorage = (event: StorageEvent) => {
      if (event.key === null || event.key === key) {
        cached = read();
        onChange?.(cached);
        notify();
      }
    };
    listeners.add(notify);
    window.addEventListener("storage", onStorage);
    return () => {
      listeners.delete(notify);
      window.removeEventListener("storage", onStorage);
    };
  }

  function getSnapshot(): T {
    cached ??= read();
    return cached;
  }

  return {
    use: () => useSyncExternalStore(subscribe, getSnapshot, () => fallback),
    set(value) {
      cached = value;
      try {
        window.localStorage.setItem(key, String(value));
      } catch {
        // A browser with storage blocked keeps the setting for this page only.
      }
      onChange?.(value);
      for (const listener of listeners) {
        listener();
      }
    },
  };
}

const showToolCalls = createStoredSetting<boolean>({
  key: "scrooge:show-tool-calls",
  fallback: false,
  parse: (raw) => raw === "true",
});

// The inline script in the root layout applies the stored theme before the
// first paint. This store takes over from there.
const theme = createStoredSetting<Theme>({
  key: THEME_STORAGE_KEY,
  fallback: DEFAULT_THEME,
  parse: parseTheme,
  onChange: applyTheme,
});

/** True when the conversation should show the raw tool call cards. */
export const useShowToolCalls = showToolCalls.use;
export const setShowToolCalls = showToolCalls.set;

/** The stored preference, not the palette on screen: "system" stays "system". */
export const useTheme = theme.use;
export const setTheme = theme.set;
