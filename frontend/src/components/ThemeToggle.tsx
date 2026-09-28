"use client";
// V19.3 — Government Portal. "Dark mode ready": a data-theme attribute
// on <html> plus the CSS variable overrides in globals.css. Persisted
// in localStorage so it survives a reload/navigation.
import { useEffect, useState } from "react";

export default function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem("careeros_theme");
    const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
    const isDark = saved ? saved === "dark" : !!prefersDark;
    setDark(isDark);
    document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    document.documentElement.setAttribute("data-theme", next ? "dark" : "light");
    localStorage.setItem("careeros_theme", next ? "dark" : "light");
  }

  return (
    <button className="theme-toggle" onClick={toggle} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}>
      {dark ? "Light mode" : "Dark mode"}
    </button>
  );
}
