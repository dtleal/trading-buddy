"use client";

import { Moon, Sun } from "lucide-react";
import { setTheme, useTheme } from "@/lib/theme";

/** Flips the app between dark and light, remembered in localStorage. */
export function ThemeToggle() {
  const theme = useTheme();
  const next = theme === "dark" ? "light" : "dark";

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      title={next === "light" ? "Modo claro" : "Modo escuro"}
      aria-label={next === "light" ? "Modo claro" : "Modo escuro"}
      className="rounded-md border border-zinc-800 p-1.5 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-100"
    >
      {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}
