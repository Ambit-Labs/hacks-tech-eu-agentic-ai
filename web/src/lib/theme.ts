/**
 * The theme preference: what it can be, where it is stored and how it reaches
 * the page.
 *
 * This file has no "use client" so the root layout, a server component, can
 * import the inline script as a plain string. `@/lib/settings` holds the React
 * side.
 *
 * `globals.css` reads the preference off `<html>`: `class="dark"` and
 * `class="light"` pin a palette, and no class follows the OS setting.
 *
 * Light is the default. A visitor who has never opened the settings gets the
 * light palette whatever their OS says, and "system" is something they opt
 * into.
 */

export type Theme = "system" | "light" | "dark";

export const THEME_STORAGE_KEY = "scrooge:theme";

export const DEFAULT_THEME: Theme = "light";

export function parseTheme(value: string | null): Theme {
  return value === "system" || value === "dark" ? value : DEFAULT_THEME;
}

/** Puts the preference on `<html>`. "system" removes both classes. */
export function applyTheme(theme: Theme): void {
  const { classList } = document.documentElement;
  classList.toggle("light", theme === "light");
  classList.toggle("dark", theme === "dark");
}

/**
 * Runs in `<head>` before the first paint, so a stored "dark" or "system"
 * never flashes the light palette. The server sends `<html class="light">`,
 * the default, and this only has to undo it. It is `applyTheme(parseTheme(...))`
 * written out by hand because nothing from the bundle has loaded yet.
 */
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});if(t==="dark"||t==="system"){var c=document.documentElement.classList;c.remove("light");if(t==="dark")c.add("dark")}}catch(e){}})()`;
