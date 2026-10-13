"use client";

/**
 * The applied filters as chips (design portal-filters, decision 9): one per filter, each with a remove button named
 * "Remove filter <label>", and "Clear all". Removing applies at once.
 */
import { Button } from "@/components/ui";
import type { Chip } from "@/lib/filters";
import { T } from "@/lib/messages";

import s from "./filters.module.css";

export function FilterChips({
  chips,
  onRemove,
  onClearAll,
}: {
  chips: Chip[];
  onRemove: (keys: string[]) => void;
  onClearAll: () => void;
}) {
  if (chips.length === 0) return null;
  return (
    <div className={s.actions}>
      <ul className={s.chips} aria-label={T.filters.applied}>
        {chips.map((c) => (
          <li key={c.keys.join(",")} className={s.chip}>
            <span>{c.label}</span>
            <button
              type="button"
              className={s.chipRemove}
              aria-label={T.filters.remove(c.label)}
              title={T.filters.remove(c.label)}
              onClick={() => onRemove(c.keys)}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <Button variant="link" onClick={onClearAll}>
        {T.filters.clearAll}
      </Button>
    </div>
  );
}
