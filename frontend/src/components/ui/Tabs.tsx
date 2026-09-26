"use client";

import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import s from "./ui.module.css";

export interface TabDef {
  id: string;
  label: ReactNode;
  count?: number | null;
}

/**
 * Accessible tab list (WAI-ARIA tabs pattern): arrow keys, Home and End move between tabs; only the active tab
 * is in the tab order. Render the active panel with <TabPanel>.
 */
export function Tabs({
  tabs,
  active,
  onChange,
  label,
  idBase,
}: {
  tabs: TabDef[];
  active: string;
  onChange: (id: string) => void;
  label: string;
  idBase?: string;
}) {
  const auto = useId();
  const base = idBase ?? auto;
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    let next = -1;
    if (e.key === "ArrowRight") next = (i + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    if (next < 0) return;
    e.preventDefault();
    onChange(tabs[next].id);
    refs.current[next]?.focus();
  };

  return (
    <div role="tablist" aria-label={label} className={`${s.tabs} no-print`}>
      {tabs.map((t, i) => {
        const selected = t.id === active;
        return (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            id={`${base}-tab-${t.id}`}
            aria-selected={selected}
            aria-controls={`${base}-panel-${t.id}`}
            tabIndex={selected ? 0 : -1}
            className={`${s.tab} ${selected ? s.tabActive : ""}`}
            onClick={() => onChange(t.id)}
            onKeyDown={(e) => onKey(e, i)}
          >
            {t.label}
            {t.count !== undefined && t.count !== null ? <span className={s.tabCount}>{t.count.toLocaleString("en-IN")}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ idBase, id, children }: { idBase: string; id: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={`${idBase}-panel-${id}`} aria-labelledby={`${idBase}-tab-${id}`} tabIndex={0} style={{ outlineOffset: 4 }}>
      {children}
    </div>
  );
}
