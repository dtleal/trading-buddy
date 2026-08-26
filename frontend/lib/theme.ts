"use client";

import { useSyncExternalStore } from "react";

export type Theme = "dark" | "light";

const KEY = "dtb-theme";
const listeners = new Set<() => void>();

function currentTheme(): Theme {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.classList.contains("light") ? "light" : "dark";
}

export function setTheme(theme: Theme) {
  const root = document.documentElement;
  root.classList.toggle("light", theme === "light");
  root.classList.toggle("dark", theme === "dark");
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // private mode / storage blocked — the class still flips for this tab
  }
  listeners.forEach((fn) => fn());
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Current theme, re-rendering the component when the toggle flips it. */
export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, currentTheme, () => "dark" as Theme);
}

/**
 * lightweight-charts paints on a canvas, so it can't read the Tailwind
 * variables — it needs the raw colors handed to it on every theme change.
 */
export function chartColors(theme: Theme) {
  return theme === "light"
    ? { text: "#52525b", grid: "rgba(212,212,216,0.7)", border: "#e4e4e7" }
    : { text: "#a1a1aa", grid: "rgba(63,63,70,0.4)", border: "#27272a" };
}
