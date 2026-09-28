"use client";
// V21.2 — AUTOCOMPLETE, grouped by type. Reuses the exact same
// debounce hook V21.1's SearchBox already exports (useDebouncedValue)
// rather than reimplementing debouncing, but renders suggestions
// grouped under headings (Job Titles / Companies / Government
// Organizations / Skills / Locations) with keyboard navigation across
// the flattened group order, per the spec's "Group suggestions by
// type... Keyboard navigation must work."
import { useEffect, useRef, useState } from "react";
import { useDebouncedValue } from "@/components/search/SearchBox";
import { AUTOCOMPLETE_GROUP_LABELS, fetchGroupedAutocomplete } from "@/lib/search";

export default function DiscoverySearchBox({
  value,
  onChange,
  onSubmit,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (v: string) => void;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [groups, setGroups] = useState<Record<string, string[]>>({});
  const debounced = useDebouncedValue(value, 250);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    if (!debounced.trim()) {
      setGroups({});
      return;
    }
    fetchGroupedAutocomplete(debounced).then((g) => {
      if (!cancelled) setGroups(g);
    });
    return () => {
      cancelled = true;
    };
  }, [debounced]);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const flat: { group: string; text: string }[] = [];
  for (const [group, items] of Object.entries(groups)) {
    for (const text of items) flat.push({ group, text });
  }

  function choose(text: string) {
    onChange(text);
    setOpen(false);
    setActiveIndex(-1);
    onSubmit(text);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || flat.length === 0) {
      if (e.key === "Enter") onSubmit(value);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, flat.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (activeIndex >= 0 && activeIndex < flat.length) choose(flat[activeIndex].text);
      else {
        setOpen(false);
        onSubmit(value);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  let flatIdx = -1;

  return (
    <div ref={containerRef} style={{ position: "relative", flex: 1 }}>
      <input
        className="field"
        role="combobox"
        aria-expanded={open && flat.length > 0}
        aria-autocomplete="list"
        aria-controls="discovery-autocomplete-list"
        placeholder={placeholder || 'Try "Java Developer Noida" or "SSC Graduate Jobs"'}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
          setActiveIndex(-1);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {open && flat.length > 0 && (
        <ul id="discovery-autocomplete-list" role="listbox" className="search-suggestions">
          {Object.entries(groups).map(([group, items]) => (
            <li key={group} role="presentation">
              <div className="muted" style={{ fontSize: 12, fontWeight: 700, padding: "6px 10px 2px" }}>
                {AUTOCOMPLETE_GROUP_LABELS[group] || group}
              </div>
              <ul role="group">
                {items.map((text) => {
                  flatIdx += 1;
                  const idx = flatIdx;
                  return (
                    <li key={text} role="option" aria-selected={idx === activeIndex}>
                      <button
                        type="button"
                        className={`linkbtn${idx === activeIndex ? " chip-active" : ""}`}
                        style={{ display: "block", width: "100%", textAlign: "left", padding: "6px 10px" }}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => choose(text)}
                      >
                        {text}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
