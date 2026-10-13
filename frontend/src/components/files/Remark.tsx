"use client";

/**
 * A remark clamped to two lines with "Show more" (design portal-files-alerts, decision 12). The full text is always in
 * the page, so a screen reader reads it whole; the clamp is visual only.
 */
import { useId, useState } from "react";

import { Button } from "@/components/ui";
import { T } from "@/lib/messages";

import s from "./files.module.css";

/** Roughly two lines of the column; a text with a third line break is long whatever its length. */
const LONG_CHARS = 140;

export function isLongRemark(text: string): boolean {
  return text.length > LONG_CHARS || text.split("\n").length > 2;
}

export function Remark({ text }: { text: string | null | undefined }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  if (!text) return <span className="muted">—</span>;
  const long = isLongRemark(text);
  return (
    <div className={s.remark}>
      <div id={id} className={long && !open ? s.clamp : s.full}>
        {text}
      </div>
      {long ? (
        <Button variant="link" aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>
          {open ? T.files.showLess : T.files.showMore}
        </Button>
      ) : null}
    </div>
  );
}
