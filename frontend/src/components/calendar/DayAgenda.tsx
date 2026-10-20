"use client";

/**
 * The agenda of the chosen day (design portal-ui-redesign, decision 8), the accessible version of the grid: one row per
 * item with its kind as a fixed-width leading badge (Hearing / Due / Confirm, the alignment rule of decision 15), the
 * case link and the detail — court and item, the pending action, or "Next date from order · confirm" with a link to
 * the review item.
 */
import Link from "next/link";

import { Badge, Card, CaseLink, EmptyState, Lead, ListRow } from "@/components/ui";
import type { MyCalendarItem } from "@/lib/api/types";
import { KIND_TONE, type Kind } from "@/lib/calendar";
import { formatDayLong } from "@/lib/format";
import { T } from "@/lib/messages";

import s from "./calendar.module.css";

function Detail({ item }: { item: MyCalendarItem }) {
  if (item.kind === "hearing") {
    return <span className="muted">{T.mycal.hearingDetail(item.court_no ?? null, item.item_no ?? null, item.purpose ?? null)}</span>;
  }
  if (item.kind === "action_due") {
    return (
      <span className="muted">
        {item.pending_action_label ?? item.pending_action}
        {item.overdue ? ` · ${T.mycal.overdue}` : ""}
      </span>
    );
  }
  return (
    <span className="muted">
      {T.mycal.confirmDetail} ·{" "}
      <Link href={`/alerts/next-dates?q=${encodeURIComponent(item.case.id)}`}>{T.mycal.openReview}</Link>
    </span>
  );
}

export function DayAgenda({ day, items }: { day: string | null; items: MyCalendarItem[] }) {
  return (
    <div className={s.agenda}>
      <Card title={day ? formatDayLong(day) : T.mycal.agenda}>
        <section aria-label={T.mycal.agenda} aria-live="polite">
          {items.length === 0 ? (
            <EmptyState title={T.mycal.emptyTitle}>{T.mycal.emptyText}</EmptyState>
          ) : (
            <ul className={s.agendaList}>
              {items.map((item, i) => (
                <ListRow
                  key={`${item.kind}-${item.case.id}-${i}`}
                  as="li"
                  lead={
                    <Lead>
                      <Badge tone={KIND_TONE[item.kind as Kind]}>{T.mycal.badges[item.kind] ?? item.kind}</Badge>
                    </Lead>
                  }
                >
                  <CaseLink value={item.case} />
                  <div>
                    <Detail item={item} />
                  </div>
                </ListRow>
              ))}
            </ul>
          )}
        </section>
      </Card>
    </div>
  );
}
