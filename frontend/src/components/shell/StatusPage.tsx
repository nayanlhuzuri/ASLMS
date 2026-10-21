/**
 * The error and not-found pages (design portal-ui-redesign, decisions 2 and 26, round 5): the brand on top and the
 * empty-state pattern below (the icon circle, a title, one line and the way on). They render outside the portal's
 * shell, so they carry the brand themselves.
 */
import type { ReactNode } from "react";

import { EmptyState } from "@/components/ui";

import { Brand } from "./Brand";
import s from "./shell.module.css";

export function StatusPage({
  title,
  text,
  actions,
  alert,
}: {
  title: string;
  text: string;
  actions: ReactNode;
  /** An error: announced at once. */
  alert?: boolean;
}) {
  return (
    <main id="main" className={s.statusPage}>
      <div className={s.statusCard} role={alert ? "alert" : undefined}>
        <Brand />
        <EmptyState>
          <h1 className={s.statusTitle}>{title}</h1>
          <p>{text}</p>
          <div className={s.statusActions}>{actions}</div>
        </EmptyState>
      </div>
    </main>
  );
}
