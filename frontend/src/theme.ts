/**
 * Theme switcher. Reads/writes a "light" / "dark" preference in localStorage
 * and toggles `class="light"` on <html> (Tailwind dark-mode class strategy).
 * Defaults to dark.
 */
export type Theme = "dark" | "light";
const KEY = "logicgate.theme";

export function getTheme(): Theme {
  try {
    const t = localStorage.getItem(KEY);
    if (t === "light" || t === "dark") return t;
  } catch { /* */ }
  return "dark";
}

export function setTheme(t: Theme): void {
  try {
    localStorage.setItem(KEY, t);
  } catch { /* */ }
  applyTheme(t);
}

export function applyTheme(t: Theme): void {
  const html = document.documentElement;
  if (t === "light") html.classList.add("light");
  else                html.classList.remove("light");
}

export function toggleTheme(): Theme {
  const next: Theme = getTheme() === "dark" ? "light" : "dark";
  setTheme(next);
  return next;
}

// Apply ASAP so the page paints in the right mode without a flash.
applyTheme(getTheme());
