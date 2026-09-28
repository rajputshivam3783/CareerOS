"use client";

// V21.1 — reusable Search Box with autocomplete. Debounces keystrokes
// itself (250ms) so callers just get onChange/onSubmit — no caller
// has to think about request timing or race conditions between two
// in-flight autocomplete calls (guarded below with a request-id check).

import { useEffect, useRef, useState } from "react";
import { EntityType, fetchAutocomplete } from "@/lib/search";

export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

export default function SearchBox({
  value,
  onChange,
  onSubmit,
  entityTypes,
  placeholder = "Search jobs, companies, skills…",
  autoFocus = false,
}: {
  value: string;
  onChange: (q: string) => void;
  onSubmit: (q: string) => void;
  entityTypes?: EntityType[];
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const debounced = useDebouncedValue(value, 250);
  const requestId = useRef(0);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const thisRequest = ++requestId.current;
    if (!debounced.trim()) {
      setSuggestions([]);
      return;
    }
    fetchAutocomplete(debounced, entityTypes).then((results) => {
      // Ignore a stale response that resolved after a newer request.
      if (thisRequest === requestId.current) setSuggestions(results);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  function choose(term: string) {
    onChange(term);
    onSubmit(term);
    setOpen(false);
    setSuggestions([]);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((i) => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((i) => Math.max(i - 1, -1));
    } else if (e.key === "Enter") {
      if (open && highlighted >= 0 && suggestions[highlighted]) {
        choose(suggestions[highlighted]);
      } else {
        setOpen(false);
        onSubmit(value);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="search" ref={boxRef} style={{ position: "relative" }}>
      <input
        className="field"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        placeholder={placeholder}
        autoFocus={autoFocus}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
          setHighlighted(-1);
        }}
        onFocus={() => suggestions.length > 0 && setOpen(true)}
        onKeyDown={onKeyDown}
      />
      <button className="btn" onClick={() => { setOpen(false); onSubmit(value); }}>
        Search
      </button>
      {open && suggestions.length > 0 && (
        <ul className="search-suggestions" role="listbox">
          {suggestions.map((s, i) => (
            <li
              key={s}
              role="option"
              aria-selected={i === highlighted}
              className={i === highlighted ? "search-suggestion-active" : ""}
              onMouseDown={() => choose(s)}
              onMouseEnter={() => setHighlighted(i)}
            >
              {s}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
